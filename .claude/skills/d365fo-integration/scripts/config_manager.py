"""
Config manager for d365fo-integration.

Manages ~/.d365fo-integration/config.json (or the path in
D365FO_INTEGRATION_CONFIG env var).

Usage
-----
python3 config_manager.py check
python3 config_manager.py list
python3 config_manager.py create --app NAME --tenant T --client-id C --secret S --url U
python3 config_manager.py add    --app NAME --tenant T --client-id C --secret S --url U
python3 config_manager.py edit   --app NAME --field FIELD --value VALUE
python3 config_manager.py remove --app NAME

Commands
--------
check   Print whether config exists and list app names. Exit 0 = exists, 1 = missing.
list    Print all app entries (name, baseUrl, last-used marker).
create  Create a brand-new config with one app. Fails if config already exists.
add     Add a new app entry to an existing config. Fails if app name already present.
edit    Update one field of an existing app entry.
        FIELD must be one of: tenantId, clientId, clientSecret, baseUrl
remove  Remove an app entry. Clears lastUsedEntraApp if it pointed to that app.

All write commands print a confirmation line on success.
"""

import argparse
import json
import os
import sys
from pathlib import Path


# ── Helpers ──────────────────────────────────────────────────────────────────

def config_path() -> Path:
    env = os.environ.get("D365FO_INTEGRATION_CONFIG")
    return Path(env) if env else Path.home() / ".d365fo-integration" / "config.json"


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def app_entry(args) -> dict:
    return {
        "tenantId":     args.tenant,
        "clientId":     args.client_id,
        "clientSecret": args.secret,
        "baseUrl":      args.url.rstrip("/"),
    }


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_check(args, path: Path) -> int:
    if not path.exists():
        print(f"Config not found: {path}")
        return 1
    config = load_config(path)
    apps = list(config.get("entraApps", {}).keys())
    last = config.get("lastUsedEntraApp", "")
    print(f"Config found: {path}")
    print(f"Apps: {', '.join(apps) if apps else '(none)'}")
    print(f"Last used: {last or '(none)'}")
    return 0


def cmd_list(args, path: Path) -> int:
    if not path.exists():
        print("Config not found. Run 'create' first.")
        return 1
    config = load_config(path)
    apps = config.get("entraApps", {})
    last = config.get("lastUsedEntraApp", "")
    if not apps:
        print("No apps configured.")
        return 0
    for name, entry in apps.items():
        marker = " (last used)" if name == last else ""
        print(f"  {name}{marker}")
        print(f"    baseUrl:  {entry.get('baseUrl', '')}")
        print(f"    tenantId: {entry.get('tenantId', '')}")
        print(f"    clientId: {entry.get('clientId', '')}")
    return 0


def cmd_create(args, path: Path) -> int:
    if path.exists():
        print(f"Config already exists: {path}")
        print("Use 'add' to append a new app, or 'edit' to update an existing one.")
        return 1
    config = {
        "lastUsedEntraApp": args.app,
        "entraApps": {args.app: app_entry(args)},
    }
    save_config(path, config)
    print(f"Config created: {path}")
    print(f"App added: {args.app}")
    return 0


def cmd_add(args, path: Path) -> int:
    if not path.exists():
        print(f"Config not found: {path}")
        print("Use 'create' to create a new config first.")
        return 1
    config = load_config(path)
    apps = config.setdefault("entraApps", {})
    if args.app in apps:
        print(f"App '{args.app}' already exists. Use 'edit' to update it.")
        return 1
    apps[args.app] = app_entry(args)
    if not config.get("lastUsedEntraApp"):
        config["lastUsedEntraApp"] = args.app
    save_config(path, config)
    print(f"App added: {args.app}")
    return 0


def cmd_edit(args, path: Path) -> int:
    valid_fields = {"tenantId", "clientId", "clientSecret", "baseUrl"}
    if args.field not in valid_fields:
        print(f"Invalid field '{args.field}'. Must be one of: {', '.join(sorted(valid_fields))}")
        return 1
    if not path.exists():
        print(f"Config not found: {path}")
        return 1
    config = load_config(path)
    apps = config.get("entraApps", {})
    if args.app not in apps:
        print(f"App '{args.app}' not found. Available: {', '.join(apps.keys())}")
        return 1
    value = args.value
    if args.field == "baseUrl":
        value = value.rstrip("/")
    apps[args.app][args.field] = value
    save_config(path, config)
    print(f"Updated {args.app}.{args.field}")
    return 0


def cmd_remove(args, path: Path) -> int:
    if not path.exists():
        print(f"Config not found: {path}")
        return 1
    config = load_config(path)
    apps = config.get("entraApps", {})
    if args.app not in apps:
        print(f"App '{args.app}' not found. Available: {', '.join(apps.keys())}")
        return 1
    del apps[args.app]
    if config.get("lastUsedEntraApp") == args.app:
        config["lastUsedEntraApp"] = next(iter(apps), "")
    save_config(path, config)
    print(f"App removed: {args.app}")
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Manage ~/.d365fo-integration/config.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="Check whether config exists")
    sub.add_parser("list",  help="List all configured apps")

    def add_app_args(parser):
        parser.add_argument("--app",       required=True, metavar="NAME",  help="Friendly app name (config key)")
        parser.add_argument("--tenant",    required=True, metavar="GUID",  help="Azure AD tenant ID")
        parser.add_argument("--client-id", required=True, metavar="GUID",  help="Entra app client ID", dest="client_id")
        parser.add_argument("--secret",    required=True, metavar="VALUE", help="Client secret value")
        parser.add_argument("--url",       required=True, metavar="URL",   help="D365FO base URL (no trailing slash)")

    add_app_args(sub.add_parser("create", help="Create new config with first app"))
    add_app_args(sub.add_parser("add",    help="Add app to existing config"))

    p_edit = sub.add_parser("edit", help="Edit one field of an existing app")
    p_edit.add_argument("--app",   required=True, metavar="NAME",  help="App name to edit")
    p_edit.add_argument("--field", required=True, metavar="FIELD", help="Field: tenantId | clientId | clientSecret | baseUrl")
    p_edit.add_argument("--value", required=True, metavar="VALUE", help="New value")

    p_remove = sub.add_parser("remove", help="Remove an app from config")
    p_remove.add_argument("--app", required=True, metavar="NAME", help="App name to remove")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    path = config_path()

    dispatch = {
        "check":  cmd_check,
        "list":   cmd_list,
        "create": cmd_create,
        "add":    cmd_add,
        "edit":   cmd_edit,
        "remove": cmd_remove,
    }
    sys.exit(dispatch[args.command](args, path))


if __name__ == "__main__":
    main()
