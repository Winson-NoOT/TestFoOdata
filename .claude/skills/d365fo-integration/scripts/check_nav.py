"""
D365FO navigation property checker — inspects $metadata for an entity's
navigation properties (determines if $expand is available).

Usage (CLI):
    python check_nav.py --entity ENTITY_NAME [--app APP_NAME]

Usage (import):
    from check_nav import check_nav
    check_nav("BillOfMaterialsLinesV3", token="...", base_url="...")
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# OData / EDMX namespaces used in D365FO $metadata
_EDMX_NS = {"edmx": "http://docs.oasis-open.org/odata/ns/edmx",
             "edm":  "http://docs.oasis-open.org/odata/ns/edm"}


def _find_entity_type(root: ET.Element, name: str):
    """Search the parsed $metadata XML for an EntityType by exact name.

    Parameters
    ----------
    root : ET.Element
        Root element of the parsed EDMX $metadata XML document.
    name : str
        Exact EntityType name to search for (e.g. ``"BillOfMaterialsLinesV3"``).

    Returns
    -------
    ET.Element or None
        The ``<EntityType>`` element if found, otherwise ``None``.

    Example
    -------
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_text)
        et = _find_entity_type(root, "ProductionOrder")
        if et is None:
            print("Not found")
    """
    for et in root.findall(".//edm:EntityType", _EDMX_NS):
        if et.get("Name") == name:
            return et
    return None


def check_nav(entity: str, app_name: str = "",
              token: str = "", base_url: str = "") -> None:
    """Print all navigation properties available on a D365FO entity type.

    Fetches ``$metadata`` from the D365FO endpoint and parses it to find
    ``<NavigationProperty>`` elements on the requested entity.  These are the
    names you can use in ``$expand=NavPropName`` queries to join related data
    server-side in a single API call.

    Parameters
    ----------
    entity : str
        EntityType name to inspect (e.g. ``"BillOfMaterialsLinesV3"``).
        If not found by exact name, the singular form is tried automatically.
    app_name : str, optional
        Friendly Entra app name.  Defaults to ``lastUsedEntraApp``.
    token : str, optional
        Existing bearer token.  If empty, ``get_token`` is called automatically.
        Pass the token from ``init_session()`` to avoid a redundant token fetch.
    base_url : str, optional
        D365FO base URL.  If empty, resolved from config via ``get_token``.

    Returns
    -------
    None
        Prints to stdout.  If navigation properties exist, lists their names
        and target types.  If none, recommends using ``$batch`` instead.

    Example
    -------
        from init import init_session
        from check_nav import check_nav

        s = init_session("EP prod")
        check_nav("BillOfMaterialsLinesV3", token=s["token"], base_url=s["baseUrl"])
        # If a NavigationProperty is listed → use its Name in $expand
        # If none listed → use $batch to combine two separate queries
    """
    if not token or not base_url:
        from get_token import get_token
        result   = get_token(app_name)
        token    = result["token"]
        base_url = result["baseUrl"]

    print(f"Checking $metadata for entity: {entity}\n")

    meta_url = f"{base_url}/data/$metadata"
    req      = urllib.request.Request(
        meta_url, headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req) as resp:
        xml_data = resp.read().decode("utf-8")

    root = ET.fromstring(xml_data)

    # Try exact name first, then singular fallback (strip trailing 's')
    entity_type = _find_entity_type(root, entity)
    if entity_type is None:
        singular    = entity.rstrip("s")
        entity_type = _find_entity_type(root, singular)

    if entity_type is None:
        print(f"Entity '{entity}' not found in $metadata. "
              f"Try the singular form or verify the entity name.", file=sys.stderr)
        sys.exit(1)

    nav_props = entity_type.findall("edm:NavigationProperty", _EDMX_NS)
    if not nav_props:
        print(f"No navigation properties found on '{entity}'.")
        print("Recommendation: use $batch to combine header + line queries.")
    else:
        print(f"Navigation properties on '{entity}':")
        for nav in nav_props:
            print(f"  Name : {nav.get('Name')}")
            print(f"  Type : {nav.get('Type')}")
            print()
        print("Use a nav property Name in $expand to join server-side.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check D365FO entity nav properties")
    parser.add_argument("--entity", required=True,
                        help="Entity name (e.g. BillOfMaterialsLinesV3)")
    parser.add_argument("--app",    default="", help="Entra app name")
    args = parser.parse_args()
    check_nav(args.entity, args.app)
