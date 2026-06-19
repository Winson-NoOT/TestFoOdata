"""
D365FO token fetcher — reads config, checks cache, fetches token if expired.

Usage (CLI):
    python get_token.py [--app APP_NAME] [--json]

Usage (import):
    from get_token import get_token
    session = get_token("EP prod")
    # returns {"token": "...", "baseUrl": "...", "appName": "..."}
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_DIR  = Path.home() / ".d365fo-integration"
CONFIG_FILE = CONFIG_DIR / "config.json"
CACHE_FILE  = CONFIG_DIR / "token-cache.json"


def get_token(app_name: str = "") -> dict:
    """Fetch or reuse a cached OAuth 2.0 bearer token for a D365FO Entra app.

    Reads credentials from ``~/.d365fo-integration/config.json``, checks the
    token cache (``token-cache.json``), and only calls the Microsoft identity
    endpoint when the cached token is missing or expiring within 60 seconds.

    Parameters
    ----------
    app_name : str, optional
        Friendly name that matches a key in ``config.json["entraApps"]``.
        Resolution order when omitted:
          1. ``lastUsedEntraApp`` in config (if present and valid)
          2. The only configured app (if exactly one exists)
          3. Interactive prompt asking the user to pick by index number

    Returns
    -------
    dict
        ``{"token": str, "baseUrl": str, "appName": str}``
        - ``token``   — Bearer token string; pass to Authorization header
        - ``baseUrl`` — D365FO base URL, e.g. ``https://epmb-prod.operations.dynamics.com``
        - ``appName`` — Resolved app name (useful when app_name was not supplied)

    Example
    -------
        from get_token import get_token

        s = get_token("EP prod")
        token    = s["token"]
        base_url = s["baseUrl"]
        # Use token in Authorization header, base_url to build OData URLs
    """
    if not CONFIG_FILE.exists():
        print(f"Config not found: {CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)

    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    apps   = list(config.get("entraApps", {}).keys())

    if not apps:
        print("No Entra apps configured. Run Entra app setup first.", file=sys.stderr)
        sys.exit(1)

    # Resolve which app to use
    if not app_name:
        last = config.get("lastUsedEntraApp", "")
        if last and last in apps:
            app_name = last
            print(f"Using last app: {app_name}")
        elif len(apps) == 1:
            app_name = apps[0]
        else:
            print("Available apps:")
            for i, name in enumerate(apps):
                print(f"  [{i}] {name}")
            idx      = int(input("Select app number: "))
            app_name = apps[idx]

    app           = config["entraApps"][app_name]
    tenant_id     = app["tenantId"]
    client_id     = app["clientId"]
    client_secret = app["clientSecret"]
    base_url      = app["baseUrl"].rstrip("/")

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
            "client_secret": client_secret,
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
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")

        # Update lastUsedEntraApp so next call defaults to this app
        config["lastUsedEntraApp"] = app_name
        CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        print("Token fetched and cached.")

    print(f"\nToken ready — appName: {app_name}  baseUrl: {base_url}")

    return {"token": token, "baseUrl": base_url, "appName": app_name}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch D365FO OAuth token")
    parser.add_argument("--app",  default="", help="Entra app name")
    parser.add_argument("--json", action="store_true", dest="json_out",
                        help="Output result as JSON (suppresses status messages)")
    args = parser.parse_args()

    if args.json_out:
        # Suppress status prints — only emit JSON
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = get_token(args.app)
        print(json.dumps(result))
    else:
        result = get_token(args.app)
