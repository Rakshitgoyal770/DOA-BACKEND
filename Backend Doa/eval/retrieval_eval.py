# eval/retrieval_eval.py
"""
eval/retrieval_eval.py — Measures retrieval alone: does the search return the passage that answers the question?

WHAT THIS FILE DOES
    eval/retrieval_set.json holds questions that were each written from ONE indexed chunk. For
    every question this file runs the search and looks for that chunk in the result (a chunk
    with the same content_hash counts: a shared forum thread stores the same text under several
    proposals). No LLM is called: only the local embedding model and the index.

    Each question is searched in three ways, the three ways the chat searches:
        anywhere   no filter                       (a general question)
        dao        only that DAO's passages        (a question about one DAO)
        proposal   only that proposal's passages   (the user selected a proposal)
    and scored:
        found@5 / found@8   the passage is in the top 5 / 8        (ranking only, no distance cutoff)
        MRR                 average of 1/rank within the top 8     (how HIGH it is ranked)
        delivered@5         the passage is in the top 5 AND inside the distance cutoff the chat
                            uses for that kind of search: this is what the writer really gets
        right proposal@5    share of the top 5 that belong to the right proposal (anywhere / dao)

    LIMITS OF THIS MEASUREMENT
        The questions were written while looking at the passage, so they share some of its words:
        the scores are an upper bound for real user questions. Only one passage counts as right
        per question, although another passage may answer it as well.

RUN
    python -m eval.retrieval_eval                 # prints the table, saves eval/results/retrieval_<time>.json
    python -m eval.retrieval_eval --misses        # also lists the questions that were not found
    python -m eval.retrieval_eval --no-rerank     # the merged order only, to see what the reranker adds

    BASELINE (13 Nov 2026, before keyword search, the context line and the reranker; vector search
    only): found@5 anywhere 62.8, dao 65.1, proposal 72.1  (eval/results/retrieval_20261113_143157.json)

TO COMPARE ANOTHER SEARCH
    evaluate(cases, search) takes any function search(question, where, n) -> [chunk, ...] nearest
    first (chunks as features/chat/retrieval.py returns them), so a new retrieval method is
    scored with the same questions.
"""

import argparse
import datetime
import json
from pathlib import Path

SET_PATH = Path(__file__).parent / "retrieval_set.json"
RESULTS_DIR = Path(__file__).parent / "results"
DEPTH = 30                   # chunks fetched per search; ranks beyond this count as "not found"
KS = (5, 8)                  # the chat asks for 5 passages by default and shows the writer at most 8


