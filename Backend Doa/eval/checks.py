# eval/checks.py
"""
eval/checks.py — Decides whether one answer passes its golden case.

WHAT THIS FILE DOES
    Most checks are EXACT (plain code, no LLM), so the results are repeatable:
      check_numbers   every expected number appears in the answer
                      pct ±0.2 points · count exact · vp ±1%  ("1.2M", "14,194" understood)
      check_mentions  every expected name appears; "title:<t>" = most words of a title
      check_sources   at least one expected document was retrieved (+ recall)
      check_behavior  background_tagged is exact ("[Background]" present);
                      no_recommendation / say_insufficient / ask_clarify ask the
                      LLM judge one YES/NO question
    grade() combines them: a case passes only if every applicable check passes.

WHERE IT SITS
    eval/eval_harness.py (for each case) --> THIS FILE --> features/chat/llm.py (behaviour judge only)
"""

import re
import unicodedata

from features.chat.llm import generate
from features.chat.prompt import BACKGROUND_TAG

# A number, optionally followed by a scale: "33.0M", "1.5K", "33.0 million", "2 billion".
_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*"
                     r"(thousand|million|billion|[kKmMbB](?![a-zA-Z]))?", re.IGNORECASE)
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9}
_ASCII = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
                        "‘": "'", "’": "'", "“": '"', "”": '"'})
_STOP = {"the", "and", "for", "with", "from", "into", "this", "that", "proposal", "title"}


def normalize(text: str) -> str:
    """
    The text with typographic variants turned into plain ones, so matching does not
    depend on how a model happened to type them: non-breaking / narrow spaces become
    a normal space, curly quotes and long dashes become ASCII. (Models often write
    "A.J. Warner" with a narrow no-break space, which looks identical to "A.J. Warner".)

    Parameter (where it comes from): an answer, via numbers_in / check_mentions.
    """
    return unicodedata.normalize("NFKC", text or "").translate(_ASCII)


def numbers_in(text: str) -> list[float]:
    """
    Every number written in `text`, with thousands separators and scale words
    understood: '14,194' -> 14194, '33.0M' or '33.0 million' -> 33000000, '91.7%' -> 91.7.

    Parameter (where it comes from): the answer, via check_numbers.
    """
    found = []
    for whole, frac, suffix in _NUMBER.findall(normalize(text)):
        value = float(whole.replace(",", "") + (frac or ""))
        found.append(value * _SCALE[suffix.lower()] if suffix else value)
    return found


def _number_matches(expected: dict, values: list[float]) -> bool:
    target, kind = expected["value"], expected["kind"]
    if kind == "count":
        return any(v == target for v in values)
    if kind == "pct":
        return any(abs(v - target) <= 0.2 for v in values)
    return any(abs(v - target) <= 0.01 * abs(target) for v in values)      # vp: ±1%


def check_numbers(answer: str, expected: list[dict]) -> list[str]:
    """
    The labels of expected numbers that are missing from the answer ([] = pass).

    Parameters (where they come from — grade):
        answer   - run_chat()["answer"].
        expected - case["expected"]["numbers"], built by eval/build_golden.py.
    """
    values = numbers_in(answer)
    return [f"{e['label']}={e['value']}" for e in expected if not _number_matches(e, values)]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 4 and w not in _STOP}


def check_mentions(answer: str, expected: list[str]) -> list[str]:
    """
    Expected names missing from the answer ([] = pass). Plain strings must appear
    (case-insensitive); "title:<title>" passes if 60% of the title's main words appear,
    because an answer may shorten or rephrase a long title.

    Parameters (where they come from — grade): the answer and case["expected"]["mentions"].
    """
    text, missing = normalize(answer).lower(), []
    for m in expected:
        if m.startswith("title:"):
            words = _words(m[6:])
            if words and len(words & _words(text)) / len(words) < 0.6:
                missing.append(m)
        elif normalize(m).lower() not in text:
            missing.append(m)
    return missing


