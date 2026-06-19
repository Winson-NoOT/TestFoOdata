# Testing D365 FO OData

FO URLs come from env vars (`env | grep -i '^FoUrl'`); credentials from `bws`.

| FO env var     | `bws` project  | Project ID                             |
|----------------|----------------|----------------------------------------|
| `FoUrlSsiDev3` | `Shaefer dev3` | `dc7f61e3-b52a-4b1a-9fe2-b46b00281073` |
|                | `VSTECS`       | `bf36f9df-23b8-48e2-a5d5-b46b001d6fc9` |

```bash
PID=dc7f61e3-b52a-4b1a-9fe2-b46b00281073
get() { bws secret list "$1" -o json | python3 -c \
  "import sys,json;d=json.load(sys.stdin);print(next(s['value'] for s in d if s['key']==sys.argv[1]))" "$2"; }
CID=$(get "$PID" "barcode app id"); TID=$(get "$PID" "barcode app tenant id"); SEC=$(get "$PID" "barcode app secret value")
RES="https://$FoUrlSsiDev3"

TOKEN=$(curl -s -X POST "https://login.microsoftonline.com/$TID/oauth2/token" \
  -d grant_type=client_credentials -d "client_id=$CID" \
  --data-urlencode "client_secret=$SEC" --data-urlencode "resource=$RES" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -w "\nHTTP %{http_code}\n" -X POST "$RES/data/SalesQuotationHeaders" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -H "Accept: application/json" \
  -d '{"dataAreaId":"ssr","InvoiceCustomerAccountNumber":"SRA0001","RequestingCustomerAccountNumber":"SRA0001","CurrencyCode":"MYR","SalesQuotationName":"API test quotation"}'
```

Next time: "Test call **<env>** OData, create **<entity>** with **<values>**, show the input."
