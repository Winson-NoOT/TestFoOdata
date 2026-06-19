# D365FO OData — Two-Query Client-Side Join Pattern

Use this when `$expand` is unavailable and the user has confirmed they want a client-side join.

## Pattern

All steps run in a **single bash tool call** — session state is not shared between calls.

```bash
python3 << 'EOF'
import glob, os, sys, json
_p = glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts") + \
     [os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
      os.path.expanduser("~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts")]
sys.path.insert(0, next(p for p in _p if os.path.isdir(p)))
from init import init_session
from odata_utils import odata_get

s  = init_session("YourAppName")
da = s["dataAreaId"]
tk = s["token"]

# Step A — Query primary entity; select only join key + fields needed
primary = odata_get(
    f"{s['baseUrl']}/data/BillOfMaterialsHeaders"
    f"?$filter=dataAreaId eq '{da}'&$select=BOMId,BOMName",
    tk
)["value"]

# Step B — Build an `or` filter from the keys — NEVER use `in`
bom_ids   = [r["BOMId"] for r in primary]
or_filter = " or ".join(f"BOMId eq '{bid}'" for bid in bom_ids)

# Step C — Query related entity using the `or` filter
related = odata_get(
    f"{s['baseUrl']}/data/BillOfMaterialsLines"
    f"?$filter=dataAreaId eq '{da}' and ({or_filter})"
    f"&$select=BOMId,LineNumber,ItemNumber,Quantity,ProductUnitSymbol&$top=10",
    tk
)["value"]

# Step D — Join client-side by shared key
lookup = {r["BOMId"]: r["BOMName"] for r in primary}
result = [
    {
        "BOMId":      r["BOMId"],
        "BOMName":    lookup.get(r["BOMId"], ""),
        "LineNumber": r["LineNumber"],
        "ItemNumber": r["ItemNumber"],
        "Quantity":   r["Quantity"],
    }
    for r in related
]
print(json.dumps(result, indent=2))
EOF
```

## Batch limit
If you have more than ~50 keys, split into batches of 50 to avoid HTTP 414 URI Too Long:

```python
# After Step A — chunk bom_ids into batches of 50
results = []
for i in range(0, len(bom_ids), 50):
    chunk     = bom_ids[i : i + 50]
    or_filter = " or ".join(f"BOMId eq '{bid}'" for bid in chunk)
    results.extend(odata_get(
        f"{s['baseUrl']}/data/BillOfMaterialsLines"
        f"?$filter=dataAreaId eq '{da}' and ({or_filter})"
    ))
```

---

## When to load this file

Load when:
- `$expand` has been confirmed unavailable on all entity variants
- User has agreed to proceed with a client-side join (`$batch` fallback)
- `d365-odata-efficiency.md` Section 4b decision tree selected "Yes, use `$batch`"

---

## When to load this file

Load only after the user has **explicitly confirmed** they want a two-query client-side join — i.e. after `d365-odata-efficiency.md` presented the `$batch` option and the user selected it. Do not load preemptively.
