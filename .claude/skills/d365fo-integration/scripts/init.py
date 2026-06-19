"""
D365FO session initializer — chains get_token → get_company and returns
a combined session dict with all values needed for OData queries.

Usage (CLI):
    python init.py [--app APP_NAME] [--json]

Usage (import — preferred pattern for inline queries):
    import sys
    sys.path.insert(0, "/path/to/scripts")
    from init import init_session

    session = init_session("EP prod")
    token        = session["token"]
    base_url     = session["baseUrl"]
    data_area_id = session["dataAreaId"]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure sibling scripts are importable from any cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from get_token   import get_token
from get_company import get_company


def init_session(app_name: str = "") -> dict:
    """Chain get_token → get_company and return a full session dict.

    This is the single call you should make at the top of every OData query
    block.  It resolves the bearer token, the D365FO base URL, and the default
    company (dataAreaId) for the Entra app — everything needed to build and
    run a query.

    Parameters
    ----------
    app_name : str, optional
        Environment name (= bws project name). Defaults to the last-used
        environment (same resolution as ``get_token`` / ``bws_creds``).

    Returns
    -------
    dict
        Merged result of ``get_token`` + ``get_company``:
        - ``token``       — Bearer token string for the Authorization header
        - ``baseUrl``     — D365FO base URL, e.g. ``https://epmb-prod.operations.dynamics.com``
        - ``appName``     — Resolved Entra app name
        - ``dataAreaId``  — Default company code (lowercase), e.g. ``"usmf"``

    Example
    -------
        from init import init_session
        from odata_utils import odata_get

        s   = init_session("EP prod")
        uri = (
            f"{s['baseUrl']}/data/SalesOrderHeaders"
            f"?$filter=dataAreaId eq '{s['dataAreaId']}'&$top=5"
        )
        rows = odata_get(uri, s["token"])["value"]
    """
    tok = get_token(app_name)
    co  = get_company(
        app_name  = tok["appName"],
        token     = tok["token"],
        base_url  = tok["baseUrl"],
        client_id = tok["clientId"],
    )
    return {**tok, **co}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize D365FO session")
    parser.add_argument("--app",  default="", help="Entra app name")
    parser.add_argument("--json", action="store_true", dest="json_out",
                        help="Output session as JSON")
    args = parser.parse_args()

    session = init_session(args.app)
    if args.json_out:
        # Exclude token from JSON output for safety unless explicitly needed
        safe = {k: v for k, v in session.items() if k != "token"}
        print(json.dumps(safe))
    else:
        print(f"\nSession ready:")
        print(f"  appName     : {session['appName']}")
        print(f"  baseUrl     : {session['baseUrl']}")
        print(f"  dataAreaId  : {session['dataAreaId']}")
        print(f"  token       : [loaded, {len(session['token'])} chars]")
