# D365FO Reusable Helper Scripts

These scripts live in the `scripts/` subfolder of this skill and are designed to be reused across all D365FO OData queries. They are written in **Python 3** and work on Windows, macOS, and Linux without extra dependencies (stdlib only).

## Script Inventory

| Script | Purpose | Returns (import) |
|---|---|---|
| `odata_utils.py` | Shared utilities: `find_skill_scripts()`, `safe_url()`, `odata_get/post/patch/delete()` | importable functions |
| `config_manager.py` | Config CRUD — create, add, edit, remove, list, check | CLI only (no import) |
| `init.py` | Orchestrator — runs get_token then get_company | `{"token", "baseUrl", "appName", "dataAreaId"}` |
| `get_token.py` | Read config, check token cache, fetch new token if expired | `{"token", "baseUrl", "appName"}` |
| `get_company.py` | Resolve default company from SysAADClients + SystemUsers | `{"dataAreaId"}` |
| `check_nav.py` | Check `$metadata` for navigation properties on any entity | Console output listing nav prop names and types |
| `get_metadata.py` | Fetch + cache $metadata as grep-friendly split files; search entities, enums, actions | CLI only / `ensure_metadata()` importable |

## Location

Scripts are bundled in the `scripts/` subfolder of this skill:

```
scripts/config_manager.py
scripts/init.py
scripts/get_token.py
scripts/get_company.py
scripts/check_nav.py
scripts/get_metadata.py
```

The bootstrap pattern below (from Usage Pattern) handles path resolution automatically across Claude Code and Cowork.

## Critical: Bash tool calls do NOT share state

Each bash tool call is a **fresh shell session**. Variables set in one call are gone by the next. This means:

- **Never split init and query across two tool calls** — session values will be empty in the second call.
- **Always call `init_session` at the top of every bash/Python tool call** that needs `token`, `baseUrl`, or `dataAreaId`.
- **Run init and the query in the same Python block** (see Usage Pattern below).

## Usage Pattern

All query blocks share the same 5-line bootstrap. Paste it at the top of every `python3 << 'EOF'` heredoc:

```python
import glob, os, sys, json
_p = glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts") + \
     [os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
      os.path.expanduser("~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts")]
sys.path.insert(0, next(p for p in _p if os.path.isdir(p)))
from init import init_session
from odata_utils import odata_get   # safe_url applied automatically
```

After the bootstrap, call `init_session` and write your query:

**Full example — read query:**
```bash
python3 << 'EOF'
import glob, os, sys, json
_p = glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts") + \
     [os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
      os.path.expanduser("~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts")]
sys.path.insert(0, next(p for p in _p if os.path.isdir(p)))
from init import init_session
from odata_utils import odata_get

s   = init_session("YourAppName")
uri = (f"{s['baseUrl']}/data/BillOfMaterialsLinesV3"
       f"?$filter=dataAreaId eq '{s['dataAreaId']}'&$top=10")
print(json.dumps(odata_get(uri, s["token"])["value"], indent=2))
EOF
```

**Full example — check nav properties:**
```bash
python3 << 'EOF'
import glob, os, sys
_p = glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts") + \
     [os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
      os.path.expanduser("~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts")]
sys.path.insert(0, next(p for p in _p if os.path.isdir(p)))
from init import init_session
from check_nav import check_nav

s = init_session("YourAppName")
check_nav("BillOfMaterialsLinesV3", token=s["token"], base_url=s["baseUrl"])
EOF
```

If `check_nav.py` reports a nav property → use `$expand` in the query (1 API call).
If no nav property → use `$batch` (see `d365-odata-efficiency.md` Section 5).

## init.py — Behaviour

- Imports `get_token` then `get_company` in order
- Accepts optional `app_name` parameter; passes it through to both scripts
- Returns merged dict: `{"token", "baseUrl", "appName", "dataAreaId"}`
- Use this as the single session initializer

