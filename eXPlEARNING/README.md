# eXPlEARNING — experiments and learning, away from the project

Try ideas here (new techniques, comparisons, prototypes) **without touching the project**.

Rules:
- Files here may `import` project code (config, db, features, vector ...) but never edit it.
- Nothing in the project imports from this folder.
- Run from the project root: `python -m eXPlEARNING.<file>`
- When an experiment proves itself (measured against the golden eval), we move it into the
  project deliberately.

| File | What it shows |
|---|---|
| [tool_calling_basics.py](tool_calling_basics.py) | Tool calling in ~40 lines: the LLM *requests* a function, our code runs it, the result goes back |

Graduated into the project: the tool-calling agent (it started here as `agent.py`) is now
`features/chat/agent.py` + `features/chat/tools.py`.
