# D365FO Entra App Setup

Manage apps in `~/.d365fo-integration/config.json` (override with `D365FO_INTEGRATION_CONFIG` env var).

All operations use `config_manager.py`. Each command below is self-contained and can be run as its own bash tool call.

---

## Config structure (reference)

```json
{
  "lastUsedEntraApp": "contoso-prod",
  "entraApps": {
    "contoso-prod": {
      "tenantId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "clientId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "clientSecret": "your-client-secret-here",
      "baseUrl": "https://contoso.operations.dynamics.com"
    },
    "contoso-dev": {
      "credentialSource": "bitwarden",
      "baseUrl": "https://contoso-dev.operations.dynamics.com",
      "bw": {
        "tenantId":     { "item": "D365FO-Contoso", "field": "notes" },
        "clientId":     { "item": "D365FO-Contoso", "field": "username" },
        "clientSecret": { "item": "D365FO-Contoso", "field": "password" }
      }
    }
  }
}
```

Two credential source styles can coexist in the same config. Manual entries store raw values; Bitwarden entries store vault references only (no secrets at rest).

`lastUsedEntraApp` is managed automatically — never ask the user to set it.

---

## Initial setup

1. Check if `config.json` exists:
   - **Not found:** stop here — read `references/d365-config-create.md` to create the config first, then return to this file for ongoing management.
   - **Found:** use `ASK_TOOL` to ask what the user wants to do:
     - Option A: "Manage existing apps" — add, edit, remove, or list
     - Option B: "Import and replace" — wipe config and replace with file or pasted JSON
     - **STOP. Do not proceed until the user selects.**
   - **Import selected:** use `ASK_TOOL`:
     - Option A: "Provide a file path" — read from disk
     - Option B: "Paste JSON directly" — fallback
     - **STOP. Do not proceed until the user selects.**

---

## List apps

```bash
python3 ~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts/config_manager.py list
```

---

## Add app

First, use `ASK_TOOL` to ask: **"How do you want to store credentials for this new app?"**
- **A) Manual entry** — type credentials into a form
- **B) Bitwarden CLI** — map each credential to a Bitwarden vault item/field

**STOP. Wait for selection.**

**If A (manual):** Collect credentials via widget (see App collection flow below), then run:

```bash
python3 ~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts/config_manager.py add \
  --app    "APP_NAME" \
  --tenant "TENANT_ID" \
  --client-id "CLIENT_ID" \
  --secret "CLIENT_SECRET" \
  --url    "BASE_URL"
```

**If B (Bitwarden):** Follow the BW item picker flow below to collect App Name, Base URL, and three item mappings. Then write the entry directly into `~/.d365fo-integration/config.json`:

```python
import json, os

cfg_path = os.path.expanduser("~/.d365fo-integration/config.json")
with open(cfg_path) as f:
    cfg = json.load(f)

cfg["entraApps"]["APP_NAME"] = {
    "credentialSource": "bitwarden",
    "baseUrl": "BASE_URL",
    "bw": {
        "tenantId":     { "item": "BW_ITEM_ID_TENANT",  "field": "password" },
        "clientId":     { "item": "BW_ITEM_ID_CLIENT",  "field": "password" },
        "clientSecret": { "item": "BW_ITEM_ID_SECRET",  "field": "password" }
    }
}

with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)
print("App added.")
```

> **Use item IDs, not names.** Multiple BW items can share the same display name across folders (e.g. `"app tenant id"` may exist in both Schaefer and VSTECS folders). Storing the UUID avoids "More than one result was found" errors at credential resolution time. The picker flow below fetches IDs automatically.

### BW item picker flow

#### Stage 1 — Sync + show folder picker widget

1. **Sync vault** via Windows-MCP:
   ```powershell
   bw sync --session $s
   ```

2. **Fetch all folders**:
   ```powershell
   bw list folders --session $s | ConvertFrom-Json | ForEach-Object { "$($_.id)|$($_.name)" }
   ```

3. **Render a folder picker widget** using `visualize:show_widget`. Populate it with the **live folder list** — include a filter input and a "Show all (no folder filter)" option. On selection, call `sendPrompt()` with the chosen folder ID and name (or `"ALL"` if no filter).

   > Do NOT skip straight to the item list. Always show the folder picker first so the user can scope down. This avoids showing hundreds of unrelated vault items and prevents the duplicate-name problem.

4. **Receive the folder selection** (arrives as a chat message with folder ID or `"ALL"`).

#### Stage 2 — Fetch items + show item picker widget

5. **Fetch items** scoped to the selected folder (or all items if `"ALL"`):
   ```powershell
   # Scoped to folder:
   $items = bw list items --folderid FOLDER_ID --session $s | ConvertFrom-Json

   # All items (no folder filter):
   $items = bw list items --session $s | ConvertFrom-Json

   $items | ForEach-Object { "$($_.id)|$($_.name)" }
   ```

6. **Render the item picker widget** using `visualize:show_widget`. Populate it with the **live item list from step 5** — never hardcode or reuse a stale list from a previous call. The widget must include:
   - A filter/search input
   - All items listed with **T / C / S** buttons (Tenant ID / Client ID / Client Secret)
   - A selection summary showing current picks
   - A confirm button (disabled until all three are assigned) that calls `sendPrompt()` with the selected item IDs and field names

7. **Receive the mapping** (arrives as a chat message). Store IDs in the config entry as shown above.

---

## Edit a field

```bash
python3 ~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts/config_manager.py edit --app "APP_NAME" --field FIELD --value "NEW_VALUE"
```

`FIELD` must be one of: `tenantId`, `clientId`, `clientSecret`, `baseUrl`

After running, sync the updated config to the user's machine via `Windows-MCP:FileSystem` (`mode=write`, `path=~\.d365fo-integration\config.json`). Do this silently.

---

## Remove an app

```bash
python3 ~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts/config_manager.py remove --app "APP_NAME"
```

Automatically clears `lastUsedEntraApp` if it pointed to the removed app.

After running, sync the updated config to the user's machine via `Windows-MCP:FileSystem` (`mode=write`, `path=~\.d365fo-integration\config.json`). Do this silently.

---

## App collection flow (credential collection for manual Add)

**Do not collect credentials via plain chat text.** Read `assets/env-setup-widget.html` and pass its content verbatim to `visualize:show_widget`. All five fields are required. Wait for the user to submit (arrives as a chat message starting with `D365FO env details:`).

After submission, verify all five fields are present. If any are missing, tell the user which fields are empty and show the widget again.

Once all fields are received, run the Add command above. Then **strip any injected plaintext credentials** from Bitwarden-sourced entries (see cleanup step in `d365-bw-resolve.md` Step 4W) before syncing config back. Then **sync the updated config back to the user's machine** using `Windows-MCP:FileSystem` (`mode=write`, `path=~\.d365fo-integration\config.json`). Do this silently.

Then ask using `ASK_TOOL`: "Add another Entra app?"
- Option A: "Yes, add another" — show the widget again; loop
- Option B: "No, I'm done" — done

**STOP after asking. Do not proceed until the user selects.**

---

## When to load this file

Load when:
- User explicitly asks to manage Entra apps — add, edit, remove, or list apps in an existing config
- User says "import and replace" config
- Routing table row: "Manage Entra apps — add, edit, remove, list"

Do NOT load for first-time setup when `config.json` does not exist — use `d365-config-create.md` instead.