**Quick call:**
```python
from init import init_session

s = init_session("EP prod")   # app_name optional; defaults to lastUsedEntraApp
# s["token"]       — bearer token string
# s["baseUrl"]     — https://env.operations.dynamics.com
# s["dataAreaId"]  — "ep" (lowercase)
# s["appName"]     — "EP prod"
```

## get_token.py — Behaviour

- Reads config from `~/.d365fo-integration/config.json`
- If multiple apps and none specified: prompts user to select by index (`input()`)
- Reuses cached token if `expiresAt > now + 60s`
- Otherwise fetches new token via `client_credentials` and writes back to cache
- Updates `lastUsedEntraApp` in config after fetch
- Returns `{"token", "baseUrl", "appName"}`

**Quick call:**
```python
from get_token import get_token

t = get_token("EP prod")    # app_name optional
# t["token"]    — bearer token string
# t["baseUrl"]  — D365FO base URL
# t["appName"]  — resolved app name
```

**CLI (verify token fetches correctly):**
```bash
python3 scripts/get_token.py --app "EP prod"
```

## get_company.py — Behaviour

- Auto-calls `get_token` if token not provided
- Looks up `SysAADClients` by the app's `clientId` → retrieves the mapped D365FO `UserId`
- Looks up `SystemUsers` by that `UserId` → retrieves the `Company` field
- Returns `{"dataAreaId"}` (lowercased) for use in `$filter=dataAreaId eq '...'`

**Quick call (preferred: pass token to avoid a second fetch):**
```python
from get_token import get_token
from get_company import get_company

t  = get_token("EP prod")
co = get_company(app_name=t["appName"], token=t["token"], base_url=t["baseUrl"])
# co["dataAreaId"]  — e.g. "ep"
```

**Or standalone (get_company fetches token internally):**
```python
from get_company import get_company
co = get_company("EP prod")
```

## check_nav.py — Parameters

| Parameter | Required | Description |
|---|---|---|
| `entity` | Yes | Entity name to inspect (e.g. `BillOfMaterialsLinesV3`) |
| `app_name` | No | Entra app name; defaults to last used |
| `token` | No | Reuse existing token if already loaded from `init_session` |
| `base_url` | No | Reuse existing baseUrl if already loaded from `init_session` |

Auto-calls `get_token` if `token` is not provided.
Tries both exact entity name and singular form if not found in `$metadata`.

## get_metadata.py — Metadata cache for token-efficient schema lookup

`get_metadata.py` fetches the D365FO `$metadata` document once (~52 MB) and splits it into five flat, grep-friendly cache files. Subsequent lookups hit local files instead of the API — **191–326× faster** than XML parsing tools, and ~70–85% fewer tokens per query.

### Cross-session persistence

The cache is stored in **two locations**:

| Location | Lifetime | Purpose |
|---|---|---|
| `~/.d365fo-integration/metadata/{app}/` | Session only (sandbox) | Fast in-session reads |
| `{workspace}/d365fo-metadata-cache/{app}/` | Permanent (local machine) | Survives Cowork session restarts |

On first use in a new session, `ensure_metadata()` checks if the sandbox cache is missing and automatically restores it from the workspace folder if available — so the 52 MB download only happens once across all sessions.

### Cache file layout

```
~/.d365fo-integration/metadata/{app_name}/
  fetched_at.txt        — timestamp + summary counts
  index.txt             — EntityTypeName<TAB>Set:EntitySetName<TAB>*Key1,field2,...
  entity_sets.txt       — EntitySetName -> EntityTypeName  (reverse lookup)
  enums.txt             — EnumName<TAB>Member1=Val1,Member2=Val2,...
  actions.txt           — ActionName<TAB>Bound:EntityType<TAB>params<TAB>Returns:Type
  by_entity/*.txt       — full field details per entity, with inline enum hints
```

### CLI usage

