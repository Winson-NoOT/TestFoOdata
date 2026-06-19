# Environment Gate

**Before writing any OData query, script, or API call — no exceptions — confirm the target environment is known and a live token can be fetched.**

A query written without a real environment to test against is guesswork. This gate is non-negotiable.

---

## Gate checklist

Ask yourself — do I already know all of the following from this conversation?

1. Which D365FO environment is being targeted? (friendly name, e.g. `Schaefer-DEV`)
2. Can I fetch a live token for it right now — i.e. has `get_token.py` been run successfully with no auth errors this session?

If **any** answer is NO → run the onboarding flow below before writing a single line of query.

---

## Onboarding flow (when gate fails)

> **Widget vs picker:** This flow uses the credential widget because the environment is unknown or new. Once an environment is confirmed in `config.json`, subsequent tasks use a simple app picker in `d365-odata.md` Step 1 instead — no need to re-run this flow.

### Step 0 — Auto-load config from disk

**Do not ask the user anything yet.** Try these two sources silently, in order:

**Attempt 1 — user's machine via Windows-MCP:**
Use the `Windows-MCP:FileSystem` tool with `mode=read` and `path=~\.d365fo-integration\config.json`.
If the file is found, write its content to the sandbox so scripts can use it:
```bash
mkdir -p ~/.d365fo-integration
cat > ~/.d365fo-integration/config.json << 'JSONEOF'
<PASTE CONTENT FROM WINDOWS-MCP READ HERE>
JSONEOF
```

**Attempt 2 — sandbox cache** (fallback for Cowork / Claude Code sessions where Windows-MCP is unavailable):
```bash
cat ~/.d365fo-integration/config.json 2>/dev/null
```

> **Note:** If Windows-MCP is not connected, fall through to Attempt 2 silently. Do not surface an error to the user.

**If config is found (either attempt):**
1. Parse `lastUsedEntraApp` from the config
2. **Check credential source** — inspect the app entry:
   ```bash
   python3 -c "
   import json, os
   with open(os.path.expanduser('~/.d365fo-integration/config.json')) as f:
       cfg = json.load(f)
   app = cfg.get('lastUsedEntraApp','')
   entry = cfg['entraApps'].get(app, {})
   print(entry.get('credentialSource', 'manual'))
   "
   ```
   - If output is `bitwarden` → **read `references/d365-bw-resolve.md`** and follow the resolution flow (Steps 1–5) to resolve credentials before continuing. After successful resolution the token is already fetched — skip step 3 below and proceed to task.
   - If output is `manual` (or blank) → continue to step 3 as normal.
3. Attempt token fetch — run this Python block in the same bash call:
   ```python
   import glob, os, sys
   _p = glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts") +         [os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
         os.path.expanduser("~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts")]
   sys.path.insert(0, next(p for p in _p if os.path.isdir(p)))
   from get_token import get_token
   t = get_token()          # uses lastUsedEntraApp from config
   print(t["appName"], t["baseUrl"])
   ```
3. If token succeeds → proceed to task immediately. No need to inform the user about this step — just continue.
4. If token fails → tell the user which credential looks wrong, then show the credential widget as fallback (Step 1)

**If config is not found anywhere:**
→ Ask the user using `ASK_TOOL`:

**"No config found. Do you have a saved config.json from a previous session?"**
- **A) Yes — paste the JSON** → user pastes raw JSON; write it to `~/.d365fo-integration/config.json`, attempt token fetch, then proceed to task.
- **B) No — set up a new environment** → read `references/d365-config-create.md` and follow from **Step 0** (credential source selection — manual entry or Bitwarden CLI).

**STOP. Wait for user selection before doing anything else.**

If user selects **A** and pastes the JSON:
1. Write the pasted content verbatim to `~/.d365fo-integration/config.json`
2. Fetch token using `lastUsedEntraApp` from the pasted JSON
3. If token succeeds → proceed to task
4. If token fails → tell user which credential looks wrong and show the widget as fallback

> **Why route to `d365-config-create.md` for option B?** It asks whether credentials are stored manually or in Bitwarden before collecting any details. Going straight to the widget skips that choice and only supports manual entry.

---

### Step 1 — Credential widget (only for manual entry, config already exists but env is missing)

This step applies when the **config file exists** but the target app name is not found in it. Use `ASK_TOOL` to present credential source options first:

**"How do you want to store credentials for this environment?"**
- **A) Manual entry** — fill in Tenant ID, Client ID, Secret directly
- **B) Bitwarden CLI** — read `references/d365-config-create.md` Step 1b for the Bitwarden mapping flow

If **A**: **Do not ask for credentials via plain chat text.** Render the interactive credential form instead. **Read `assets/env-setup-widget.html`** and pass its content verbatim to `visualize:show_widget`. Wait for the submit (arrives as a chat message starting with `D365FO env details:`).

### After collecting env details (manual entry only)

1. Config exists but app name not found → read `references/d365-entra-app-setup.md` and use the Add flow to append the new entry.
2. Confirm a live token fetches successfully:
   ```python
   import glob, os, sys
   _p = glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts") +         [os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
         os.path.expanduser("~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts")]
   sys.path.insert(0, next(p for p in _p if os.path.isdir(p)))
   from get_token import get_token
   t = get_token("APP_NAME")   # replace APP_NAME with the value from config/widget
   print(t["appName"], t["baseUrl"])
   ```
3. If token fetch fails — diagnose and fix before writing any query. See `references/d365-token-manual.md` if `get_token.py` is unavailable.
4. Live token confirmed → proceed to the task.

---

## Query execution policy

| Request type | What to do |
|---|---|
| User asks to **draft / provide / show** a query (GET) | **Run it. Confirm it works. Present only the tested, working result.** State explicitly in your response: "Tested and confirmed working." Never present an untested query as the answer. The only exception: user **explicitly** says "no need to test" or "just give me the query, I'll run it" — in that case comply but label the output as **⚠️ Untested — not verified against live environment.** |
| User asks to **write / create / update / delete** data (POST/PATCH/DELETE) | Draft first, then **stop and ask** for confirmation before executing. Use `ASK_TOOL`: **A) Run now** / **B) Show query only** / **C) Cancel**. Writes are irreversible. |
| Intent is **unclear** | Read `references/d365-clarify.md` and ask one focused question before doing anything. |

If the user explicitly says "just give me the query, I'll run it myself" — comply, but label the output clearly as **untested**.

---

## When to load this file

Load at the start of any task that will involve writing or running OData queries, scripts, or API calls — i.e. any time the environment gate check is needed. You only need to load it once per session unless auth fails and you need to re-onboard.
