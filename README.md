# Testing Dynamics 365 FO OData

Call a D365 **Finance & Operations (FO)** OData endpoint without re-explaining the
setup. Credentials come from the **Bitwarden Secrets CLI (`bws`)**; FO URLs come
from **environment variables**.

> Flow: pick a secret project → get app id / tenant / secret → get an OAuth token
> with `resource = <FO base URL>` → call `https://<fo-host>/data/<Entity>`.

## Inputs

**FO URLs** (env vars, host only — discover with `env | grep -i '^FoUrl'`):

| Env var        | FO host                                   | Name      |
|----------------|-------------------------------------------|-----------|
| `FoUrlSsiDev3` | `ssiapacmea-dev3.operations.dynamics.com` | SSI dev 3 |

**Credentials** (`bws project list`, `bws secret list <id>`) — each project holds
an AAD app (client id / tenant id / secret). Don't print or commit secret values.

| Project        | Project ID                             | Secret keys                                              |
|----------------|----------------------------------------|----------------------------------------------------------|
| `Shaefer dev3` | `dc7f61e3-b52a-4b1a-9fe2-b46b00281073` | `barcode app id`, `barcode app tenant id`, `barcode app secret value` |
| `VSTECS`       | `bf36f9df-23b8-48e2-a5d5-b46b001d6fc9` | `app id`, `app tenant id`, `app secret value`            |

## Run

```bash
PID=dc7f61e3-b52a-4b1a-9fe2-b46b00281073                 # Shaefer dev3
get() { bws secret list "$1" -o json | python3 -c \
  "import sys,json;d=json.load(sys.stdin);print(next(s['value'] for s in d if s['key']==sys.argv[1]))" "$2"; }
CID=$(get "$PID" "barcode app id"); TID=$(get "$PID" "barcode app tenant id"); SEC=$(get "$PID" "barcode app secret value")
RES="https://ssiapacmea-dev3.operations.dynamics.com"    # = https://$FoUrlSsiDev3

TOKEN=$(curl -s -X POST "https://login.microsoftonline.com/$TID/oauth2/token" \
  -d grant_type=client_credentials -d "client_id=$CID" \
  --data-urlencode "client_secret=$SEC" --data-urlencode "resource=$RES" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Create a sales quotation header (HTTP 201; SalesQuotationNumber auto-assigned)
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

## How to ask next time

> "Test call **<env name>** OData, create a **<entity>** with **<values>**, show the input you used."

To onboard a new environment: add its `FoUrl<Name>` env var and a `bws` project,
then add a row to the tables above.