```bash
# Fetch (or refresh) the metadata cache for an app
python3 scripts/get_metadata.py --app "EP prod"

# Force a refresh (re-download from D365FO)
python3 scripts/get_metadata.py --app "EP prod" --force

# Search for an entity by name fragment
python3 scripts/get_metadata.py --entity ProductionOrder

# Show all fields for a specific entity (reads by_entity/ file)
python3 scripts/get_metadata.py --fields ProductionOrderHeader

# Show all members of an enum by name
python3 scripts/get_metadata.py --enum ProdStatus

# Search actions by name fragment
python3 scripts/get_metadata.py --action post
```

### Import usage — ensure cache then grep

```python
import glob, os, sys
_p = glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts") + \
     [os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
      os.path.expanduser("~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts")]
sys.path.insert(0, next(p for p in _p if os.path.isdir(p)))

from get_metadata import ensure_metadata

meta_dir = ensure_metadata("EP prod")   # fetches if missing, restores from workspace if available

# Grep the flat files directly — no XML parsing needed
import subprocess
result = subprocess.run(
    ["grep", "-i", "ProductionOrder", str(meta_dir / "index.txt")],
    capture_output=True, text=True
)
print(result.stdout)
```

### When to use get_metadata.py

- User asks "what fields does entity X have?" → `--fields EntityName`
- User asks "what are the valid values for enum Y?" → `--enum EnumName`
- User wants to find an entity whose name they only partially know → `--entity fragment`
- Building a query and need to confirm field names without loading full $metadata XML
- Any situation where you'd otherwise fetch the 52 MB `$metadata` XML in-band

### Parameters

| CLI flag | Import arg | Required | Description |
|---|---|---|---|
| `--app` | `app_name` | No | Entra app name; defaults to last used |
| `--force` | `force=True` | No | Re-download even if cache exists |
| `--entity` | — | No | Search index.txt for entities matching fragment |
| `--fields` | — | No | Print full field details from `by_entity/{name}.txt` |
| `--enum` | — | No | Print enum members from `enums.txt` |
| `--action` | — | No | Search actions.txt for matching actions |

## odata_utils.py — What it provides

| Function | Signature | Purpose |
|---|---|---|
| `find_skill_scripts()` | `() → str` | Locates the scripts dir in both Cowork and Claude Code |
| `safe_url(uri)` | `(str) → str` | Percent-encodes spaces in OData `$filter` (Python 3.10+ compatibility) |
| `odata_get(uri, token)` | `(str, str) → dict` | Authenticated GET, safe URL applied, returns full parsed JSON |
| `odata_post(uri, token, payload)` | `(str, str, dict) → dict` | Authenticated POST (create) |
| `odata_patch(uri, token, payload, etag)` | `(str, str, dict, str) → None` | Authenticated PATCH (update) |
| `odata_delete(uri, token, etag)` | `(str, str, str) → None` | Authenticated DELETE |

`odata_get` returns the whole JSON dict — call `["value"]` to get the rows array.

**Quick call examples:**
```python
from odata_utils import odata_get, odata_post, odata_patch, odata_delete

# GET — read records
rows = odata_get(f"{base_url}/data/SalesOrderHeaders?$filter=dataAreaId eq 'ep'&$top=5", token)["value"]

# POST — create a record
new_rec = odata_post(f"{base_url}/data/SalesOrderHeaders", token, {"SalesOrderNumber": "SO-001", ...})

# PATCH — update a field (etag="*" skips concurrency check)
odata_patch(f"{base_url}/data/SalesOrderHeaders(SalesOrderNumber='SO-001',dataAreaId='ep')", token, {"SalesStatus": "Invoiced"})

# DELETE — remove a record
odata_delete(f"{base_url}/data/SalesOrderHeaders(SalesOrderNumber='SO-001',dataAreaId='ep')", token)
```

## When to Reference This File

Load this reference when:
- User asks to run or modify any of the helper scripts
- User asks "do we have a script for token?" or "how do I check nav properties?" or "how do I get the default company?"
- User wants to find entity fields, enum values, or available actions without fetching $metadata XML
- User wants to add a new reusable helper script for D365FO
- Writing any OData query — to confirm the session init pattern for token, baseUrl, and dataAreaId
