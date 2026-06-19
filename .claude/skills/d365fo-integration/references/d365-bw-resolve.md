# Bitwarden CLI Credential Resolution

Use this flow **only** when an `entraApps` entry has `"credentialSource": "bitwarden"`.

This resolves the Bitwarden vault references into actual credential values at runtime so `get_token.py` can use them. No secrets are written to disk — they are held in memory only for the duration of the token fetch.

---

## Step 0 — Detect where `bw` is available

`bw` runs on the **user's machine**, not in the Claude sandbox. Determine which execution path to use:

**Check sandbox (bash):**
```bash
bw --version 2>/dev/null || echo "NOT_FOUND"
```

**Check user's machine (Windows-MCP), if connected:**
```powershell
bw --version
```

| Result | Path to use |
|---|---|
| Found in bash | Use **bash path** (Steps 1–5 as-is) |
| Found via Windows-MCP | Use **Windows-MCP path** (Steps 1W–4W below) |
| Neither found | Tell user to install `bw` from https://bitwarden.com/help/cli/ and ensure it is on PATH. **STOP.** |

> **In practice on Windows:** `bw` is almost always on the user's machine, not in the Claude sandbox. Default to Windows-MCP path if the connector is available.

---

## Windows-MCP Path (Steps 1W–4W)

### Step 1W — Check vault status via Windows-MCP

```powershell
bw status
```

Look at the `"status"` field:
- `"unlocked"` → skip to Step 1W-sync
- `"locked"` → need to unlock (continue below)
- `"unauthenticated"` → tell the user to run `bw login` in their terminal first, then retry

> **Known bug (Bitwarden CLI 2024.6+):** If `bw status` shows `"locked"` immediately after `bw unlock`, or if `bw list items --session KEY` still prompts for master password, the local `data.json` is corrupt. Fix: run `Remove-Item "$env:APPDATA\Bitwarden CLI\data.json"` via Windows-MCP, then have the user run `bw login` again in their terminal.

**To unlock:** Use `ASK_TOOL`:
> "Your Bitwarden vault is locked. Please run `bw unlock` in your terminal and paste the session key here (the value after `$env:BW_SESSION=`)."

Wait for the session key. Store it as `BW_SESSION`.

### Step 1W-sync — Sync vault before any item lookups

Always sync after unlocking (or at the start of a new session) to ensure the latest items are present:

```powershell
bw sync --session $s
```

> **Why this matters:** Items added or updated in the Bitwarden web vault since the last sync won't appear in `bw list items` results until a sync is performed. If expected items are missing from a folder listing, sync is always the first fix to try.

### Step 2W — Read BW mapping from config

```python
import json, os
with open(os.path.expanduser("~/.d365fo-integration/config.json")) as f:
    cfg = json.load(f)
app_name = cfg["lastUsedEntraApp"]
bw_map = cfg["entraApps"][app_name]["bw"]
# bw_map keys: tenantId, clientId, clientSecret — each has "item" and "field"
```

### Step 3W — Fetch credentials via Windows-MCP PowerShell

Replace placeholders with values from `bw_map`. Use the session key from Step 1W-sync.

> **Item name vs item ID:** The `bw_map` `"item"` field can be either a human-readable name (e.g. `"barcode app tenant id"`) **or** a UUID item ID (e.g. `"53a73450-6ad0-467d-b25d-b4580096a191"`). `bw get item` accepts both. **Prefer IDs** when multiple items share the same name across folders — `bw get item <name>` fails with "More than one result was found" in that case. See the BW item picker flow in `d365-entra-app-setup.md` for how to collect IDs.

```powershell
$s = "BW_SESSION_KEY_HERE"

function Get-BwField($itemRef, $fieldName) {
    $raw = bw get item $itemRef --session $s | ConvertFrom-Json
    switch ($fieldName) {
        "password" { return $raw.login.password }
        "username" { return $raw.login.username }
        "notes"    { return $raw.notes }
        default    { return ($raw.fields | Where-Object { $_.name -eq $fieldName }).value }
    }
}

$TENANT_ID     = Get-BwField "ITEM_FOR_TENANT"  "FIELD_FOR_TENANT"
$CLIENT_ID     = Get-BwField "ITEM_FOR_CLIENT"  "FIELD_FOR_CLIENT"
$CLIENT_SECRET = Get-BwField "ITEM_FOR_SECRET"  "FIELD_FOR_SECRET"

echo "Tenant: $(if ($TENANT_ID) { $TENANT_ID.Substring(0,[Math]::Min(8,$TENANT_ID.Length)) + '...' } else { 'EMPTY' })"
echo "Client: $(if ($CLIENT_ID) { $CLIENT_ID.Substring(0,[Math]::Min(8,$CLIENT_ID.Length)) + '...' } else { 'EMPTY' })"
echo "Secret fetched: $(if ($CLIENT_SECRET) { 'YES' } else { 'NO' })"
```

