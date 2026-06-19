# AGENTS.md — Testing Dynamics 365 Finance & Operations OData

Purpose: let any future session call a D365 **Finance & Operations (FO)** OData
endpoint (query or create records) **without re-explaining the setup**. All
credentials come from the **Bitwarden Secrets CLI (`bws`)**; FO environment URLs
come from **environment variables**.

> TL;DR: pick a secret project → get app id / tenant / secret → get an OAuth
> token with `resource = <FO base URL>` → call `https://<fo-host>/data/<Entity>`.

---

## 1. Inputs available in the session

### FO environment URLs (env vars)
Pattern: `FoUrl<Name>=<host>` (host only, no scheme). Build the base URL as
`https://<host>`.

| Env var        | FO host                                          | "Friendly" name used in chat |
|----------------|--------------------------------------------------|------------------------------|
| `FoUrlSsiDev3` | `ssiapacmea-dev3.operations.dynamics.com`        | "SSI dev 3"                  |

Discover all of them at runtime:
```bash
env | grep -i '^FoUrl'
```

### Credentials (Bitwarden — `bws`)
`BWS_ACCESS_TOKEN` is already set in the environment, so `bws` works with no
extra login. Secrets are grouped into **projects**; each project holds an Azure
AD app registration (client id / tenant id / client secret).

```bash
bws project list          # list projects (id + name)
bws secret list <PROJECT_ID>   # list secrets (key + value) in a project
```

| Project name  | Project ID                             | Secret keys (the values are the OAuth creds)                     |
|---------------|----------------------------------------|------------------------------------------------------------------|
| `Shaefer dev3`| `dc7f61e3-b52a-4b1a-9fe2-b46b00281073` | `barcode app id`, `barcode app tenant id`, `barcode app secret value` |
| `VSTECS`      | `bf36f9df-23b8-48e2-a5d5-b46b001d6fc9` | `app id`, `app tenant id`, `app secret value`                    |

> Map the FO URL to the right secret project by matching names
> (e.g. **SSI/Shaefer dev3** → FO host `ssiapacmea-dev3...` + project `Shaefer dev3`).
> If unsure which project pairs with a URL, ask the user once.

Helper to pull a single secret value by key:
```bash
get() { bws secret list "$1" -o json | python3 -c \
  "import sys,json;d=json.load(sys.stdin);print(next(s['value'] for s in d if s['key']==sys.argv[1]))" "$2"; }
# usage: get <PROJECT_ID> "<secret key>"
```

**Never print secret values** in chat or commit them. Keep them in shell vars only.

---

## 2. Get an OAuth token (client-credentials flow)

FO uses the AAD v1.0 token endpoint with `resource = <FO base URL>`.

```bash
PID=dc7f61e3-b52a-4b1a-9fe2-b46b00281073          # Shaefer dev3
get() { bws secret list "$1" -o json | python3 -c \
  "import sys,json;d=json.load(sys.stdin);print(next(s['value'] for s in d if s['key']==sys.argv[1]))" "$2"; }

CID=$(get "$PID" "barcode app id")
TID=$(get "$PID" "barcode app tenant id")
SEC=$(get "$PID" "barcode app secret value")
RES="https://ssiapacmea-dev3.operations.dynamics.com"   # = https://$FoUrlSsiDev3

TOKEN=$(curl -s -X POST "https://login.microsoftonline.com/$TID/oauth2/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=$CID" \
  --data-urlencode "client_secret=$SEC" \
  --data-urlencode "resource=$RES" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
```

(Tokens last ~1h. Cache `$TOKEN` to a scratchpad file to avoid re-fetching.)

---

## 3. Call OData

Base path is `https://<fo-host>/data`. Always send
`Authorization: Bearer $TOKEN` and `Accept: application/json`.

```bash
# Query (top N)
curl -s "$RES/data/CustomersV3?\$top=5&\$select=dataAreaId,CustomerAccount,OrganizationName,SalesCurrencyCode" \
  -H "Authorization: Bearer $TOKEN" -H "Accept: application/json"

# Query across all companies (default returns only the app's default company)
curl -s "$RES/data/CustomersV3?\$top=5&cross-company=true" \
  -H "Authorization: Bearer $TOKEN" -H "Accept: application/json"

# Create (POST) — example: Sales quotation header
curl -s -w "\nHTTP %{http_code}\n" -X POST "$RES/data/SalesQuotationHeaders" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -H "Accept: application/json" \
  -d '{
    "dataAreaId": "ssr",
    "InvoiceCustomerAccountNumber": "SRA0001",
    "RequestingCustomerAccountNumber": "SRA0001",
    "CurrencyCode": "MYR",
    "SalesQuotationName": "API test quotation"
  }'
```

Success returns **HTTP 201** with the created record. The entity key for
`SalesQuotationHeader` is `dataAreaId` + `SalesQuotationNumber`; leave
`SalesQuotationNumber` out and the number sequence auto-assigns it
(e.g. `SRQO0000002`). Add lines via `POST /data/SalesQuotationLines`.

---

## 4. Discovering an entity's fields (when you don't know them)

- **Field names**: a bad `$select` returns an error naming the type, e.g.
  *"Could not find a property named 'X' on type
  'Microsoft.Dynamics.DataEntities.SalesQuotationHeader'"* — so the type name
  is confirmed; then fetch metadata for the real names.
- **Metadata (keys + types + non-nullable)**:
  ```bash
  curl -s "$RES/data/\$metadata" -H "Authorization: Bearer $TOKEN" > meta.xml
  ```
  Then grep the `<EntityType Name="...">` block for `<PropertyRef>` (keys) and
  `<Property ... Nullable="false">` (mandatory-ish fields).
- Get a real template by querying one existing record (`?$top=1`). If the env is
  empty, use `cross-company=true` to find data in another company.

---

## 5. Reference data found in SSI dev 3 (handy for tests)

Companies (`dataAreaId`) with data: `ssr`, `ssg`.

| dataAreaId | CustomerAccount | Name                     | Currency |
|------------|-----------------|--------------------------|----------|
| `ssr`      | `SRA0001`       | ATLAS VENDING (M) SDN BHD| MYR      |
| `ssr`      | `SRC0003`       | Cash                     | MYR      |
| `ssg`      | `#CUST`         | DUMMY CUSTOMER           | SGD      |

---

## 6. How to ask for a new test (so no re-explaining is needed)

Just tell the agent, e.g.:
> "Test call **<friendly name>** OData, create a **<entity>** with **<a few field values>**, and show the input you used."

The agent should:
1. Resolve `<friendly name>` → FO host via `env | grep -i '^FoUrl'`.
2. Match it to a `bws` project (by name) → pull app id / tenant / secret.
3. Get a token (`resource = https://<host>`).
4. If fields are unknown, discover via §4, then POST/GET.
5. Report HTTP status, the created key, and the exact request body used.

To onboard a **new environment**: add its `FoUrl<Name>` env var and a `bws`
project with `*app id / *app tenant id / *app secret value`, then add a row to
the tables in §1.
