"""
D365FO credential resolver — sources everything from Bitwarden Secrets
Manager via the ``bws`` CLI. There is no config.json anymore.

Model
-----
- Each bws **project** = one D365FO environment. The project *name* is the
  friendly environment / app name (e.g. ``"Shaefer dev3"``).
- Within a project, **secrets** hold the Entra app's tenant id, client (app)
  id, client secret, and the environment base URL.
- The base URL is normally stored in a secret's ``note`` (per the team's
  convention), but may instead appear as a secret value.

Secrets are NOT assumed to follow a fixed naming scheme. Keys are matched
heuristically (``tenant`` / ``secret`` / ``id`` …). When the mapping is
ambiguous or incomplete, ``resolve_creds`` raises a descriptive error that
dumps every secret key + note so the caller (the agent) can inspect and
resolve manually — e.g. by asking the user which secret is which.

Auth
----
Requires ``BWS_ACCESS_TOKEN`` in the environment (a machine-account access
token). The ``bws`` binary must be on PATH.

Usage (import)
--------------
    from bws_creds import resolve_creds, list_environments, list_secrets

    envs = list_environments()                 # [{"id", "name"}, ...]
    c    = resolve_creds("Shaefer dev3")        # by name (or id, or "")
    # c -> {"appName", "tenantId", "clientId", "clientSecret", "baseUrl"}

Usage (CLI)
-----------
    python3 bws_creds.py envs                   # list environments
    python3 bws_creds.py secrets "Shaefer dev3" # list a project's secrets
    python3 bws_creds.py resolve "Shaefer dev3" # resolve creds (secret masked)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

STATE_DIR     = Path.home() / ".d365fo-integration"
LAST_ENV_FILE = STATE_DIR / "last-env.txt"


# ── bws CLI wrapper ────────────────────────────────────────────────────────────

def _bws(*args: str) -> list | dict:
    """Run a ``bws`` command and return parsed JSON. Raises on any failure."""
    if not os.environ.get("BWS_ACCESS_TOKEN"):
        raise RuntimeError(
            "BWS_ACCESS_TOKEN is not set. The bws CLI needs a machine-account "
            "access token in the environment to read secrets."
        )
    proc = subprocess.run(
        ["bws", *args], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"`bws {' '.join(args)}` failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return json.loads(proc.stdout)


# ── Discovery ──────────────────────────────────────────────────────────────────

def list_environments() -> list[dict]:
    """List D365FO environments (one per bws project).

    Returns
    -------
    list[dict]
        ``[{"id": str, "name": str}, ...]`` — ``name`` is the friendly env name.
    """
    return [{"id": p["id"], "name": p["name"]} for p in _bws("project", "list")]


def list_secrets(project_id: str) -> list[dict]:
    """Return all secrets for a project (raw bws objects: key/value/note/...)."""
    return _bws("secret", "list", project_id)


# ── Heuristics (tolerant — structure is not guaranteed) ─────────────────────────

def _match(secrets: list[dict], *keywords: str, exclude: tuple = ()) -> dict | None:
    """First secret whose key contains any keyword and none of `exclude`."""
    for s in secrets:
        k = s.get("key", "").lower()
        if any(w in k for w in keywords) and not any(x in k for x in exclude):
            return s
    return None


def _looks_like_url(s: str) -> bool:
    if not s:
        return False
    low = s.lower()
    return "dynamics.com" in low or low.startswith("http") or low.startswith("www.")


def _normalize_url(s: str) -> str:
    s = s.strip().rstrip("/")
    if not s.lower().startswith("http"):
        s = "https://" + s
    return s


def _find_base_url(secrets: list[dict]) -> str | None:
    # Prefer a note that looks like a URL (team convention), then a value.
    for field in ("note", "value"):
        for s in secrets:
            if _looks_like_url(s.get(field, "")):
                return _normalize_url(s[field])
    return None


def _resolve_env(env: str, envs: list[dict]) -> dict:
    """Pick the target project. `env` may be a name (case-insensitive) or id."""
    if env:
        for e in envs:
            if env == e["id"] or env.lower() == e["name"].lower():
                return e
        names = ", ".join(repr(e["name"]) for e in envs)
        raise RuntimeError(f"Environment {env!r} not found. Available: {names}")
    # No env given — try last used, then sole project.
    last = get_last_env()
    if last:
        for e in envs:
            if e["name"] == last:
                return e
    if len(envs) == 1:
        return envs[0]
    names = ", ".join(repr(e["name"]) for e in envs)
    raise RuntimeError(
        f"Multiple environments available and none selected — pick one: {names}"
    )


# ── Last-used persistence (replaces lastUsedEntraApp) ───────────────────────────

def get_last_env() -> str:
    try:
        return LAST_ENV_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_last_env(name: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LAST_ENV_FILE.write_text(name, encoding="utf-8")


# ── Main resolver ──────────────────────────────────────────────────────────────

def resolve_creds(env: str = "") -> dict:
    """Resolve full credentials for a D365FO environment from bws.

    Parameters
    ----------
    env : str, optional
        Environment (bws project) name or id. When omitted, resolves to the
        last-used environment, or the sole project if only one exists.

    Returns
    -------
    dict
        ``{"appName", "tenantId", "clientId", "clientSecret", "baseUrl"}``

    Raises
    ------
    RuntimeError
        If no environment can be selected, or if any credential cannot be
        mapped. The message lists every secret key + note so the caller can
        inspect and resolve the ambiguity manually.
    """
    envs = list_environments()
    if not envs:
        raise RuntimeError("No bws projects found — no D365FO environments configured.")

    proj    = _resolve_env(env, envs)
    secrets = list_secrets(proj["id"])

    tenant = _match(secrets, "tenant")
    secret = _match(secrets, "secret")
    client = _match(secrets, "client id", "app id", "clientid", "client",
                    exclude=("tenant", "secret"))
    if client is None:
        # Fallback: any id-like key that isn't the tenant or the secret.
        client = _match(secrets, "id", exclude=("tenant", "secret"))
    base_url = _find_base_url(secrets)

    missing = [n for n, v in (
        ("tenantId", tenant), ("clientId", client),
        ("clientSecret", secret), ("baseUrl", base_url),
    ) if not v]
    if missing:
        dump = "\n".join(
            f"  - key={s.get('key','')!r}  note={s.get('note','')!r}"
            for s in secrets
        )
        raise RuntimeError(
            f"Could not map {', '.join(missing)} for environment {proj['name']!r}.\n"
            f"Secrets in this project:\n{dump}\n"
            "Secret naming is not fixed — inspect the keys/notes above and resolve "
            "the correct secret for each missing field (ask the user if unclear)."
        )

    save_last_env(proj["name"])
    return {
        "appName":      proj["name"],
        "tenantId":     tenant["value"],
        "clientId":     client["value"],
        "clientSecret": secret["value"],
        "baseUrl":      _normalize_url(base_url),
    }


# ── CLI ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "envs"
    arg = sys.argv[2] if len(sys.argv) > 2 else ""

    try:
        if cmd == "envs":
            print(json.dumps(list_environments(), indent=2))
        elif cmd == "secrets":
            envs = list_environments()
            proj = _resolve_env(arg, envs)
            rows = [{"key": s["key"], "note": s["note"]} for s in list_secrets(proj["id"])]
            print(json.dumps({"env": proj["name"], "secrets": rows}, indent=2))
        elif cmd == "resolve":
            c = resolve_creds(arg)
            masked = dict(c)
            masked["clientSecret"] = c["clientSecret"][:4] + "…[masked]"
            print(json.dumps(masked, indent=2))
        else:
            print(f"Unknown command: {cmd!r}. Use: envs | secrets <env> | resolve <env>",
                  file=sys.stderr)
            sys.exit(2)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
