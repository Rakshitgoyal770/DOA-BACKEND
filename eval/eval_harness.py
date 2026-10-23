# eval/eval_harness.py
"""
eval/eval_harness.py — Runs the golden dataset and reports which question types pass.

WHAT THIS FILE DOES
    For every case in eval/golden_dataset.py it runs the REAL chat pipeline
    (features/chat/service.py run_chat — the same function POST /chat uses) and
    grades the answer with eval/checks.py:
        exact      numbers, names, retrieved sources, [Background] tag
        judged     advice / unanswerable / ambiguous behaviour (one YES/NO question)
    and prints a pass/fail table per question type (level / intent), with the
    reason for every failure. Results are saved to eval/results/ so runs can be compared.

    ERRORS ARE NOT FAILURES. If no LLM provider could answer (a missing package, an
    exhausted free-tier quota), the case is counted as an ERROR and left out of the
    pass rate, so an infrastructure problem can never look like a wrong answer.

    With --judge it also computes the LLM-judged quality scores:
        faithfulness       are the answer's claims supported by the sources and the
                           PROPOSAL FACTS? ([Background] sentences are left out)
        answer relevancy   does the answer address the question?
    plus the exact "background share" (sentences marked [Background]).

RUN
    python -m eval.eval_harness                     all cases, exact checks (+ behaviour judge)
    python -m eval.eval_harness --only proposal     cases whose id/level/intent contains "proposal"
    python -m eval.eval_harness --judge             also faithfulness + relevancy (3 more LLM calls a case)
    python -m eval.eval_harness --regrade eval/results/run_X.json
                                                    re-score a saved run with the CURRENT checks and
                                                    dataset. Reuses the saved answers and behaviour
                                                    verdicts: zero LLM calls, so no quota.
    Run it with the project's own interpreter (.venv), which has groq / mistralai installed.
    Each case makes 1 LLM call for the answer (+1 for judged behaviours). Free tiers
    rate-limit, so cases are spaced by --pause seconds (default 2).

WHERE IT SITS
    THIS FILE --> features/chat/service.py run_chat (answers)
              --> eval/checks.py grade              (pass / fail)
              --> features/chat/llm.py generate      (the judge)
              --> eval/golden_dataset.py             (the cases)
"""

import argparse
import datetime
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

from eval.checks import grade
from eval.golden_dataset import GOLDEN_DATASET
from features.chat.context import format_facts
from features.chat.llm import generate
from features.chat.prompt import BACKGROUND_TAG
from features.chat.service import run_chat

RESULTS_DIR = Path(__file__).with_name("results")

if sys.platform == "win32":          # print non-ASCII answers on the Windows console
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ── LLM-judged quality scores (--judge) ───────────────────────────────────────

def _judge(instruction: str) -> tuple[float | None, str]:
    """
    Ask the LLM judge and read "SCORE: X.X | REASON: ..." from its reply.
    Returns (score or None if the reply had no score, the full reply).

    Parameter (where it comes from):
        instruction - built by score_faithfulness / score_answer_relevancy.
    The judge is the same provider chain as the chat (features/chat/llm.py).
    """
    prompt = (
        "You are a strict evaluation judge. " + instruction +
        "\nRespond ONLY in this exact format: SCORE: X.X | REASON: one sentence\n"
        "Where X.X is a number from 0.0 to 1.0."
    )
    reply, _provider = generate([{"role": "user", "content": prompt}])
    m = re.search(r"SCORE:\s*([0-9.]+)", reply, re.IGNORECASE)
    return (float(m.group(1)) if m else None), reply


def _sentences(text: str) -> list[str]:
    """Split an answer into sentences (good enough for counting [Background] ones)."""
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def background_share(answer: str) -> float:
    """
    Share of the answer's sentences marked [Background] (0-1), exact.

    Parameter (where it comes from): run_chat()["answer"], via run_eval.
    """
    sentences = _sentences(answer)
    return sum(BACKGROUND_TAG in s for s in sentences) / len(sentences) if sentences else 0.0