If any value is empty or null:
- Tell the user which credential failed
- Ask them to verify the item name/ID and field in Bitwarden (names are **case-sensitive**)
- If using names and getting "More than one result was found" → switch to item IDs (use `bw list items --folderid <id>` to find the correct UUID)
- Re-run after correction

**Session expiry:** If the command prompts for master password despite a valid session key, the session has expired. Ask the user to run `bw unlock` again and provide a fresh key.

### Step 4W — Patch config, call get_token, then clean up

Pass resolved values in-memory to `get_token.py` in the Claude sandbox:

```python
import json, os, sys, glob

cfg_path = os.path.expanduser("~/.d365fo-integration/config.json")
with open(cfg_path) as f:
    cfg = json.load(f)

app_name = cfg["lastUsedEntraApp"]
entry = cfg["entraApps"][app_name]

# Inject resolved credentials — sandbox session only, never persisted
entry["tenantId"]     = "TENANT_ID_VALUE"    # from Step 3W output
entry["clientId"]     = "CLIENT_ID_VALUE"
entry["clientSecret"] = "CLIENT_SECRET_VALUE"

with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)

_p = (glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts") +
      [os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
       "/mnt/skills/user/d365fo-integration/scripts"])
sys.path.insert(0, next(p for p in _p if os.path.isdir(p)))

from get_token import get_token
t = get_token(app_name)
print(t["appName"], t["baseUrl"])
```

> **⚠️ IMPORTANT — Clean up plaintext creds before syncing config back to user's machine.**
> After a successful token fetch, the sandbox config contains injected plaintext credentials. Before calling `Windows-MCP:FileSystem` to write config back, strip them:
>
> ```python
> import json, os
> cfg_path = os.path.expanduser("~/.d365fo-integration/config.json")
> with open(cfg_path) as f:
>     cfg = json.load(f)
> for app in cfg["entraApps"].values():
>     if app.get("credentialSource") == "bitwarden":
>         for key in ["tenantId", "clientId", "clientSecret"]:
>             app.pop(key, None)
> with open(cfg_path, "w") as f:
>     json.dump(cfg, f, indent=2)
> ```
>
> Only then write the cleaned config to `~\.d365fo-integration\config.json` on the user's machine.

---

## Bash Path (original — for Linux/macOS environments)

### Step 1 — Check vault lock status

```bash
bw status 2>/dev/null
```

- `"unlocked"` → skip to Step 3
- `"locked"` → ask user to run `bw unlock` and paste the session key
- `"unauthenticated"` → ask user to run `bw login` first

Use `ASK_TOOL` for unlock:
> "Your Bitwarden vault is locked. Please run `bw unlock` in your terminal and paste the session key here."

### Step 2 — Read BW mapping from config

```python
import json, os
with open(os.path.expanduser("~/.d365fo-integration/config.json")) as f:
    cfg = json.load(f)
app_name = cfg["lastUsedEntraApp"]
bw_map = cfg["entraApps"][app_name]["bw"]
```

### Step 3 — Fetch each credential

```bash
BW_SESSION="PASTE_SESSION_KEY_HERE"

bw_get_field() {
  local item_name="$1" field_name="$2"
  local raw
  raw=$(bw get item "$item_name" --session "$BW_SESSION" 2>/dev/null)
  case "$field_name" in
    password) echo "$raw" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['login']['password'])" ;;
    username) echo "$raw" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['login']['username'])" ;;
    notes)    echo "$raw" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('notes',''))" ;;
    *)        echo "$raw" | python3 -c "import json,sys; d=json.load(sys.stdin); fields={f['name']:f['value'] for f in d.get('fields',[])}; print(fields.get('$field_name','NOT_FOUND'))" ;;
  esac
}

TENANT_ID=$(bw_get_field "ITEM_FOR_TENANT"  "FIELD_FOR_TENANT")
CLIENT_ID=$(bw_get_field "ITEM_FOR_CLIENT"  "FIELD_FOR_CLIENT")
CLIENT_SECRET=$(bw_get_field "ITEM_FOR_SECRET" "FIELD_FOR_SECRET")

echo "Tenant: ${TENANT_ID:0:8}..."
echo "Client: ${CLIENT_ID:0:8}..."
echo "Secret fetched: $([ -n "$CLIENT_SECRET" ] && echo YES || echo NO)"
```

### Step 4 — Call get_token with resolved credentials

Same as Step 4W above — patch config in-memory and call `get_token`.

---

## When to load this file

Load when:
- An entraApp entry has `"credentialSource": "bitwarden"` and credentials need to be resolved
- Env-gate encounters a BW entry and needs to fetch a token
- Step 3 of `d365-config-create.md` routes here for Bitwarden verification
