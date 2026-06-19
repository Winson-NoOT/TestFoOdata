# D365FO OData Usage

## Step 1: Resolve the environment

> Environments and credentials come entirely from Bitwarden Secrets Manager via the `bws` CLI — each bws project is one environment. See `references/d365-bws-resolve.md`. If the environment is unknown, run the env-gate onboarding flow (`d365-env-gate.md`) first.

**MANDATORY — do not skip or assume. Always resolve the environment FIRST — before drafting any query, before any API call, before any other action. The selected environment determines baseUrl and dataAreaId used in every query.**

**If user specified an environment explicitly** OR **it was already established through the env gate this session:** use it directly, skip the steps below.

**If no environment is known, follow these rules in order:**

1. List environments: `python3 <scripts>/bws_creds.py envs` (one per bws project).
2. If none are returned → STOP and tell the user: *"No D365FO environments found in Bitwarden Secrets Manager. Check `BWS_ACCESS_TOKEN` and the bws projects."* Do not proceed.
3. If exactly one exists, use it. Otherwise **show a picker** using `ASK_TOOL`:
   - List all environment names. If a last-used environment exists (`bws_creds.get_last_env()`), append `" (last used)"` to it.
   - **STOP. Do not write any text, draft any query, or produce any output before or after calling the picker. Wait silently for the user's selection — it is the only thing that may appear.**
   - Use the environment the user selected.

The last-used environment is tracked automatically by `resolve_creds` (`~/.d365fo-integration/last-env.txt`) — no manual step needed.

`init_session` resolves `tenantId`, `clientId`, `clientSecret`, and `baseUrl` from the project's secrets automatically.

## Step 2: Get access token

**Important:** Bash tool calls do NOT share shell state. Each call is a fresh session. Always call `init_session` at the top of every bash Python block and run the query in the same block. Never split init and query across two separate tool calls.

Use `init.py` (see `references/d365-scripts.md`) — it handles token caching automatically:
```bash
python3 << 'EOF'
import glob, os, sys, json
_p = glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts") + \
     [os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
      os.path.expanduser("~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts")]
sys.path.insert(0, next(p for p in _p if os.path.isdir(p)))
from init import init_session
from odata_utils import odata_get

s = init_session("YourAppName")  # token cached to ~/.d365fo-integration/token-cache.json
# run your query immediately below in the SAME block
EOF
```
Token is cached to `~/.d365fo-integration/token-cache.json` and reused if still valid (>60s remaining).

## Known D365FO OData Limitations

Do NOT use — these return 400 errors:

| Feature | Status | Workaround |
|---|---|---|
| `in` operator (`BOMId in ('A','B')`) | ❌ Not supported | `or` chain: `BOMId eq 'A' or BOMId eq 'B'` |
| `has` operator | ❌ Not supported | Use `eq`/`ne` chains |
| `$expand` beyond first level | ❌ Only first-level nav properties work | Query related entities separately |
| `$apply` (aggregation/groupby) | ❌ Not supported | Aggregate client-side |
| `$search` | ❌ Not supported | Use `$filter` with wildcard `eq '*value*'` |
| Lambda operators (`any`, `all`) | ❌ Not supported | Filter client-side |
| Array fields in entities | ❌ Not supported | Avoid array fields in entity design |

String filter syntax that WORKS in D365FO:
- Wildcard contains: `$filter=Name eq '*retail*'` (D365FO uses `*` inside `eq`, not standard `contains()`)
- `startswith(Name,'ABC')` — supported
- `endswith(Name,'XYZ')` — supported

Enum filter syntax: `$filter=Status eq Microsoft.Dynamics.DataEntities.SalesStatus'Open'`

Cross-company: append `?cross-company=true`. To filter a non-default company: `?cross-company=true&$filter=dataAreaId eq 'usrt'`

## Step 3: Discover entities — only when needed

### When to SKIP discovery entirely
If ANY of the following are true, go directly to Step 4:
- User named the entity explicitly
- Entity name retrieved earlier in this conversation

Do NOT call `/data`, `d365fo_list_entities`, or `$metadata` unless the entity is genuinely unknown.

### When you DO need to discover an entity name
Filter immediately — never dump the full list.

