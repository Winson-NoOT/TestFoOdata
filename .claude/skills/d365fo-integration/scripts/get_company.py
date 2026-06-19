"""
D365FO company resolver — resolves the default company for the Entra app via
SysAADClients → SystemUsers.

Usage (CLI):
    python get_company.py [--app APP_NAME] [--json]

Usage (import):
    from get_company import get_company
    result = get_company(app_name="EP prod", token="...", base_url="...")
    # returns {"dataAreaId": "usmf"}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# odata_get wraps urllib with safe_url applied automatically (handles spaces in $filter)
from odata_utils import odata_get as _odata_get


def get_company(app_name: str = "", token: str = "", base_url: str = "",
                client_id: str = "") -> dict:
    """Resolve the default D365FO company (dataAreaId) for an Entra app.

    Performs two OData lookups:
      1. ``SysAADClients`` filtered by the app's ``clientId`` → retrieves the
         mapped D365FO ``UserId``
      2. ``SystemUsers`` filtered by that ``UserId`` → retrieves the ``Company``
         field (returned as ``dataAreaId``, lowercased)

    Parameters
    ----------
    app_name : str, optional
        Environment name (= bws project name). Resolved automatically from the
        last-used environment when omitted.
    token : str, optional
        Existing bearer token.  If empty, ``get_token`` is called automatically.
    base_url : str, optional
        D365FO base URL.  If empty, it is obtained via ``get_token``.
    client_id : str, optional
        Entra app client id.  If empty, it is obtained via ``get_token`` /
        ``bws_creds`` (no config file is read).

    Returns
    -------
    dict
        ``{"dataAreaId": str}``
        ``dataAreaId`` is lowercased (e.g. ``"usmf"``) and ready to use directly
        in ``$filter=dataAreaId eq '{s["dataAreaId"]}'`` expressions.

    Example
    -------
        from get_company import get_company

        co = get_company("EP prod")
        print(co["dataAreaId"])   # e.g. "ep"

        # Or pass an existing token to avoid a second token fetch:
        from get_token import get_token
        s  = get_token("EP prod")
        co = get_company(app_name=s["appName"], token=s["token"], base_url=s["baseUrl"])
    """
    # If token / base_url / client_id not supplied, resolve them via get_token
    # (which sources credentials from bws). get_token returns clientId too.
    if not token or not base_url or not client_id:
        from get_token import get_token
        tok_result = get_token(app_name)
        token     = token     or tok_result["token"]
        base_url  = base_url  or tok_result["baseUrl"]
        client_id = client_id or tok_result["clientId"]
        app_name  = tok_result["appName"]

    # Step 1: SysAADClients → UserId
    # Finds the D365FO user account that this Entra app impersonates
    uri        = (f"{base_url}/data/SysAADClients"
                  f"?$filter=AADClientId eq '{client_id}'"
                  f"&$select=AADClientId,Name,UserId")
    aad_values = _odata_get(uri, token).get("value", [])
    if not aad_values:
        print(f"No SysAADClients entry for clientId: {client_id}", file=sys.stderr)
        sys.exit(1)

    aad_entry = aad_values[0]
    user_id   = aad_entry["UserId"]
    print(f"AAD app '{aad_entry['Name']}' maps to D365FO user: {user_id}")

    # Step 2: SystemUsers → Company
    # The Company field on the D365FO user is the default dataAreaId
    uri         = (f"{base_url}/data/SystemUsers"
                   f"?$filter=UserID eq '{user_id}'"
                   f"&$select=UserID,Company&cross-company=true")
    user_values = _odata_get(uri, token).get("value", [])
    if not user_values or not user_values[0].get("Company"):
        print(f"No default company for user: {user_id}", file=sys.stderr)
        sys.exit(1)

    data_area_id = user_values[0]["Company"].lower()
    print(f"Default company resolved: {data_area_id.upper()}")
    print(f"  dataAreaId: {data_area_id}")

    return {"dataAreaId": data_area_id}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resolve D365FO default company")
    parser.add_argument("--app",  default="", help="Entra app name")
    parser.add_argument("--json", action="store_true", dest="json_out",
                        help="Output result as JSON")
    args = parser.parse_args()

    result = get_company(args.app)
    if args.json_out:
        print(json.dumps(result))