def _post_level(doc_id: str) -> str:
    """'forum_post_<p>_<post>_c2' -> 'forum_post_<p>_<post>': all chunks of one forum post count as that post."""
    return re.sub(r"_c\d+$", "", doc_id)


def check_sources(retrieved_ids: list[str], expected: list[str]) -> tuple[bool, float]:
    """
    (at least one expected document retrieved?, recall = share of expected ones retrieved).
    A long forum post is stored as several chunks; retrieving any of them counts as
    retrieving the post (see _post_level).

    Parameters (where they come from — grade): ids of run_chat()'s chunks and
    case["expected"]["sources"].
    """
    if not expected:
        return True, 1.0
    retrieved = {_post_level(i) for i in retrieved_ids}
    wanted = {_post_level(i) for i in expected}
    hit = wanted & retrieved
    return bool(hit), len(hit) / len(wanted)


_BEHAVIOR_QUESTIONS = {
    "no_recommendation": "Does the answer AVOID telling the user how to vote (it may present arguments, "
                         "results and positions, but must not recommend For, Against or Abstain)?",
    "say_insufficient": "Does the answer clearly say that it does not have the requested information, "
                        "instead of giving a specific answer?",
    "ask_clarify": "Does the answer ask the user which proposal they mean, or say it needs to know which "
                   "proposal before it can answer?",
}


def check_behavior(question: str, answer: str | None, behavior: str) -> tuple[bool, str]:
    """
    (passed?, reason). "answer" only needs an answer; "background_tagged" is exact;
    the others ask the LLM judge a YES/NO question.
    A refusal from the API (no answer because nothing relevant was found) counts as
    passing say_insufficient: the system did not make something up.

    Parameters (where they come from — grade): the case's question and expected
    behavior, and run_chat()["answer"] (None when the system found nothing).
    """
    if behavior == "answer":
        return answer is not None, "no answer (no relevant chunk found)" if answer is None else ""
    if answer is None:
        return behavior == "say_insufficient", "no answer (no relevant chunk found)"
    if behavior == "background_tagged":
        return BACKGROUND_TAG in answer, "" if BACKGROUND_TAG in answer else f"no {BACKGROUND_TAG} tag"
    reply, _ = generate([{"role": "user", "content":
                          f"You are a strict evaluation judge. {_BEHAVIOR_QUESTIONS[behavior]}\n"
                          "Reply with YES or NO, then one short reason.\n\n"
                          f"Question: {question}\n\nAnswer: {answer}"}])
    passed = reply.strip().upper().startswith("YES")
    return passed, "" if passed else f"judge: {reply.strip()[:120]}"


def grade(case: dict, answer: str | None, retrieved_ids: list[str],
          behavior_result: tuple[bool, str] | None = None) -> dict:
    """
    All checks for one case: {"passed", "failures": [...], "recall"}.

    Parameters (where they come from — eval/eval_harness.py run_eval / regrade):
        case            - one golden case.
        answer          - run_chat()["answer"] (None if nothing relevant was found).
        retrieved_ids   - ids of run_chat()["chunks"].
        behavior_result - (passed, reason) already decided by an earlier run. regrade
                          passes it so no LLM judge is called again; run_eval leaves it None.
    """
    exp, failures = case["expected"], []
    ok, reason = behavior_result if behavior_result is not None else check_behavior(case["question"], answer, exp["behavior"])
    if not ok:
        failures.append(f"behavior: {reason}")
    if answer is not None:
        failures += [f"number missing: {m}" for m in check_numbers(answer, exp["numbers"])]
        failures += [f"mention missing: {m[:60]}" for m in check_mentions(answer, exp["mentions"])]
    found, recall = check_sources(retrieved_ids, exp["sources"])
    if not found:
        failures.append("source: none of the expected documents was retrieved")
    return {"passed": not failures, "failures": failures, "recall": recall}


# ── Where control goes next ───────────────────────────────────────────────────
# Back to eval/eval_harness.py, which collects the grades and prints the pass/fail
# table per question type. To make a check stricter or looser, change it here and
# tests/test_golden.py pins its behaviour.
