   # eXPlEARNING/tool_calling_basics.py
"""
eXPlEARNING/tool_calling_basics.py — The SMALLEST working example of LLM tool calling.

WHAT THIS FILE DOES
    Shows, in about 40 lines of real code, what "the LLM calls a function" means.
    The big idea: THE LLM NEVER RUNS ANYTHING. It only writes a request such as
    "please call get_voters with proposal='OAT Elections'". YOUR code runs the
    function and sends the result back. Then the LLM writes the final answer.

    The conversation has 4 messages:
        1. user       "How many people voted on OAT Elections?"
        2. assistant  (no text!) tool_calls = [get_voters({"proposal": "OAT Elections"})]
        3. tool       "2226"            <- YOU ran get_voters and send this back
        4. assistant  "2,226 people voted on OAT Elections."   <- the final answer
    The program makes TWO calls to the LLM: one to get message 2, one to get message 4.

RUN
    .venv\\Scripts\\python.exe -m eXPlEARNING.tool_calling_basics
    Needs GROQ_API_KEY in .env (the same key the project uses).

WHERE IT SITS
    Standalone. It imports nothing from the project, so you can read it top to bottom.
    The real version, with 7 tools and SQLite, is eXPlEARNING/agent.py.
"""

import json
import os

from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq(api_key=os.environ["GROQ_API_KEY"])
MODEL = "openai/gpt-oss-120b"


# ── STEP 1: a normal Python function. The LLM knows nothing about it yet ──────

VOTERS = {"OAT Elections": 2226, "Season 2: Cycle 8: DefiLlama": 14194}     # stand-in for a database


def get_voters(proposal: str) -> int | str:
    """Number of voters on a proposal.

    Parameter (where it comes from): `proposal` is chosen BY THE LLM, as text,
    inside its tool call (message 2 above). We never type it ourselves.
    """
    return VOTERS.get(proposal, "unknown proposal")


# ── STEP 2: a DESCRIPTION of the function, written for the LLM to read ────────
# This is all the model ever sees of get_voters: a name, a sentence, and which
# arguments exist. If the description is vague, the model calls the wrong tool.

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_voters",
        "description": "Number of people who voted on a proposal. Use for any question about turnout.",
        "parameters": {                                   # a JSON Schema: the shape of the arguments
            "type": "object",
            "properties": {"proposal": {"type": "string", "description": "The proposal title."}},
            "required": ["proposal"],
        },
    },
}]


# ── STEP 3: the two LLM calls ─────────────────────────────────────────────────

messages = [{"role": "user", "content": "How many people voted on OAT Elections?"}]
print("MESSAGE 1 (we send):", messages[0])

# --- LLM call 1: we send the question AND the tool descriptions ---
reply = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS).choices[0].message
call = reply.tool_calls[0]                                # the model asked for a function; it did NOT answer
print("\nMESSAGE 2 (the LLM answers with a REQUEST):")
print("   text       :", repr(reply.content))
print("   wants      :", call.function.name, call.function.arguments)      # arguments is a JSON *string*

# --- we run the function ourselves, with the arguments the model chose ---
arguments = json.loads(call.function.arguments)           # '{"proposal": "OAT Elections"}' -> a dict
result = get_voters(**arguments)                          # <- THE ONLY PLACE THE FUNCTION RUNS
print("\nWE RUN get_voters(**", arguments, ") =", result)

# --- LLM call 2: we send everything so far PLUS the result ---
messages.append({"role": "assistant", "content": reply.content,
                 "tool_calls": [{"id": call.id, "type": "function",
                                 "function": {"name": call.function.name, "arguments": call.function.arguments}}]})
messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})
print("\nMESSAGE 3 (we send the result back):", messages[-1])

final = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS).choices[0].message
print("\nMESSAGE 4 (the final answer):", final.content)


# ── Where control goes next ───────────────────────────────────────────────────
# Read eXPlEARNING/agent.py next. It is this same file with three changes:
#   1. seven tools that read SQLite instead of one that reads a dict
#   2. a LOOP: the model may ask for several tools, one after another, before it answers
#   3. a fallback to Gemini if Groq fails
# If the model's first reply has no tool_calls (reply.tool_calls is None), it decided
#   to answer directly; here that would make line `call = reply.tool_calls[0]` crash.
#   agent.py checks `if not msg.tool_calls` first, which is the loop's exit.
