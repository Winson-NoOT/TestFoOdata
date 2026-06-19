"""
D365FO token fetcher — resolves credentials from Bitwarden Secrets Manager
(via bws_creds), checks the token cache, and fetches a new token if expired.

Credentials come entirely from the ``bws`` CLI now — there is no config.json.
Each bws project is one D365FO environment; ``app_name`` is the project name.

Usage (CLI):
    python get_token.py [--app ENV_NAME] [--json]

Usage (import):
    from get_token import get_token
    session = get_token("Shaefer dev3")
    # returns {"token": "...", "baseUrl": "...", "appName": "...", "clientId": "..."}
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Make sibling scripts importable from any cwd.
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bws_creds import resolve_creds

STATE_DIR  = Path.home() / ".d365fo-integration"
CACHE_FILE = STATE_DIR / "token-cache.json"


def get_token(app_name: str = "") -> dict:
    """Fetch or reuse a cached OAuth 2.0 bearer token for a D365FO environment.

    Resolves the Entra app credentials from Bitwarden Secrets Manager (the bws
    CLI) for the selected environment, checks the local token cache
    (``token-cache.json``), and only calls the Microsoft identity endpoint when
    the cached token is missing or expiring within 60 seconds.

    Parameters
    ----------
    app_name : str, optional
        Environment name (= bws project name) or id. When omitted, resolves to
        the last-used environment, or the sole project if only one exists.

    Returns
    -------
    dict
        ``{"token": str, "baseUrl": str, "appName": str, "clientId": str}``
        - ``token``    — Bearer token string; pass to the Authorization header
        - ``baseUrl``  — D365FO base URL, e.g. ``https://env.operations.dynamics.com``
        - ``appName``  — Resolved environment name
        - ``clientId`` — Entra app client id (used by get_company)

    Example
    -------
        from get_token import get_token

        s = get_token("Shaefer dev3")
        token    = s["token"]
        base_url = s["baseUrl"]
    """
    creds      = resolve_creds(app_name)   # raises with a helpful dump if unmappable
    app_name   = creds["appName"]
    base_url   = creds["baseUrl"].rstrip("/")
    tenant_id  = creds["tenantId"]
    client_id  = creds["clientId"]
    secret_val = creds["clientSecret"]

    # Check token cache — reuse if not expiring within 60 seconds
    now    = int(time.time())
    cached = None
    if CACHE_FILE.exists():
        cache_data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        cached     = cache_data.get(app_name)

    if cached and cached.get("expiresAt", 0) > now + 60:
        token     = cached["token"]
        remaining = (cached["expiresAt"] - now) // 60
        print(f"Reusing cached token (expires in {remaining} min)")
    else:
        print("Fetching new token...")
        data = urllib.parse.urlencode({
            "grant_type":    "client_credentials",
            "client_id":     client_id,
            "client_secret": secret_val,
            "resource":      base_url,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/token",
            data=data,
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))

        token      = resp_data["access_token"]
        expires_at = now + int(resp_data.get("expires_in", 3600))

        # Write token cache
        cache = {}
        if CACHE_FILE.exists():
            cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        cache[app_name] = {"token": token, "expiresAt": expires_at}
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        print("Token fetched and cached.")

    print(f"\nToken ready — appName: {app_name}  baseUrl: {base_url}")

    return {"token": token, "baseUrl": base_url, "appName": app_name, "clientId": client_id}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch D365FO OAuth token (creds from bws)")
    parser.add_argument("--app",  default="", help="Environment name (bws project)")
    parser.add_argument("--json", action="store_true", dest="json_out",
                        help="Output result as JSON (suppresses status messages)")
    args = parser.parse_args()

    if args.json_out:
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = get_token(args.app)
        # Do not leak the bearer token in JSON CLI output
        safe = {k: v for k, v in result.items() if k != "token"}
        print(json.dumps(safe))
    else:
        result = get_token(args.app)
