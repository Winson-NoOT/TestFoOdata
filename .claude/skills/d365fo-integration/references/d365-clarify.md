# Clarify Intent Before Acting

**At any point where the user's intent is unclear — before writing queries, scripts, or running setup flows — stop and ask.** Do not guess and produce a long answer that may be entirely wrong.

---

## When to clarify

Clarify whenever the request is ambiguous. Common situations:

- "Help me with D365FO" or "I need to get data" — unclear what entity, operation, or environment
- Entity name could match multiple things
- "Write me a script" — unclear what it should do
- Unclear whether the user wants a fix, a workaround, or just an explanation
- Could mean either a read (GET) or a write (POST/PATCH/DELETE)

## How to clarify

Ask one focused question at a time. **Always provide concrete options — never ask open-ended questions.** Use `ASK_TOOL` or list labelled choices (A / B / C).

Example intents to offer when the overall goal is unclear:

- A) **Query / read data** — fetch records via OData GET
- B) **Write / create / update / delete data** — OData POST, PATCH, or DELETE
- C) **Set up a new environment or Entra app** — onboard credentials, config
- D) **Optimize or debug an existing query** — performance, errors, wrong results
- E) **Build a reusable helper script** — something they'll run repeatedly
- F) **Explore available entities or fields** — discover what's in the environment

Trim to only the options that are relevant from context — do not list all six if three are obviously irrelevant.

## When NOT to clarify

Skip if the user's intent is unambiguous — e.g. they paste a broken query and say "fix this", or name a specific entity and say "give me all records where X". Proceed directly.

---

## When to load this file

Load when intent is ambiguous at the start of a task, before deciding which reference files to read next. Once intent is confirmed, you do not need to re-load this file.
