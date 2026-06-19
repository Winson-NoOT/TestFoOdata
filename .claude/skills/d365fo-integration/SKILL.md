---
name: d365fo-integration
description: Use when the user mentions D365FO, OData, Dynamics 365 Finance & Operations, Entra app, client credentials, querying or writing D365FO data, or setting up D365FO environment access — even if they don't say "OData" explicitly. Also trigger for setup, config, or any API call to a Dynamics 365 environment.
---

# D365FO Integration

Connect to and interact with Dynamics 365 Finance & Operations via OData and Azure Entra app authentication.

---

## Session init — MANDATORY, never skip

> ⛔ **This step is not optional.** Run it before anything else — before reading references, before writing queries, before answering the user. No exceptions.

```bash
python3 - << 'PYEOF'
import os, shutil
# Detect environment and return the right interactive-question tool name.
# Inlined so this works regardless of where the skill is installed.
if os.environ.get('CLAUDE_CODE') or shutil.which('claude'):
    print('AskUserQuestion')
elif os.path.isdir('/mnt/user-data'):
    print('ask_user_input_v0')
else:
    print('agent_choice')
PYEOF
```

Output is the picker tool to use throughout this session. Store it mentally as `ASK_TOOL`. Every reference file that says "use `ASK_TOOL`" means the value from this output.

| Output | Environment | What to do |
|---|---|---|
| `AskUserQuestion` | Claude Code (terminal / CLI) | Call the `AskUserQuestion` tool |
| `ask_user_input_v0` | Claude.ai web / mobile | Call the `ask_user_input_v0` tool |
| `agent_choice` | Unknown / third-party agent | Use whatever interactive question tool your environment provides; if none, present numbered options as plain text and ask the user to reply with their choice number |

---

## Four rules — always apply

1. **Unclear intent?** Read `references/d365-clarify.md` before doing anything.
2. **Before any query or API call** — run the environment gate: read `references/d365-env-gate.md`.
   - **"Give me a query" = test it first.** Default is always: execute the query, verify it works, then present the confirmed working result. The only exception is when the user **explicitly** says they do not need it tested (e.g. "just give me the query, I'll run it myself"). If tested, you **must** state in your response that the query was tested and confirmed working.
3. **Config file missing?** Read `references/d365-config-create.md`. **Env not in existing config?** Read `references/d365-entra-app-setup.md` (Add flow).
4. **No cross-session pattern trust.** Any query pattern confirmed in a previous session — including `$expand` paths, navigation property names, entity variants, company data areas, or `$filter` shapes — is **not** assumed valid in the current session. "Not assumed valid" means **you must re-test it this session before presenting it as an answer.** Do not present a remembered pattern as correct — execute it, check the response, then show the result.

---

## Reference index

| When | Read |
|---|---|
| Intent is ambiguous | `references/d365-clarify.md` |
| Starting any query/script task — env check | `references/d365-env-gate.md` |
| Config file missing / first-time setup | `references/d365-config-create.md` |
| Manage Entra apps — add, edit, remove, list | `references/d365-entra-app-setup.md` |
| App entry has `credentialSource: "bitwarden"` | `references/d365-bw-resolve.md` |
| OData query — single entity (read or write) | `references/d365-odata.md` + `references/d365-scripts.md` |
| OData query — join / related entities | above + `references/d365-odata-efficiency.md` |
| Performance, `$batch`, `$select`, token caching | `references/d365-odata-efficiency.md` |
| Client-side join (user confirmed `$batch`) | `references/d365-odata-join.md` |
| Helper scripts — `get_token`, `check_nav`, `init` | `references/d365-scripts.md` |
| Entity field lookup, enums, actions — `get_metadata.py` | `references/d365-scripts.md` (get_metadata section) |
| `get_token.py` unavailable — manual token fetch | `references/d365-token-manual.md` |

**Metadata lookup:** if the user asks about entity fields, field names, enum values, or available actions — use `get_metadata.py` (see `d365-scripts.md`) before fetching raw `$metadata` XML. Run `ensure_metadata()` or CLI `--fields / --enum / --action` flags instead.

**Join detection:** if the request mentions two entity types, header+lines, "join", "expand", or fields from multiple tables — treat as a join query and load `d365-odata.md` + `d365-odata-efficiency.md` + `d365-scripts.md`. Always discover entity variants first (Step 4a in efficiency.md) before attempting `$expand` or `$batch`.