def load_cases(path: Path = SET_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def current_search(question: str, where: dict | None, n: int) -> list[dict]:
    """The search the chat uses today: features/chat/retrieval.py, without its distance cutoff."""
    from features.chat.retrieval import retrieve
    return retrieve(question, n_results=n, where=where, max_distance=float("inf"))


def search_without_reranker(question: str, where: dict | None, n: int) -> list[dict]:
    """The same search with the reranker switched off: the merged vector + keyword order."""
    from features.chat.retrieval import retrieve
    return retrieve(question, n_results=n, where=where, max_distance=float("inf"), reranker=False)


def scopes(case: dict, dao_filter) -> dict:
    """The three filters a question is searched with, and the chat's distance cutoff for each."""
    from features.chat.tools import MAX_DISTANCE_ANYWHERE, MAX_DISTANCE_ONE_PROPOSAL
    return {"anywhere": (None, MAX_DISTANCE_ANYWHERE),
            "dao": (dao_filter(case["space_id"]), MAX_DISTANCE_ANYWHERE),
            "proposal": ({"proposal_id": case["proposal_id"]}, MAX_DISTANCE_ONE_PROPOSAL)}


def score_case(case: dict, chunks: list[dict], cutoff: float) -> dict:
    """Where the expected passage landed in one search result."""
    rank = next((i + 1 for i, c in enumerate(chunks)
                 if c["metadata"].get("content_hash") == case["expected_hash"] or c["id"] == case["expected_chunk"]), None)
    distance = chunks[rank - 1]["distance"] if rank else None
    top5 = chunks[:5]
    return {"rank": rank, "distance": round(distance, 3) if distance is not None else None,
            "within_cutoff": distance is not None and distance <= cutoff,
            "right_proposal_at_5": (sum(c["metadata"].get("proposal_id") == case["proposal_id"] for c in top5) / len(top5)
                                    if top5 else 0.0),
            "top1_distance": round(chunks[0]["distance"], 3) if chunks else None}


def summarise(rows: list[dict]) -> dict:
    """The scores of one scope over all cases."""
    n = len(rows)
    out = {"cases": n}
    for k in KS:
        out[f"found@{k}"] = round(100 * sum(1 for r in rows if r["rank"] and r["rank"] <= k) / n, 1)
    out["mrr@8"] = round(sum(1 / r["rank"] for r in rows if r["rank"] and r["rank"] <= 8) / n, 3)
    out["delivered@5"] = round(100 * sum(1 for r in rows if r["rank"] and r["rank"] <= 5 and r["within_cutoff"]) / n, 1)
    out["right_proposal@5"] = round(100 * sum(r["right_proposal_at_5"] for r in rows) / n, 1)
    out[f"not_in_top_{DEPTH}"] = sum(1 for r in rows if not r["rank"])
    return out


def evaluate(cases: list[dict], search=current_search, dao_filter=None) -> dict:
    """
    Run every case in every scope. Returns {"summary": {scope: scores}, "by_source_type": ..., "cases": [...]}.

    Parameters:
        cases      - load_cases().
        search     - search(question, where, n) -> chunks nearest first.
        dao_filter - space_id -> the Chroma filter for one DAO. Default: the `space_id` key every
                     chunk carries since metadata schema 2.
    """
    dao_filter = dao_filter or (lambda space_id: {"space_id": space_id})
    results = []
    for case in cases:
        per_scope = {}
        for name, (where, cutoff) in scopes(case, dao_filter).items():
            per_scope[name] = score_case(case, search(case["question"], where, DEPTH), cutoff)
        results.append({**case, "scopes": per_scope})
    names = list(results[0]["scopes"])
    summary = {name: summarise([r["scopes"][name] for r in results]) for name in names}
    by_type = {kind: {name: summarise([r["scopes"][name] for r in results if r["source_type"] == kind]) for name in names}
               for kind in sorted({r["source_type"] for r in results})}
    return {"summary": summary, "by_source_type": by_type, "cases": results}


def print_report(report: dict, misses: bool = False) -> None:
    columns = ["cases", "found@5", "found@8", "mrr@8", "delivered@5", "right_proposal@5", f"not_in_top_{DEPTH}"]

    def table(title, block):
        print(f"\n{title}")
        print(f"  {'scope':<10}" + "".join(f"{c:>18}" for c in columns))
        for scope, scores in block.items():
            print(f"  {scope:<10}" + "".join(f"{scores[c]:>18}" for c in columns))
    table("ALL QUESTIONS", report["summary"])
    for kind, block in report["by_source_type"].items():
        table(f"ONLY {kind}", block)
    if misses:
        print("\nNOT IN THE TOP 5 (anywhere):")
        for r in report["cases"]:
            s = r["scopes"]["anywhere"]
            if not s["rank"] or s["rank"] > 5:
                print(f"  {r['id']} rank={s['rank']} dist={s['distance']} top1={s['top1_distance']} [{r['source_type']}] {r['question']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score retrieval on eval/retrieval_set.json (no LLM calls)")
    parser.add_argument("--misses", action="store_true", help="List the questions whose passage was not in the top 5")
    parser.add_argument("--no-rerank", action="store_true", help="Score the merged vector + keyword order, without the reranker")
    args = parser.parse_args()

    report = evaluate(load_cases(), search_without_reranker if args.no_rerank else current_search)
    report["run_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    report["search"] = ("vector (context line, query instruction) + BM25 keyword search, merged by rank"
                        + ("" if args.no_rerank else ", then reranked (vector/reranker.py)"))
    print_report(report, misses=args.misses)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"retrieval_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {out}")