**IMPORTANT:** `/data` returns objects with `name`, `kind`, `url` properties — NOT plain strings. Always filter on the `name` field (case-insensitive):
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
entities = odata_get(f"{s['baseUrl']}/data", s["token"])["value"]

keyword = "BOM"
matches = [e["name"] for e in entities if keyword.lower() in e["name"].lower()]
print("\n".join(matches))
EOF
```

Do NOT filter against the raw object string — always access `.name` explicitly.

### Picking the right entity version (V2, V3, etc.)
D365FO entities are versioned — higher versions have more fields and better data quality.
1. Use the discovery query above to find all available versions
2. Pick the **highest available version** (e.g. prefer `BillOfMaterialsLinesV3` over `BillOfMaterialsLines`)

### When the query involves related entities (join scenario)

**Before writing any query**, follow the Decision Tree in `references/d365-odata-efficiency.md` Section 4.

### When to use `$metadata` for nav property check
Only to confirm navigation properties before attempting `$expand`. Do NOT use it to discover field names.

**Known issue:** `$metadata` entity type names often differ from `/data` URL segment names. If it returns "entity not found", try the singular form (e.g. `BillOfMaterialsHeader`). If it still fails → tell the user and stop. Do NOT silently fall back.

**If `$expand` is confirmed unavailable** (no navigation property on any entity variant): use `ASK_TOOL` to present options — be explicit that a true OData join is not possible:
- Option A: "Use `$batch` — two separate queries merged client-side (NOT a true OData join)"
- Option B: "Stop here — I only want a true single-query OData join"

**STOP. Do not proceed until the user selects.** If they choose Option A → read `references/d365-odata-join.md` for the pattern.

## Step 4: OData queries

**Always include company filter** unless entity is cross-company:
```
$filter=dataAreaId eq 'USMF'
```

| Option | Purpose | Example |
|---|---|---|
| `$filter` | Filter rows | `$filter=dataAreaId eq 'USMF' and Status eq 'Open'` |
| `$select` | Limit fields | `$select=SalesOrderNumber,CustomerAccount` |
| `$expand` | Related entities (only if navigation property confirmed via metadata) | `$expand=SalesOrderLines` |
| `$top` | Limit rows | `$top=10` |
| `$orderby` | Sort | `$orderby=CreatedDateTime desc` |
| `$count=true` | Total count | `?$count=true` |

**Example query (Python, stdlib only):**
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
uri = (f"{s['baseUrl']}/data/SalesOrderHeadersV2"
       f"?$filter=dataAreaId eq '{s['dataAreaId']}' and SalesOrderStatus eq 'Open'"
       f"&$select=SalesOrderNumber,CustomerAccount&$top=10")
print(json.dumps(odata_get(uri, s["token"])["value"], indent=2))
EOF
```

Create/Update/Delete use POST/PATCH/DELETE with `Content-Type: application/json`.

**Execution policy:**

- **GET queries (read):** Run silently against the live environment. Fix any entity name, field name, or filter errors. Present only the working, tested query and its results to the user — never an untested draft.
- **POST / PATCH / DELETE (write/update/delete):** Draft the call, then stop and show the user what will be executed and ask for confirmation before sending. These are destructive.
- **User says "just show me the query":** Comply, but label it clearly as **untested**.

## Error handling

| Error | Cause | Fix |
|---|---|---|
| 401 Unauthorized | Token expired or wrong resource URL | Clear cache entry, re-fetch token |
| 404 Not Found | Wrong entity name or URL segment | Verify with `/data` keyword filter; check singular vs. plural |
| 400 — unsupported operator | Used `in`, `has`, `any`, `all`, `$apply`, `$search` | See Limitations section; rewrite using supported syntax |
| 400 — field not found | Wrong field name | Use `$top=1` to inspect actual field names |
| 400 — expand failed | No nav property, or expansion beyond first level | Tell user; wait for their decision on how to proceed |
| 414 URI Too Long | OR filter chain > ~50 keys | Batch requests in groups of 50 |
| Entity not found in `$metadata` | Name mismatch between `/data` and `$metadata` | Try singular form; if still fails, report to user — do not silently fall back |
