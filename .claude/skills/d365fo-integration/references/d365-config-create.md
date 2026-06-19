# Create Config File

Use this flow **only** when `~/.d365fo-integration/config.json` does not exist yet.

For adding or editing environments in an **existing** config → use `d365-entra-app-setup.md` instead.

---

## Step 0 — Choose credential source

Use `ASK_TOOL` to ask the user:

**"How do you want to store credentials for this D365FO environment?"**

- **A) Manual entry** — type Tenant ID, Client ID, and Client Secret directly into a form
- **B) Bitwarden CLI** — pull secrets from your Bitwarden vault at runtime (no secrets stored in config)

**STOP. Do not proceed until the user selects.**

- If **A** → proceed to **Step 1a** (manual entry widget)
- If **B** → proceed to **Step 1b** (Bitwarden mapping)

---

## Step 1a — Manual entry (collect credentials via interactive UI)

**Read `assets/env-setup-widget.html`** and pass its content verbatim to `visualize:show_widget`. The Client Secret field is masked (`type="password"`). All five fields are required.

Wait for the user to submit (arrives as a chat message starting with `D365FO env details:`). Verify all five fields are present. If any are missing, tell the user which ones are blank and show the widget again.

For multiple environments, after each successful submission use `ASK_TOOL`: **A) Add another environment** / **B) Done** — repeat until done.

---

## Step 1b — Bitwarden CLI mapping

> **No secrets are stored in config.json in this mode.** Only the Bitwarden item names and field references are saved. The actual credential values are fetched from the vault at runtime via `bw get item`.

### Step 1b-i — Try auto-discovery first (Windows-MCP)

If the Windows-MCP connector is available, attempt to list vault items directly so the user can pick — much better than asking them to type item names from memory.

**Check if bw is accessible via Windows-MCP:**
```powershell
bw --version
```

If accessible, check vault status:
```powershell
bw status
```

- If `"locked"` → use `ASK_TOOL`: *"Your Bitwarden vault is locked. Please run `bw unlock` in your terminal and paste the session key (the value after `$env:BW_SESSION=`)."* Wait for key.
- If `"unauthenticated"` → ask user to run `bw login` first, then retry.

**Known bug:** If `bw list items --session KEY` still prompts for master password despite a valid session key, the local `data.json` is corrupt. Fix it silently:
```powershell
Remove-Item "$env:APPDATA\Bitwarden CLI\data.json" -Force
```
Then ask user to run `bw login` again and provide a fresh session key.

Once unlocked, list all items:
```powershell
bw list items --session "SESSION_KEY_HERE" | ConvertFrom-Json | Select-Object id, name | Format-Table -AutoSize
```

Present the item list to the user and ask:
- Which item holds **Tenant ID**, and which field (`password` / `username` / `notes` / custom)?
- Which item holds **Client ID**, and which field?
- Which item holds **Client Secret**, and which field?

Also ask for:
- **App Name** — friendly label (e.g. `Schaefer-DEV`)
- **Base URL** — e.g. `https://schaefer-dev.operations.dynamics.com`

### Step 1b-ii — Manual fallback (no Windows-MCP or bw not found)

If auto-discovery isn't possible, collect the following via plain-text chat:

1. **App Name** — friendly label
2. **Base URL**
3. For **Tenant ID**: Bitwarden item name + field name
4. For **Client ID**: Bitwarden item name + field name
5. For **Client Secret**: Bitwarden item name + field name

**Field name conventions:**
- `password` — main Password field of a Login item
- `username` — Username field of a Login item
- `notes` — Notes field
- Any other string → custom field name (case-sensitive)

**Example mapping:**
```
App Name:      Schaefer-DEV
Base URL:      https://schaefer-dev.operations.dynamics.com
Tenant ID:     item="D365FO-Schaefer", field="notes"
Client ID:     item="D365FO-Schaefer", field="username"
Client Secret: item="D365FO-Schaefer", field="password"
```

Items can all be the same Bitwarden item (different fields) or completely separate items.

After collecting all five pieces of information, **skip to Step 2b** (Bitwarden config creation).

---

## Step 2a — Create config (manual entry)

First, locate `config_manager.py`. The skill's base directory is shown in your system prompt (look for `Base directory for this skill:`). In a Cowork/bash session the Windows path maps to a `/sessions/.../mnt/` mount — use `find` to get the exact path:

```bash
SCRIPT=$(find /sessions -name "config_manager.py" 2>/dev/null | grep d365fo | head -1)
echo "Script found at: $SCRIPT"
```

Then run `create` with the first environment's credentials:

```bash
python3 "$SCRIPT" \
  create \
  --app    "APP_NAME" \
  --tenant "TENANT_ID" \
  --client-id "CLIENT_ID" \
  --secret "CLIENT_SECRET" \
  --url    "BASE_URL"
```

If the user submitted more than one environment, run `add` for each additional one:

```bash
python3 "$SCRIPT" \
  add \
  --app    "APP_NAME_2" \
  --tenant "TENANT_ID_2" \
  --client-id "CLIENT_ID_2" \
  --secret "CLIENT_SECRET_2" \
  --url    "BASE_URL_2"
```

Skip to **Step 3**.

---

## Step 2b — Create config (Bitwarden CLI)

Write the config manually as JSON (no secrets stored — only the vault mapping):

```bash
mkdir -p ~/.d365fo-integration
cat > ~/.d365fo-integration/config.json << 'JSONEOF'
{
  "lastUsedEntraApp": "APP_NAME",
  "entraApps": {
    "APP_NAME": {
      "credentialSource": "bitwarden",
      "baseUrl": "BASE_URL",
      "bw": {
        "tenantId":     { "item": "BW_ITEM_FOR_TENANT",  "field": "FIELD_NAME" },
        "clientId":     { "item": "BW_ITEM_FOR_CLIENT",  "field": "FIELD_NAME" },
        "clientSecret": { "item": "BW_ITEM_FOR_SECRET",  "field": "FIELD_NAME" }
      }
    }
  }
}
JSONEOF
echo "Config written."
```

Replace all placeholder values with what the user provided in Step 1b.

For multiple environments, read the existing config and add additional entries under `entraApps` using the same `credentialSource: "bitwarden"` structure per entry (or a mix of manual and BW entries is fine — each entry has its own `credentialSource`).

After writing, proceed to **Step 3**, then **Step 4** to persist to the user's machine.

---

### Config file format reference

**Manual entry entry:**
```json
"Schaefer-DEV": {
  "tenantId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "clientId":  "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "clientSecret": "your-secret-value",
  "baseUrl": "https://schaefer-dev.operations.dynamics.com"
}
```

**Bitwarden CLI entry:**
```json
"Schaefer-DEV": {
  "credentialSource": "bitwarden",
  "baseUrl": "https://schaefer-dev.operations.dynamics.com",
  "bw": {
    "tenantId":     { "item": "D365FO-Schaefer", "field": "notes" },
    "clientId":     { "item": "D365FO-Schaefer", "field": "username" },
    "clientSecret": { "item": "D365FO-Schaefer", "field": "password" }
  }
}
```

- `lastUsedEntraApp` — updated automatically by `get_token.py`; set to first app on creation
- `entraApps` — one key per environment; key is the friendly App Name
- Manual entries require all four raw fields; Bitwarden entries require `credentialSource`, `baseUrl`, and `bw` mapping
- Both styles can coexist in the same config file

## Step 3 — Verify

Confirm the config was written correctly:

```bash
SCRIPT=$(find /sessions -name "config_manager.py" 2>/dev/null | grep d365fo | head -1)
python3 "$SCRIPT" list
```

Then confirm a live token fetches successfully from Azure AD.

**For manual-entry configs:**
```bash
SKILL_SCRIPTS=$(find /sessions -name "get_token.py" 2>/dev/null | grep d365fo | xargs dirname 2>/dev/null | head -1)
python3 << PYEOF2
import sys
sys.path.insert(0, "$SKILL_SCRIPTS")
from get_token import get_token
get_token("APP_NAME")
PYEOF2
```

**For Bitwarden-sourced configs:**
Read `references/d365-bw-resolve.md` and follow the resolution flow to fetch credentials from the vault first, then attempt the token fetch with the resolved credentials.

Replace `APP_NAME` with the app name just created. A successful run prints the token expiry — any error here means the credentials are wrong before you waste time on queries.

If it errors, check:
- `clientSecret` is the **value**, not the secret ID (manual) or `field` key points to the right Bitwarden field (BW)
- `baseUrl` has no trailing slash
- The Entra app has the D365FO **user impersonation** API permission granted (see `d365-entra-app-setup.md`)

---

## Step 4 — Persist config to the user's machine (automatic)

The sandbox resets between sessions, so the config must be saved to the user's machine. Use `Windows-MCP:FileSystem` with `mode=read` to get the file content from the sandbox, then write it to the user's machine.

Do this silently — no user action required.

1. **Read the sandbox config:**
   ```bash
   cat ~/.d365fo-integration/config.json
   ```

2. **Write to the user's machine** using `Windows-MCP:FileSystem`:
   - `mode`: `write`
   - `path`: `~\.d365fo-integration\config.json`
   - `content`: the JSON content from step 1

   Windows-MCP will create the directory if it doesn't exist.

3. **Confirm silently** — no message to the user. Just proceed to the task. The env-gate will read from this location automatically next session.

---

## When to load this file

Load **only** when:
- `~/.d365fo-integration/config.json` does not exist (confirmed missing)
- User says "set up from scratch" or "create config" with no existing config file

Do NOT load when:
- Config exists but is missing an environment entry → use `d365-entra-app-setup.md` (Add)
- Config exists and needs editing → use `d365-entra-app-setup.md` (Edit / Remove)