def score_faithfulness(answer: str, context_chunks: list[str], facts: list[dict]) -> tuple[float | None, str]:
    """
    Judge: what fraction of the answer's specific claims are supported by the
    material the model was given — the source chunks AND the PROPOSAL FACTS.
    [Background] sentences are general knowledge the prompt allows; they are
    excluded here and tracked by background_share instead.

    Parameters (where they come from — run_eval):
        answer         - run_chat()["answer"].
        context_chunks - the text of run_chat()'s chunks.
        facts          - run_chat()["facts"] (shown to the judge exactly as the prompt showed them).
    """
    material = "\n\n".join(context_chunks)
    if facts:
        material = "PROPOSAL FACTS:\n" + "\n".join(format_facts(f) for f in facts) + "\n\n" + material
    return _judge("Given the material below and a generated answer, determine what fraction of "
                  f"the answer's claims are directly supported by the material. IGNORE every sentence "
                  f"that starts with {BACKGROUND_TAG}: it is permitted general background and must not "
                  "count either way.\n\n"
                  f"Material:\n{material}\n\nGenerated Answer:\n{answer}")


def score_answer_relevancy(question: str, answer: str) -> tuple[float | None, str]:
    """
    Judge: does the answer address the question (0 = off-topic, 1 = on-topic)?

    Parameters (where they come from — run_eval): the case's question and run_chat()'s answer.
    """
    return _judge("Does the following answer actually address the question asked, regardless "
                  "of factual correctness? 0.0 means off-topic, 1.0 directly on-topic.\n\n"
                  f"Question: {question}\n\nAnswer: {answer}")


# ── Running the cases ─────────────────────────────────────────────────────────

def run_case(case: dict, judge: bool) -> dict:
    """
    Answer one case with the real pipeline and grade it.

    Parameters (where they come from — run_eval):
        case  - one GOLDEN_DATASET entry.
        judge - the --judge flag.
    Only scope["proposal_id"] is passed on: run_chat has no DAO scope yet, so a
    dao_id is ignored (those cases show what happens without it).
    """
    started = time.time()
    try:
        out = run_chat(case["question"], proposal_id=case["scope"].get("proposal_id"))
    except Exception as e:                       # every LLM provider failed, etc.
        return {"id": case["id"], "question": case["question"], "passed": False, "error": True,
                "failures": [f"error: {e}"[:200]], "recall": 0.0,
                "answer": None, "provider": None, "seconds": round(time.time() - started, 1)}

    retrieved = [c["id"] for c in out["chunks"]]
    result = {"id": case["id"], "question": case["question"], **grade(case, out["answer"], retrieved),
              "answer": out["answer"], "provider": out["provider"], "retrieved": retrieved}
    if judge and out["answer"]:
        result["faithfulness"], _ = score_faithfulness(out["answer"], [c["document"] for c in out["chunks"]], out["facts"])
        result["relevancy"], _ = score_answer_relevancy(case["question"], out["answer"])
        result["background_share"] = background_share(out["answer"])
    result["seconds"] = round(time.time() - started, 1)
    return result


def print_report(cases: list[dict], results: list[dict]):
    """
    Pass/fail per question type, then every failure with its reason.
    Cases that ended in an ERROR (no provider could answer) are listed separately
    and excluded from the pass rate.

    Parameters (where they come from — run_eval / regrade):
        cases   - the golden cases that were run (for level, intent and "needs").
        results - one result dict per case.
    """
    by_id = {c["id"]: c for c in cases}
    groups = defaultdict(list)
    for r in results:
        c = by_id[r["id"]]
        groups[(c["level"], c["intent"])].append(r)

    print(f"\n{'LEVEL':<10} {'TYPE':<16} {'PASS':>6} {'ERR':>4}   NEEDS (feature not built yet)")
    print("-" * 82)
    for (level, intent), rs in sorted(groups.items()):
        answered = [r for r in rs if not r.get("error")]
        passed = sum(r["passed"] for r in answered)
        errors = len(rs) - len(answered)
        needs = {by_id[r["id"]]["needs"] for r in rs} - {None}
        mark = "ok " if answered and passed == len(answered) else ("-- " if passed == 0 else "~  ")
        mark = "?  " if not answered else mark
        print(f"{level:<10} {intent:<16} {passed:>2}/{len(answered):<3} {errors or '':>4} {mark} {', '.join(needs)}")
    answered = [r for r in results if not r.get("error")]
    errors = len(results) - len(answered)
    print("-" * 82)
    print(f"{'PASSED':<27} {sum(r['passed'] for r in answered):>2}/{len(answered)} answered cases")
    if errors:
        print(f"{'ERRORS':<27} {errors} cases got no answer (provider problem, NOT counted as failures) - rerun them")

    print("\nFAILURES")
    for r in answered:
        if not r["passed"]:
            print(f"  {r['id']}: " + " | ".join(r["failures"]))
    for r in results:
        if r.get("error"):
            print(f"  [error, not scored] {r['id']}: {r['failures'][0]}")

    judged = [r for r in results if r.get("faithfulness") is not None]
    if judged:
        avg = lambda k: sum(r[k] for r in judged if r.get(k) is not None) / len(judged)
        print(f"\nJUDGED ({len(judged)} answers): faithfulness {avg('faithfulness'):.2f} | "
              f"relevancy {avg('relevancy'):.2f} | background share {avg('background_share'):.2f}")


