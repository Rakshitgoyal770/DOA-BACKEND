# eval/eval_harness.py
"""
eval/eval_harness.py — Measures how good the chat's answers are.

WHAT THIS FILE DOES
    For every case in eval/golden_dataset.py it runs the REAL chat pipeline
    (features/chat/service.py run_chat — the same function POST /chat uses, so
    the SQL facts and author labels are included) and scores:
        context precision  share of retrieved documents that are expected ones
        context recall     share of expected documents that were retrieved
        faithfulness       LLM judge: are the answer's claims supported by the sources
                           and the PROPOSAL FACTS? Sentences marked [Background]
                           (allowed general knowledge) are left out of this score.
        background share   share of sentences marked [Background] (exact). If it
                           grows, answers lean on the model's memory instead of our data.
        answer relevancy   LLM judge: does the answer address the question?
    Precision, recall and background share are exact; the judged scores depend on the judge model.

RUN
    python -m eval.eval_harness        (makes LLM calls: one answer + two judgements per case)

WHERE IT SITS
    THIS FILE --> features/chat/service.py run_chat (answers)
              --> features/chat/llm.py generate      (the judge)
              --> eval/golden_dataset.py             (questions and expected documents)
"""

import re
import sys

from eval.golden_dataset import GOLDEN_DATASET
from features.chat.context import format_facts
from features.chat.llm import generate
from features.chat.prompt import BACKGROUND_TAG
from features.chat.service import run_chat

if sys.platform == "win32":          # print non-ASCII answers on the Windows console
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def score_context_precision(retrieved_ids: list[str], ground_truth_ids: list[str]) -> float:
    """
    Share of retrieved documents that are expected ones (0-1).

    Parameters (where they come from — run_eval):
        retrieved_ids    - ids of run_chat()'s chunks.
        ground_truth_ids - the case's ground_truth_context_ids.
    """
    if not retrieved_ids:
        return 0.0
    return sum(1 for cid in retrieved_ids if cid in ground_truth_ids) / len(retrieved_ids)


def score_context_recall(retrieved_ids: list[str], ground_truth_ids: list[str]) -> float:
    """
    Share of expected documents that were retrieved (0-1). Same parameters as
    score_context_precision.
    """
    if not ground_truth_ids:
        return 1.0
    return sum(1 for cid in ground_truth_ids if cid in retrieved_ids) / len(ground_truth_ids)


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


def _average(values: list) -> float:
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if valid else 0.0


def run_eval() -> list[dict]:
    """
    Score every golden case and print a summary. Returns one dict per scored case:
    {question, provider, precision, recall, faithfulness, relevancy}.
    """
    results = []
    for case in GOLDEN_DATASET:
        print(f"\n{'=' * 60}\nQuestion: {case['question']}")
        out = run_chat(case["question"], proposal_id=case["proposal_id"])
        if out["answer"] is None:
            print("  No chunks retrieved — skipping generation.")
            continue

        retrieved_ids = [c["id"] for c in out["chunks"]]
        precision = score_context_precision(retrieved_ids, case["ground_truth_context_ids"])
        recall = score_context_recall(retrieved_ids, case["ground_truth_context_ids"])
        faithfulness, faith_reason = score_faithfulness(
            out["answer"], [c["document"] for c in out["chunks"]], out["facts"])
        background = background_share(out["answer"])
        relevancy, rel_reason = score_answer_relevancy(case["question"], out["answer"])

        print(f"  Generated by: {out['provider']}")
        print(f"  Context Precision: {precision:.2f}")
        print(f"  Context Recall:    {recall:.2f}")
        print(f"  Faithfulness:      {faithfulness} ({faith_reason})")
        print(f"  Background share:  {background:.2f}")
        print(f"  Answer Relevancy:  {relevancy} ({rel_reason})")
        results.append({"question": case["question"], "provider": out["provider"],
                        "precision": precision, "recall": recall,
                        "faithfulness": faithfulness, "background": background,
                        "relevancy": relevancy})

    print(f"\n{'=' * 60}\nSUMMARY ({len(results)} of {len(GOLDEN_DATASET)} cases scored)")
    if results:
        print(f"Avg Context Precision: {_average([r['precision'] for r in results]):.2f}")
        print(f"Avg Context Recall:    {_average([r['recall'] for r in results]):.2f}")
        print(f"Avg Faithfulness:      {_average([r['faithfulness'] for r in results]):.2f}")
        print(f"Avg Background share:  {_average([r['background'] for r in results]):.2f}")
        print(f"Avg Answer Relevancy:  {_average([r['relevancy'] for r in results]):.2f}")
    return results


if __name__ == "__main__":
    run_eval()


# ── Where control goes next ───────────────────────────────────────────────────
# The summary is printed and the program ends. If a score drops after a change,
# look at features/chat/prompt.py (instructions) and features/chat/retrieval.py
# (which chunks were found) first.
# If every LLM provider fails: run_chat or the judge raises and the run stops.
