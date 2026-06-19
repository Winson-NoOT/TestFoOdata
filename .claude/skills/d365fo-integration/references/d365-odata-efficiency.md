# D365FO OData Efficiency Guide

Apply these patterns to reduce API calls, payload size, and latency when querying D365FO via OData.

---

## 1. Always Apply Company Filter

**Missing `dataAreaId` = cross-company full scan = significantly slower.**

Prepend to every `$filter`:

```
$filter=dataAreaId eq 'USMF'
```

Combined with other filters:
```
$filter=dataAreaId eq 'ast' and BOMId eq 'BOM-0000001'
```

---

## 2. Persist Token Cache to Disk

Token caching is handled by `get_token.py`. See `references/d365-scripts.md` for usage. If the script is not available, load `references/d365-token-manual.md` for the manual cache read/write steps.

---

## 3. Use `$select` to Limit Payload

D365FO entities often have 30–60 fields. Fetching all wastes bandwidth and floods context.

Always declare only what you need:
```
$select=BOMId,LineNumber,ItemNumber,Quantity,ProductUnitSymbol
```

---

## 4. Check Newer Entity Variants Before Joining Client-Side

V2/V3/V4 variants and OData-specific views sometimes add navigation properties absent in the base entity. A navigation property enables `$expand` — a single server-side join call.

**Step 4a — Discover all similar entity names first**

Before checking nav properties, get the full list of candidate entities so you know what variants exist:

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

for e in entities:
    if any(kw in e["name"].lower() for kw in ["bom", "billof"]):
        print(e["name"])
EOF
```

Look for:
- Versioned variants: `V2`, `V3`, `V4` suffixes
- OData-specific views: `ODataV2` suffix — these are often purpose-built for API consumption and may already embed related data
- Combined/denormalised views: entity names that reference **both** concepts (e.g., `BillOfMaterialsVersionsODataV2` may expose both header and line fields in one entity)

**Step 4b — Check nav properties on each promising variant**

Run `check_nav.py` on the highest version AND any ODataV2 variant found, in the SAME bash call as init:

```bash
python3 << 'EOF'
import glob, os, sys, json
_p = glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts") + \
     [os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
      os.path.expanduser("~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts")]
sys.path.insert(0, next(p for p in _p if os.path.isdir(p)))
from init import init_session
from odata_utils import odata_get
from check_nav import check_nav

s = init_session("YourAppName")
check_nav("BillOfMaterialsLinesV3",         token=s["token"], base_url=s["baseUrl"])
check_nav("BillOfMaterialsVersionsODataV2", token=s["token"], base_url=s["baseUrl"])
EOF
```

- **Nav property found on any variant** → use that entity + `$expand` (1 API call, true server-side join):
  ```
  GET /data/BillOfMaterialsLinesV3?$expand=BillOfMaterialsHeader($select=BOMName)&$top=10&$filter=dataAreaId eq 'ast'&$select=BOMId,LineNumber,ItemNumber,Quantity
  ```
- **ODataV2 or combined entity found with both header + line fields** → query it directly with `$select` only (no join needed, 1 call)
- **No nav property on ANY variant** → **STOP. Do not auto-proceed.** Tell the user:

  > "No navigation property found on any entity variant — a true OData server-side join (`$expand`) is not available. The fallback is `$batch`: two separate queries (header + line) sent in one HTTP call, merged client-side in Python. This is NOT a single joined query. Would you like to proceed with the `$batch` approach?"

  Present options via `ASK_TOOL`:
  - Option A: "Yes, use `$batch` (2 queries, client-side merge)"
  - Option B: "No, stop here — I only want a true OData join"

  **STOP. Wait for explicit user confirmation before proceeding.**

---

## 5. Use `$batch` to Combine Multiple Requests into One HTTP Call

When `$expand` is not available, bundle 2+ queries into a single HTTP round-trip via `POST /data/$batch`.

```bash
python3 << 'EOF'
import glob, os, sys, json, uuid
_p = glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts") + \
     [os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
      os.path.expanduser("~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts")]
