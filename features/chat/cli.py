# features/chat/cli.py
"""
features/chat/cli.py — Chat with the project in the terminal.

WHAT THIS FILE DOES
    A simple question/answer loop over the SAME pipeline as POST /chat
    (features/chat/service.py run_chat): the agent looks things up in the database
    (shown to you as it happens) -> the writer answers from them.
    No server needed. Type a question, get the answer, and look at what it was
    based on whenever you want.

RUN
    python -m features.chat.cli

COMMANDS (type them instead of a question)
    /find <words>     search proposal titles, e.g.  /find defillama
    /use <n or id>    talk about ONE proposal: a number from /find, or a 0x... id
    /all              talk about all proposals again (no proposal selected)
    /sources          the passages the last answer was built from
    /lookups          every database lookup the agent made for the last answer, with its result
    /help             this list
    /quit             leave (or Ctrl+C)

    Selecting a proposal with /use is the same as sending proposal_id to the API:
    the search only looks inside that proposal, which gives much better answers
    for questions like "why did people support this?".

WHERE IT SITS
    you --> THIS FILE --> features/chat/service.py run_chat --> agent / tools / prompt / llm
    /find reads proposal titles straight from SQLite (db/schema.py).
"""

import json
import sys
import textwrap

from db.schema import get_connection
from features.chat.service import lookups, run_chat

if sys.platform == "win32":          # print non-ASCII answers on the Windows console
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HELP = __doc__.split("COMMANDS (type them instead of a question)")[1].split("WHERE IT SITS")[0].rstrip()
WIDTH = 100
AUTOMATIC_MARK = "   [automatic: the model skipped the search, so we ran it]"


def find_proposals(words: str, limit: int = 10) -> list[dict]:
    """
    Proposals whose title contains every word, newest first: [{id, title, dao, state}].

    Parameters (where they come from):
        words - what you typed after /find.
        limit - how many to show (10).
    """
    terms = [w for w in words.lower().split() if w]
    sql = ("SELECT p.id, p.title, p.state, s.name AS dao FROM proposals p "
           "LEFT JOIN spaces s ON s.id = p.space_id")
    if terms:
        sql += " WHERE " + " AND ".join("lower(p.title) LIKE ?" for _ in terms)
    sql += " ORDER BY p.created_ts DESC LIMIT ?"
    conn = get_connection()
    try:
        rows = conn.execute(sql, [f"%{t}%" for t in terms] + [limit]).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def proposal_title(proposal_id: str) -> str | None:
    """
    The title of a proposal id, or None if it is not in our data.

    Parameter (where it comes from): the id after /use.
    """
    conn = get_connection()
    try:
        row = conn.execute("SELECT title FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    finally:
        conn.close()
    return row["title"] if row else None


def _wrap(text: str, indent: str = "  ") -> str:
    lines = []
    for paragraph in (text or "").splitlines():
        lines.append(textwrap.fill(paragraph, WIDTH, initial_indent=indent, subsequent_indent=indent)
                     if paragraph.strip() else "")
    return "\n".join(lines)


def show_sources(last: dict | None):
    """Print the passages behind the last answer (the /sources command)."""
    if not last or not last.get("chunks"):
        print("  No answer yet, or it had no sources.")
        return
    for i, c in enumerate(last["chunks"], 1):
        meta, sql = c["metadata"], c.get("sql") or {}
        who = f" by {meta['author']}" if meta.get("author") else ""
        wallet = f" | wallet link: {sql['link_confidence']}" if sql.get("link_confidence") else ""
        vote = f" | voted {sql['voted']}" if sql.get("voted") else ""
        print(f"  [Source {i}] {meta.get('source_type')}{who}{wallet}{vote} | distance {c['distance']:.2f}")
        print(_wrap(c["document"][:400] + ("..." if len(c["document"]) > 400 else ""), "      "))


def _arguments(arguments: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in arguments.items())


def show_lookups(last: dict | None):
    """Print every lookup the agent made for the last answer (the /lookups command)."""
    if not last or not last.get("evidence"):
        print("  No database lookup was needed for the last answer.")
        return
    for entry in lookups(last["evidence"]):
        text = json.dumps(entry["result"], ensure_ascii=False, default=str)
        print(f"  {entry['tool']}({_arguments(entry['arguments'])})" + AUTOMATIC_MARK * bool(entry.get("automatic")))
        print(_wrap(text[:600] + ("..." if len(text) > 600 else ""), "      "))


def show_lookup_started(entry: dict):
    """Print one lookup as soon as it ran (passed to run_chat as on_lookup)."""
    print(f"  ... looked up {entry['tool']}({_arguments(entry['arguments'])[:90]})"
          + AUTOMATIC_MARK * bool(entry.get("automatic")), flush=True)


def main():
    """The question/answer loop."""
    print("DAO governance chat. Ask a question, or type /help. (The first answer takes a few seconds.)")
    scope, scope_title, found, last = None, None, [], None
    while True:
        try:
            line = input(f"\n[{scope_title[:40] + '...' if scope_title else 'all proposals'}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        command, _, arg = line.partition(" ")

        if command in ("/quit", "/exit"):
            return
        if command == "/help":
            print(HELP)
        elif command == "/find":
            found = find_proposals(arg)
            if not found:
                print("  No proposal title contains those words.")
            for n, p in enumerate(found, 1):
                print(f"  {n:>2}. [{p['dao']}, {p['state']}] {p['title'][:80]}")
            if found:
                print("  Type /use <number> to talk about one of them.")
        elif command == "/use":
            arg = arg.strip()
            if arg.isdigit() and 1 <= int(arg) <= len(found):
                scope, scope_title = found[int(arg) - 1]["id"], found[int(arg) - 1]["title"]
            elif arg.startswith("0x") and proposal_title(arg):
                scope, scope_title = arg, proposal_title(arg)
            else:
                print("  Use a number from /find, or a proposal id (0x...).")
                continue
            print(f"  Now talking about: {scope_title}")
        elif command == "/all":
            scope, scope_title = None, None
            print("  Now talking about all proposals.")
        elif command == "/sources":
            show_sources(last)
        elif command in ("/lookups", "/facts"):
            show_lookups(last)
        elif command.startswith("/"):
            print("  Unknown command. Type /help.")
        else:
            try:
                last = run_chat(line, proposal_id=scope, on_lookup=show_lookup_started)
            except Exception as e:                  # every LLM provider failed, etc.
                print(f"  Could not answer: {e}")
                continue
            print()
            print(_wrap(last["answer"]))
            print(f"\n  ({last['provider']} | {len(last['evidence'])} lookups, {len(last['chunks'])} sources"
                  " - /lookups and /sources to see them)")


if __name__ == "__main__":
    main()


# ── Where control goes next ───────────────────────────────────────────────────
# Each question goes to features/chat/service.py run_chat (the same pipeline as
# POST /chat), so what you see here is what the API would answer.
# If an answer looks wrong: /lookups shows what the agent asked the database, /sources what
# the search found; that usually tells you whether the lookups, the data or the writer's
# prompt is the problem.