def regrade(path: str) -> list[dict]:
    """
    Re-score a saved run with the current checks and dataset, reusing its answers
    and its earlier behaviour verdicts. Makes NO LLM calls, so it costs no quota.

    Parameter (where it comes from):
        path - the --regrade flag: a file in eval/results/ written by run_eval.
    Cases whose question text changed since the run are skipped (their saved answer
    belongs to a different question), as are cases no longer in the dataset.
    """
    saved = json.loads(Path(path).read_text(encoding="utf-8"))["results"]
    by_id = {c["id"]: c for c in GOLDEN_DATASET}
    results, skipped = [], []
    for old in saved:
        case = by_id.get(old["id"])
        if case is None or (old.get("question") and old["question"] != case["question"]):
            skipped.append(old["id"])
            continue
        if old.get("error"):
            results.append(old)
            continue
        # Reuse the earlier behaviour verdict (it may have cost an LLM judge call); everything
        # else - numbers, names, sources, the [Background] tag - is recomputed.
        earlier = [f for f in old["failures"] if f.startswith("behavior:")]
        verdict = (not earlier, earlier[0][len("behavior: "):] if earlier else "")
        new = {**old, "question": case["question"],
               **grade(case, old["answer"], old.get("retrieved", []), behavior_result=verdict)}
        results.append(new)
    if skipped:
        print(f"Skipped (case removed or question changed since this run - rerun them): {skipped}")
    print_report([by_id[r["id"]] for r in results], results)
    return results


def run_eval(only: str | None = None, judge: bool = False, pause: float = 2.0) -> list[dict]:
    """
    Run the (filtered) golden cases, print the report, and save every result.

    Parameters (where they come from — the command line below):
        only  - --only: keep cases whose id, level or intent contains this text.
        judge - --judge: also compute faithfulness / relevancy.
        pause - --pause: seconds between cases (free-tier rate limits).
    """
    cases = [c for c in GOLDEN_DATASET
             if not only or only in c["id"] or only in c["level"] or only in c["intent"]]
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"run_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    def save(finished: bool):
        # Rewritten after EVERY case, so a crash or a kill loses nothing done so far.
        out.write_text(json.dumps({"cases": len(cases), "finished": finished,
                                   "done": len(results), "passed": sum(r["passed"] for r in results),
                                   "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")

    results = []
    for i, case in enumerate(cases, 1):
        r = run_case(case, judge)
        results.append(r)
        save(finished=False)
        print(f"[{i}/{len(cases)}] {'PASS' if r['passed'] else 'FAIL'} {case['id']} "
              f"({r.get('provider')}, {r['seconds']}s)", flush=True)   # show progress at once, even in a log file
        time.sleep(pause)

    save(finished=True)
    print_report(cases, results)
    print(f"\nSaved: {out}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the golden dataset")
    parser.add_argument("--only", default=None, help="Keep cases whose id / level / intent contains this text")
    parser.add_argument("--judge", action="store_true", help="Also LLM-judge faithfulness and relevancy")
    parser.add_argument("--pause", type=float, default=2.0, help="Seconds between cases (default 2)")
    parser.add_argument("--regrade", default=None, metavar="FILE",
                        help="Re-score a saved run from eval/results/ with the current checks (no answer calls)")
    args = parser.parse_args()
    if args.regrade:
        regrade(args.regrade)
    else:
        run_eval(args.only, args.judge, args.pause)


# ── Where control goes next ───────────────────────────────────────────────────
# The report is printed and saved to eval/results/. For a failing type, start with
# the file named in its "needs" column, or features/chat/prompt.py (instructions) and
# features/chat/retrieval.py (which chunks were found).
# If every LLM provider fails for a case: it is recorded as "error" and the run continues.