sys.path.insert(0, next(p for p in _p if os.path.isdir(p)))
from init import init_session
from odata_utils import odata_get

s        = init_session("YourAppName")
boundary = f"batch_{uuid.uuid4().hex}"

batch_body = (
    f"--{boundary}\r\n"
    f"Content-Type: application/http\r\n"
    f"Content-Transfer-Encoding: binary\r\n\r\n"
    f"GET {s['baseUrl']}/data/BillOfMaterialsLines?$filter=dataAreaId eq '{s['dataAreaId']}'&$top=10&$select=BOMId,LineNumber,ItemNumber,Quantity HTTP/1.1\r\n"
    f"Accept: application/json\r\n\r\n"
    f"--{boundary}\r\n"
    f"Content-Type: application/http\r\n"
    f"Content-Transfer-Encoding: binary\r\n\r\n"
    f"GET {s['baseUrl']}/data/BillOfMaterialsHeaders?$filter=dataAreaId eq '{s['dataAreaId']}' and (BOMId eq 'BOM-0000001' or BOMId eq 'BOM-0000002')&$select=BOMId,BOMName HTTP/1.1\r\n"
    f"Accept: application/json\r\n\r\n"
    f"--{boundary}--\r\n"
).encode("utf-8")

req = urllib.request.Request(
    f"{s['baseUrl']}/data/$batch",
    data=batch_body,
    method="POST",
    headers={
        "Authorization":    f"Bearer {s['token']}",
        "OData-MaxVersion": "4.0",
        "OData-Version":    "4.0",
        "Content-Type":     f"multipart/mixed; boundary={boundary}",
    }
)
with urllib.request.urlopen(req) as resp:
    print(resp.read().decode("utf-8"))
EOF
```

> **Two-step note:** If BOMIds for the headers filter aren't known upfront, run the lines query first to get them, then send the header lookup as a `$batch` with the known IDs. This still saves one network round-trip compared to 2 sequential calls.

---

## Decision Tree: How Many API Calls Do I Need?

```
Need related entity data?
├── Step 1: Discover all similar entity names via /data keyword filter
│   └── Step 2: Check nav properties (check_nav.py) on:
│           - Highest versioned variant (V3, V4...)
│           - Any ODataV2 variant (purpose-built for API, often has nav props or embedded fields)
│           ├── Nav property found on any variant
│           │     → $expand  → 1 call, true server-side join
│           ├── ODataV2 / combined entity has both fields already
│           │     → $select only  → 1 call, no join needed
│           └── No nav property on ANY variant
│                 → STOP. Ask user:
│                   A) "Yes, use $batch (2 queries, client-side merge)"
│                   B) "No, stop — I only want a true OData join"
│                   ↓ Only if A selected:
│                   ├── IDs known upfront → $batch  → 1 HTTP call
│                   └── IDs unknown      → 2 calls (lines first, then $batch headers)
└── No related data needed   → 1 call with $filter + $select
```

---

## Quick Checklist

Before running any OData query:

- [ ] `dataAreaId` filter applied
- [ ] `$select` lists only needed fields
- [ ] Token cache read (skip fetch if valid)
- [ ] Nav property checked on latest entity variant
- [ ] Multiple queries bundled via `$batch` if applicable

---

## When to load this file

Load when:
- The query involves related entities, joins, `$expand`, or `$batch`
- User asks about performance, reducing API calls, or payload size
- Routing table directs here for an OData efficiency/join task
- `d365-odata.md` Step 3 decision tree points to this file

---

## When to load this file

Load when:
- User asks about performance, slow queries, or reducing API calls
- The query involves related entities or a join (load alongside `d365-odata.md`)
- User asks about `$batch`, `$select` optimisation, or token caching
- Join detection is triggered in SKILL.md (two entity types, header+lines, "expand")

Do NOT load for simple single-entity reads with no join — `d365-odata.md` alone is sufficient.
