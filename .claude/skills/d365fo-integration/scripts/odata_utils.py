"""
D365FO OData utilities — shared helpers used across all D365FO scripts and queries.

Import these instead of writing boilerplate in every query block:

    import glob, os, sys, json
    _p = glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts") + \
         [os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
          os.path.expanduser("~/.claude/plugins/cache/ai-skills-marketplace/daxonet/1.0.0/skills/d365fo-integration/scripts")]
    sys.path.insert(0, next(p for p in _p if os.path.isdir(p)))
    from init import init_session
    from odata_utils import odata_get

    s    = init_session("EP prod")
    data = odata_get(f"{s['baseUrl']}/data/Entity?$filter=...", s["token"])
    print(json.dumps(data["value"], indent=2))
"""
from __future__ import annotations

import glob
import json
import os
import urllib.request
from urllib.parse import quote, urlparse, urlunparse


# ── Path resolution ───────────────────────────────────────────────────────────

def find_skill_scripts() -> str:
    """Return the d365fo-integration scripts directory path.

    Searches all known installation locations so imports work in both the
    Cowork desktop app (session mount) and Claude Code (CLI).

    Returns
    -------
    str
        Absolute path to the scripts directory that contains this file.

    Raises
    ------
    RuntimeError
        If the scripts directory cannot be found in any expected location.

    Example
    -------
        from odata_utils import find_skill_scripts
        import sys
        sys.path.insert(0, find_skill_scripts())   # then import siblings
    """
    candidates = list(glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts"))
    candidates += [
        os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
        os.path.expanduser(
            "~/.claude/plugins/cache/ai-skills-marketplace"
            "/daxonet/1.0.0/skills/d365fo-integration/scripts"
        ),
    ]
    found = next((p for p in candidates if os.path.isdir(p)), None)
    if not found:
        raise RuntimeError(
            "d365fo-integration scripts not found — check skill installation"
        )
    return found


# ── URL safety ────────────────────────────────────────────────────────────────

def safe_url(uri: str) -> str:
    """Percent-encode spaces and control characters in an OData query string.

    Python 3.10+ raises ``InvalidURL`` for raw spaces in ``$filter`` expressions
    (e.g. ``dataAreaId eq 'ep'``).  This function encodes only the query
    component of the URL, keeping all OData punctuation
    (``$``, ``=``, ``&``, ``'``, ``(``, ``)``, etc.) intact.

    Parameters
    ----------
    uri : str
        Full OData URL, possibly containing unencoded spaces in the query string.

    Returns
    -------
    str
        URL with the query component safely percent-encoded.

    Example
    -------
        from odata_utils import safe_url

        raw = "https://env.dynamics.com/data/SalesOrders?$filter=dataAreaId eq 'ep'"
        safe = safe_url(raw)   # spaces in query string are encoded
    """
    p = urlparse(uri)
    encoded_query = quote(p.query, safe="$=&,'\"()/!~.-_*+@")
    return urlunparse(p._replace(query=encoded_query))


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def odata_get(uri: str, token: str) -> dict:
    """Authenticated OData GET request.

    Applies ``safe_url`` automatically before sending the request, so you can
    pass raw OData URLs with unencoded spaces in ``$filter`` without worrying
    about Python 3.10+ URL encoding issues.

    Parameters
    ----------
    uri : str
        Full OData URL (e.g. ``{baseUrl}/data/SalesOrderHeaders?$filter=...``).
        Spaces are automatically encoded; all OData operators are preserved.
    token : str
        Bearer token string from ``get_token()`` or ``init_session()``.

    Returns
    -------
    dict
        Parsed JSON response body.  For collection responses, call
        ``["value"]`` on the result to get the rows list.

    Example
    -------
        from odata_utils import odata_get

        data = odata_get(
            f"{base_url}/data/SalesOrderHeaders?$filter=dataAreaId eq 'ep'&$top=5",
            token
        )
        for row in data["value"]:
            print(row["SalesOrderNumber"])
    """
    req = urllib.request.Request(
        safe_url(uri), headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def odata_post(uri: str, token: str, payload: dict) -> dict:
    """Authenticated OData POST (create a new record).

    Parameters
    ----------
    uri : str
        EntitySet URL without a key (e.g. ``{baseUrl}/data/SalesOrderHeaders``).
    token : str
        Bearer token string.
    payload : dict
        Fields to set on the new record.  Only include writable fields.

    Returns
    -------
    dict
        Parsed JSON of the newly created record as returned by D365FO.

    Example
    -------
        from odata_utils import odata_post

        new_record = odata_post(
            f"{base_url}/data/SalesOrderHeaders",
            token,
            {"SalesOrderNumber": "SO-001", "dataAreaId": "ep", ...}
        )
        print(new_record["SalesOrderNumber"])
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        safe_url(uri),
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def odata_patch(uri: str, token: str, payload: dict, etag: str = "*") -> None:
    """Authenticated OData PATCH (update an existing record).

    Parameters
    ----------
    uri : str
        Entity URL with the record key, e.g.
        ``{baseUrl}/data/SalesOrderHeaders(SalesOrderNumber='SO-001',dataAreaId='ep')``.
    token : str
        Bearer token string.
    payload : dict
        Fields to update.  Only include the fields you want to change.
    etag : str, optional
        ETag for optimistic concurrency.  Default ``"*"`` bypasses the check.
        Pass the ``@odata.etag`` value from a prior GET to enforce it.

    Returns
    -------
    None
        D365FO returns HTTP 204 No Content on success; raises on HTTP error.

    Example
    -------
        from odata_utils import odata_patch

        odata_patch(
            f"{base_url}/data/SalesOrderHeaders(SalesOrderNumber='SO-001',dataAreaId='ep')",
            token,
            {"SalesStatus": "Invoiced"}
        )
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        safe_url(uri),
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "If-Match": etag,
        },
        method="PATCH",
    )
    with urllib.request.urlopen(req) as resp:
        resp.read()  # consume response (HTTP 204 No Content)


def odata_delete(uri: str, token: str, etag: str = "*") -> None:
    """Authenticated OData DELETE (remove a record).

    Parameters
    ----------
    uri : str
        Entity URL with the record key, e.g.
        ``{baseUrl}/data/SalesOrderHeaders(SalesOrderNumber='SO-001',dataAreaId='ep')``.
    token : str
        Bearer token string.
    etag : str, optional
        ETag for optimistic concurrency.  Default ``"*"`` bypasses the check.

    Returns
    -------
    None
        D365FO returns HTTP 204 No Content on success; raises on HTTP error.

    Example
    -------
        from odata_utils import odata_delete

        odata_delete(
            f"{base_url}/data/SalesOrderHeaders(SalesOrderNumber='SO-001',dataAreaId='ep')",
            token
        )
    """
    req = urllib.request.Request(
        safe_url(uri),
        headers={"Authorization": f"Bearer {token}", "If-Match": etag},
        method="DELETE",
    )
    with urllib.request.urlopen(req) as resp:
        resp.read()
