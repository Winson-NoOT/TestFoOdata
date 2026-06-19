# Environment Gate

**Before writing any OData query, script, or API call — no exceptions — confirm the target environment is known and a live token can be fetched.**

A query written without a real environment to test against is guesswork. This gate is non-negotiable.

---

## Gate checklist

Ask yourself — do I already know all of the following from this conversation?

1. Which D365FO environment is being targeted? (friendly name = bws project name, e.g. `Shaefer dev3`)
2. Can I fetch a live token for it right now — i.e. has `get_token.py` been run successfully with no auth errors this session?

If **any** answer is NO → run the onboarding flow below before writing a single line of query.

---

## Onboarding flow (when gate fails)

Credentials come entirely from **Bitwarden Secrets Manager** via the `bws` CLI
(see `references/d365-bws-resolve.md`). There is no config file to load or
create. Each bws project is one environment.

### Step 0 — Verify bws is usable

Silently confirm the CLI and token are present:

```bash
bws --version >/dev/null 2>&1 && [ -n "$BWS_ACCESS_TOKEN" ] && echo OK || echo MISSING
```

- `OK` → continue to Step 1.
- `MISSING` → tell the user that `bws` and/or `BWS_ACCESS_TOKEN` are required
  to reach D365FO credentials, then **STOP**. There is no other source.

### Step 1 — Determine the environment

```bash
python3 << 'EOF'
import glob, os, sys
_p = glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts") + \
     [os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
      os.path.expanduser("~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts")]
sys.path.insert(0, next(p for p in _p if os.path.isdir(p)))
from bws_creds import list_environments, get_last_env
print("last:", get_last_env())
for e in list_environments():
    print("-", e["name"])
EOF
```

- **User already named an environment** (or one was established earlier this
  session) → use it; skip to Step 2.
- **Exactly one environment** → use it; skip to Step 2.
- **Multiple and none chosen** → show the names with `ASK_TOOL` and let the
  user pick. **STOP. Wait for the selection before doing anything else.**

### Step 2 — Fetch a live token

Run the token fetch for the chosen environment in one bash call:

```python
import glob, os, sys
_p = glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts") + \
     [os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
      os.path.expanduser("~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts")]
sys.path.insert(0, next(p for p in _p if os.path.isdir(p)))
from get_token import get_token
t = get_token("ENV_NAME")        # omit the arg to use last-used / sole env
print(t["appName"], t["baseUrl"])
```

- **Token succeeds** → proceed to the task immediately. No need to narrate this step.
- **`resolve_creds` raised a mapping error** (secret naming was unexpected) →
  read `references/d365-bws-resolve.md` and inspect the project's secrets
  (`bws_creds.py secrets "<env>"`), map each field, asking the user if unclear,
  then retry.
- **Auth error from Azure** (bad secret / tenant / URL) → tell the user which
  credential looks wrong, inspect the secrets, and fix before any query.

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
