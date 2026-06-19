# D365FO Manual Token Fetch

Use this only when `get_token.py` is not available at the path in `d365-scripts.md`.

**Python (cross-platform, stdlib only):**
```python
import json, time, urllib.parse, urllib.request

tenant_id     = "YOUR_TENANT_ID"
client_id     = "YOUR_CLIENT_ID"
client_secret = "YOUR_CLIENT_SECRET"
base_url      = "https://yourenv.operations.dynamics.com"

data = urllib.parse.urlencode({
    "grant_type":    "client_credentials",
    "client_id":     client_id,
    "client_secret": client_secret,
    "resource":      base_url,
}).encode("utf-8")

req = urllib.request.Request(
    f"https://login.microsoftonline.com/{tenant_id}/oauth2/token",
    data=data, method="POST"
)
with urllib.request.urlopen(req) as resp:
    resp_data = json.loads(resp.read().decode("utf-8"))

token      = resp_data["access_token"]
expires_at = int(time.time()) + int(resp_data.get("expires_in", 3600))
```

**curl (bash, cross-platform):**
```bash
response=$(curl -s -X POST \
  "https://login.microsoftonline.com/$tenantId/oauth2/token" \
  -d "grant_type=client_credentials&client_id=$clientId&client_secret=$clientSecret&resource=$baseUrl")
token=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
expiresAt=$(( $(date +%s) + $(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['expires_in'])") ))
```

After fetching: write `access_token` + `expiresAt` to `~/.d365fo-integration/token-cache.json` under the app name key.

---

## When to load this file

Load only when `get_token.py` is not available at the path defined in `d365-scripts.md`. Do not load for normal token operations — use the script instead.

---

## When to load this file

Load only when `get_token.py` is confirmed unavailable at the path in `d365-scripts.md`. Do not load for normal token operations — `get_token.py` handles all standard cases automatically.
