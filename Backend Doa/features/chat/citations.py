# features/chat/citations.py
"""
features/chat/citations.py — Checks the citations in an answer against the evidence the writer was given.

WHAT THIS FILE DOES
    The writer is told to cite passages as [Source N] and database facts as [Facts]. Nothing made
    sure those citations point at anything. check_citations() reads the finished answer and reports:

        invalid_sources       [Source 9] when only 4 sources were given (or [Source 0])
        facts_without_facts   [Facts] cited when no database lookup was part of the evidence
        unsupported_numbers   numbers in the answer that appear nowhere in the evidence or the question
                              (a hint of an invented number, not proof: a sum the writer computed is
                              reported too)
        ok                    no invalid_sources and no facts_without_facts

    What it does NOT check: whether a cited source really supports the sentence it is attached to.
    That needs a model (the faithfulness judge in eval/eval_harness.py).

    strip_invalid() removes the citation markers that point at nothing, for the case where the
    writer repeats the mistake after being asked to fix it.

WHERE IT SITS
    features/chat/service.py run_chat() --> THIS FILE (after the writer has answered)
"""

import re

_BRACKET = re.compile(r"\[([^\[\]]{1,80})\]")
_SOURCE_NUMBERS = re.compile(r"\d+")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
MIN_DIGITS = 3        # shorter numbers ("3 options", "2 sources") are too common to check


def cited_sources(answer: str) -> list[int]:
    """The source numbers an answer cites, in order, without repeats: [Source 2], [Source 1, 3], [Source 1, Source 4]."""
    numbers: list[int] = []
    for inner in _BRACKET.findall(answer or ""):
        if inner.strip().lower().startswith("source"):
            for n in _SOURCE_NUMBERS.findall(inner):
                if int(n) not in numbers:
                    numbers.append(int(n))
    return numbers


def cites_facts(answer: str) -> bool:
    """True if the answer contains a [Facts] citation."""
    return any(inner.strip().lower() == "facts" for inner in _BRACKET.findall(answer or ""))


def _normalise(number: str) -> str:
    """'63,845' -> '63845', '11.50' -> '11.5': the form numbers are compared in."""
    number = number.replace(",", "").rstrip(".")
    return number.rstrip("0").rstrip(".") if "." in number else number


def unsupported_numbers(answer: str, evidence_text: str) -> list[str]:
    """
    Numbers in the answer (three or more digits, or with decimals) that do not occur in `evidence_text`.

    Parameters (where they come from — check_citations): the answer, and everything the writer could
    see: the database facts, the sources, and the question.
    """
    haystack = {_normalise(n) for n in _NUMBER.findall(evidence_text or "")}
    haystack_text = (evidence_text or "").replace(",", "")
    missing: list[str] = []
    for raw in _NUMBER.findall(answer or ""):
        number = _normalise(raw)
        if len(number.replace(".", "")) < MIN_DIGITS and "." not in number:
            continue
        if number not in haystack and number not in haystack_text and raw not in missing:
            missing.append(raw)
    return missing


def check_citations(answer: str, source_count: int, has_facts: bool, evidence_text: str = "") -> dict:
    """
    {"ok", "cited_sources", "invalid_sources", "facts_without_facts", "unsupported_numbers"}.

    Parameters (where they come from — features/chat/service.py run_chat):
        answer        - the writer's answer.
        source_count  - how many numbered sources the writer was given.
        has_facts     - True if the writer was given a DATABASE FACTS block.
        evidence_text - the text of the facts, the sources and the question, for the number check
                        ("" skips it).
    """
    cited = cited_sources(answer)
    invalid = [n for n in cited if n < 1 or n > source_count]
    facts_without = cites_facts(answer) and not has_facts
    return {"ok": not invalid and not facts_without,
            "cited_sources": cited,
            "invalid_sources": invalid,
            "facts_without_facts": facts_without,
            "unsupported_numbers": unsupported_numbers(answer, evidence_text) if evidence_text else []}


def strip_invalid(answer: str, source_count: int, has_facts: bool) -> str:
    """The answer without citation markers that point at nothing (a source that was not given, [Facts] with no facts)."""
    def fix(match):
        inner = match.group(1)
        if inner.strip().lower() == "facts":
            return match.group(0) if has_facts else ""
        if inner.strip().lower().startswith("source"):
            numbers = [int(n) for n in _SOURCE_NUMBERS.findall(inner)]
            good = [n for n in numbers if 1 <= n <= source_count]
            if len(good) == len(numbers):
                return match.group(0)
            return f"[{', '.join(f'Source {n}' for n in good)}]" if good else ""
        return match.group(0)
    cleaned = _BRACKET.sub(fix, answer or "")
    return re.sub(r"[ \t]+([.,;:])", r"\1", re.sub(r"[ \t]{2,}", " ", cleaned))


def correction_request(check: dict, source_count: int) -> str:
    """The message that asks the writer to fix an answer whose citations point at nothing."""
    problems = []
    if check["invalid_sources"]:
        have = f"only Sources 1-{source_count} exist" if source_count else "no sources were given"
        problems.append(f"it cites {', '.join(f'[Source {n}]' for n in check['invalid_sources'])}, but {have}")
    if check["facts_without_facts"]:
        problems.append("it cites [Facts], but there are no database facts")
    return ("Your answer has a citation problem: " + "; ".join(problems) + ". Rewrite the answer. Cite only "
            "the sources that exist, and drop any claim you cannot support from them.")
