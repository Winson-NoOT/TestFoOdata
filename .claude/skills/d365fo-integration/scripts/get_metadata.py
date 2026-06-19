"""
D365FO metadata fetcher — downloads $metadata XML and splits it into small,
grep-friendly files stored in a local cache folder.

WHY: The full $metadata from D365FO can be 50+ MB of XML containing thousands
of schema objects. Loading that into a language model on each query is very
expensive in tokens. This script fetches the metadata once, splits it into
per-entity plain-text files and searchable index files — so future queries
can run a single grep or cat to find exactly what they need.

─────────────────────────────────────────────────────────────────────────────
Usage (CLI):
    python get_metadata.py [--app APP_NAME] [--force]
    python get_metadata.py [--app APP_NAME] --search TERM
    python get_metadata.py [--app APP_NAME] --fields-of ENTITY_NAME
    python get_metadata.py [--app APP_NAME] --set-of ENTITY_SET_NAME
    python get_metadata.py [--app APP_NAME] --enum ENUM_NAME
    python get_metadata.py [--app APP_NAME] --action TERM

    --force             Re-fetch even if cached metadata already exists
    --search TERM       Search entity names and field names (case-insensitive)
    --fields-of NAME    Print all properties for a specific entity type
    --set-of NAME       Show which EntityType an OData EntitySet name maps to
    --enum NAME         Show enum member values (e.g. --enum ProdStatus)
    --action TERM       Search action names and their bound entity / parameters

Usage (import):
    from get_metadata import ensure_metadata, get_metadata_dir

    meta_dir = ensure_metadata("EP prod")   # fetches if not cached; returns Path
    # Then use bash grep/cat on files in that dir

─────────────────────────────────────────────────────────────────────────────
Output structure in ~/.d365fo-integration/metadata/{app_name}/:

    fetched_at.txt      — ISO timestamp, source URL, object counts
    index.txt           — One line per EntityType:
                          EntityTypeName<TAB>Set:EntitySetName<TAB>*KeyField,field,...
                          (* prefix = key property)
    entity_sets.txt     — "EntitySetName -> EntityTypeName"  (one per line)
    enums.txt           — One line per EnumType:
                          EnumName<TAB>Member1=Value1,Member2=Value2,...
    actions.txt         — One line per Action:
                          ActionName<TAB>Bound:EntityTypeName<TAB>param:Type,...<TAB>Returns:Type
    by_entity/
        {EntityTypeName}.txt  — Full entity detail: all properties + nav props

─────────────────────────────────────────────────────────────────────────────
Grep cookbook (token-efficient — no file loading needed):

    META=~/.d365fo-integration/metadata/"EP prod"

    # Which entities have a "modified" or "datetime" field?
    grep -i "modif" "$META/index.txt"

    # Find the OData entity for production orders:
    grep -i "production" "$META/index.txt"

    # What EntitySet name do I use in a URL?
    grep "ProductionOrderHeader" "$META/entity_sets.txt"

    # Full field list for a specific entity:
    cat "$META/by_entity/ProductionOrderHeader.txt"

    # What are the values for a ProdStatus field?
    grep "^ProdStatus" "$META/enums.txt"

    # Find all enums related to "status":
    grep -i "status" "$META/enums.txt"

    # What actions can be called on ProductionOrderHeader?
    grep -i "ProductionOrder" "$META/actions.txt"

    # Find all actions that return a string:
    grep "Returns:Edm.String" "$META/actions.txt"
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import shutil
from pathlib import Path

# ── Sibling script resolution ─────────────────────────────────────────────────
# Locate the d365fo-integration scripts dir so sibling imports (get_token etc.)
# work regardless of where this script is run from.

import glob as _glob


def _find_skill_scripts() -> str:
    """Locate the d365fo-integration scripts directory.

    Searches known installation paths for both Cowork and Claude Code
    environments.

    Returns
    -------
    str
        Absolute path to the scripts directory.

    Raises
    ------
    RuntimeError
        If the directory cannot be found in any expected location.
    """
    candidates = (
        list(_glob.glob("/sessions/*/mnt/.claude/skills/d365fo-integration/scripts"))
        + list(_glob.glob("/sessions/*/mnt/claude cowork/d365fo-scripts-updated"))
        + [
            os.path.expanduser("~/.claude/skills/d365fo-integration/scripts"),
            os.path.expanduser(
                "~/.claude/plugins/cache/ai-skills-marketplace"
                "/daxonet/1.0.0/skills/d365fo-integration/scripts"
            ),
            os.path.dirname(os.path.abspath(__file__)),   # same dir as this file
        ]
    )
    found = next((p for p in candidates if os.path.isdir(p)), None)
    if not found:
        raise RuntimeError(
            "d365fo-integration scripts not found. "
            "Ensure the skill is installed or run from the scripts directory."
        )
    return found


_SCRIPTS_DIR = _find_skill_scripts()
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# ── Constants ─────────────────────────────────────────────────────────────────

# OData / EDMX XML namespaces used by D365FO $metadata endpoint
_NS = "http://docs.oasis-open.org/odata/ns/edm"
_EDMX_NS = {
    "edmx": "http://docs.oasis-open.org/odata/ns/edmx",
    "edm":  _NS,
}



def _find_workspace() -> Path | None:
    """Locate the persistent Cowork workspace folder on the users machine.

    Returns None if running outside Cowork (e.g. plain Claude Code terminal).

    The workspace is the folder the user selected in Cowork — it persists
    across sessions on their local machine.  Metadata saved here survives
    sandbox resets.
    """
    import glob as _g
    # Cowork mounts the users selected folder under /sessions/*/mnt/<folder-name>
    candidates = _g.glob("/sessions/*/mnt/*/")
    # Filter to dirs that already contain a .d365fo-integration folder,
    # OR are named like a project workspace (not internal mounts like .claude)
    for c in candidates:
        p = Path(c)
        # Skip the skill/plugin mounts
        if ".claude" in str(p) or "outputs" in str(p) or "uploads" in str(p):
            continue
        return p   # first non-internal mount is the workspace
    return None

# Root cache directory — one sub-directory per Entra app name
METADATA_BASE = Path.home() / ".d365fo-integration" / "metadata"


# ── Public helpers ────────────────────────────────────────────────────────────

def safe_dir_name(app_name: str) -> str:
    """Sanitize an Entra app name into a filesystem-safe directory name.

    Replaces path-unsafe characters with underscores; spaces are kept.

    Parameters
    ----------
    app_name : str
        Environment name (= bws project name, e.g. ``"Shaefer dev3"``).

    Returns
    -------
    str
        Safe directory name (e.g. ``"EP prod"``; ``"Dev/Test"`` → ``"Dev_Test"``).
    """
    return re.sub(r'[<>:"/\\|?*]', "_", app_name)


def get_metadata_dir(app_name: str) -> Path:
    """Return the metadata cache directory Path for an app (does NOT fetch).

    Use ``ensure_metadata()`` when you want automatic fetching on cache miss.

    Parameters
    ----------
    app_name : str
        Friendly Entra app name (e.g. ``"EP prod"``).

    Returns
    -------
    Path
        ``~/.d365fo-integration/metadata/{safe_app_name}/``

    Example
    -------
        from get_metadata import get_metadata_dir
        p = get_metadata_dir("EP prod")
        # grep on p / "index.txt", p / "enums.txt", etc.
    """
    return METADATA_BASE / safe_dir_name(app_name)


def ensure_metadata(app_name: str = "", force: bool = False) -> Path:
    """Ensure metadata is fetched and cached; return the cache directory Path.

    If ``fetched_at.txt`` already exists and ``force`` is False, the cached
    version is reused with no network call.  Otherwise the $metadata endpoint
    is fetched, parsed, and split into the full set of cache files.

    Parameters
    ----------
    app_name : str, optional
        Environment name (= bws project name).  Defaults to the last-used environment.
    force : bool, optional
        Re-fetch even if a cache already exists.  Default ``False``.

    Returns
    -------
    Path
        Absolute path to the metadata cache directory containing:
        ``index.txt``, ``entity_sets.txt``, ``enums.txt``, ``actions.txt``,
        ``fetched_at.txt``, and ``by_entity/*.txt``.

    Example
    -------
        from get_metadata import ensure_metadata

        meta = ensure_metadata("EP prod")
        # grep -i "ProdStatus" meta/"enums.txt"   → enum member values
        # grep -i "production" meta/"index.txt"   → matching entities
    """
    from get_token import get_token
    tok          = get_token(app_name)
    token        = tok["token"]
    base_url     = tok["baseUrl"]
    resolved_app = tok["appName"]

    meta_dir        = get_metadata_dir(resolved_app)
    fetched_at_file = meta_dir / "fetched_at.txt"

    if not force and fetched_at_file.exists():
        first_line = fetched_at_file.read_text(encoding="utf-8").splitlines()[0]
        print("Using cached metadata (fetched: " + first_line + ")")
        print("Cache dir: " + str(meta_dir))
        return meta_dir

    # Cache miss in sandbox — try restoring from the persistent workspace folder
    if not force:
        ws = _find_workspace()
        if ws is not None:
            ws_meta = ws / ".d365fo-integration" / "metadata" / safe_dir_name(resolved_app)
            if (ws_meta / "fetched_at.txt").exists():
                print("Restoring metadata cache from workspace folder...")
                shutil.copytree(str(ws_meta), str(meta_dir), dirs_exist_ok=True)
                first_line = (meta_dir / "fetched_at.txt").read_text(encoding="utf-8").splitlines()[0]
                print("Restored. (fetched: " + first_line + ")")
                print("Cache dir: " + str(meta_dir))
                return meta_dir

    meta_url = base_url + "/data/$metadata"
    print(f"Fetching {meta_url} ...")
    req = urllib.request.Request(
        meta_url, headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        xml_bytes = resp.read()
    print(f"Downloaded {len(xml_bytes):,} bytes.  Parsing and splitting...")

    root = ET.fromstring(xml_bytes.decode("utf-8"))
    _split_and_save(root, meta_dir, base_url, resolved_app)

    # Sync to persistent workspace folder so cache survives session restarts
    ws = _find_workspace()
    if ws is not None:
        ws_meta = ws / ".d365fo-integration" / "metadata" / safe_dir_name(resolved_app)
        ws_meta.mkdir(parents=True, exist_ok=True)
        # Use dirs_exist_ok so we overlay without needing to delete
        # (Windows-mounted workspace does not allow unlink from Linux)
        shutil.copytree(str(meta_dir), str(ws_meta), dirs_exist_ok=True)
        print("Synced to workspace: " + str(ws_meta))
    else:
        print("(No Cowork workspace found — cache is session-only)")

    return meta_dir


# ── Internal: parse and write cache ──────────────────────────────────────────

def _split_and_save(
    root: ET.Element, meta_dir: Path, base_url: str, app_name: str
) -> None:
    """Parse the EDMX root and write all five cache file groups into meta_dir.

    Writes:
      - ``index.txt``        — one searchable line per EntityType
      - ``entity_sets.txt``  — EntitySet → EntityType mapping
      - ``enums.txt``        — one line per EnumType with all member values
      - ``actions.txt``      — one line per Action with bound entity and params
      - ``by_entity/*.txt``  — full property + nav prop detail per EntityType
      - ``fetched_at.txt``   — timestamp and object counts

    Parameters
    ----------
    root : ET.Element
        Parsed root of the $metadata XML document.
    meta_dir : Path
        Target directory (created if it does not exist).
    base_url : str
        D365FO base URL — recorded in fetched_at.txt for traceability.
    app_name : str
        Resolved Entra app name — recorded in fetched_at.txt.
    """
    by_entity_dir = meta_dir / "by_entity"
    by_entity_dir.mkdir(parents=True, exist_ok=True)

    # ── Pass 1: EntityType definitions ───────────────────────────────────────
    entity_types: dict[str, dict] = {}

    for et_elem in root.findall(f".//{{{_NS}}}EntityType"):
        name = et_elem.get("Name", "")
        if not name:
            continue
        key_props = {
            ref.get("Name", "")
            for ref in et_elem.findall(f".//{{{_NS}}}PropertyRef")
        }
        props = [
            {
                "name":     p.get("Name", ""),
                "type":     p.get("Type", ""),
                "nullable": p.get("Nullable", "true"),
                "key":      p.get("Name", "") in key_props,
            }
            for p in et_elem.findall(f"{{{_NS}}}Property")
        ]
        nav_props = [
            {"name": nav.get("Name", ""), "type": nav.get("Type", "")}
            for nav in et_elem.findall(f"{{{_NS}}}NavigationProperty")
        ]
        entity_types[name] = {"props": props, "nav_props": nav_props}

    # ── Pass 2: EntitySet → EntityType mapping ───────────────────────────────
    entity_sets: dict[str, str] = {}
    for es in root.findall(f".//{{{_NS}}}EntitySet"):
        set_name  = es.get("Name", "")
        type_name = es.get("EntityType", "").rsplit(".", 1)[-1]
        if set_name and type_name:
            entity_sets[set_name] = type_name

    type_to_sets: dict[str, list[str]] = {}
    for sn, tn in entity_sets.items():
        type_to_sets.setdefault(tn, []).append(sn)

    # ── Pass 3: EnumType definitions ─────────────────────────────────────────
    # Format per line: EnumName<TAB>Member1=Value1,Member2=Value2,...
    # Grep for the enum name to get all member values, or grep for a value
    # to find which enum it belongs to.
    enum_lines: list[str] = []
    enum_count = 0

    for en in root.findall(f".//{{{_NS}}}EnumType"):
        name = en.get("Name", "")
        if not name:
            continue
        members = [
            f"{m.get('Name', '')}={m.get('Value', '')}"
            for m in en.findall(f"{{{_NS}}}Member")
        ]
        enum_lines.append(f"{name}\t{','.join(members)}")
        enum_count += 1

    (meta_dir / "enums.txt").write_text(
        "\n".join(sorted(enum_lines)), encoding="utf-8"
    )

    # ── Pass 4: Action definitions ───────────────────────────────────────────
    # Format per line:
    #   ActionName<TAB>Bound:EntityTypeName<TAB>param1:Type,...<TAB>Returns:Type
    # Unbound actions have Bound:(none).
    # Grep by action name, by entity type, by param name, or by return type.
    action_lines: list[str] = []
    action_count = 0

    def _short_type(full_type: str) -> str:
        """Strip namespace prefix and Collection() wrapper from an OData type string."""
        t = full_type.strip()
        if t.startswith("Collection(") and t.endswith(")"):
            t = t[len("Collection("):-1]
        return t.rsplit(".", 1)[-1]

    for action in root.findall(f".//{{{_NS}}}Action"):
        name = action.get("Name", "")
        if not name:
            continue

        is_bound    = action.get("IsBound", "false").lower() == "true"
        bound_to    = "(none)"
        params_out  = []

        for i, param in enumerate(action.findall(f"{{{_NS}}}Parameter")):
            pname = param.get("Name", "")
            ptype = _short_type(param.get("Type", ""))
            if i == 0 and is_bound:
                bound_to = ptype
            else:
                params_out.append(pname + ":" + ptype)

        ret_elem    = action.find(f"{{{_NS}}}ReturnType")
        return_type = "(void)"
        if ret_elem is not None:
            rt = ret_elem.get("Type", "")
            return_type = _short_type(rt) if rt else "(void)"

        params_str = ",".join(params_out) if params_out else "(none)"
        action_lines.append(
            f"{name}\tBound:{bound_to}\t{params_str}\tReturns:{return_type}"
        )
        action_count += 1

    (meta_dir / "actions.txt").write_text(
        "\n".join(sorted(action_lines)), encoding="utf-8"
    )

    # ── Write entity_sets.txt ─────────────────────────────────────────────────
    sets_lines = sorted(f"{sn} -> {tn}" for sn, tn in entity_sets.items())
    (meta_dir / "entity_sets.txt").write_text("\n".join(sets_lines), encoding="utf-8")

    # ── Write per-entity files + build index.txt ──────────────────────────────
    index_lines: list[str] = []

    for etype_name, info in sorted(entity_types.items()):
        sets_for_type = type_to_sets.get(etype_name, [])
        set_label     = sets_for_type[0] if sets_for_type else ""

        # index.txt line — key fields prefixed with * for easy grepping
        prop_names = [("*" if p["key"] else "") + p["name"] for p in info["props"]]
        set_info   = f"Set:{set_label}" if set_label else "Set:(none)"
        index_lines.append(f"{etype_name}\t{set_info}\t{','.join(prop_names)}")

        # by_entity/{Name}.txt — full human-readable listing
        out: list[str] = [
            f"Entity:   {etype_name}",
            f"ODataSet: {', '.join(sets_for_type) if sets_for_type else '(not exposed as EntitySet)'}",
            "",
        ]
        if info["props"]:
            out.append("Properties:")
            for p in info["props"]:
                key_tag = "[Key]  " if p["key"] else "       "
                req_tag = " [Required]" if p["nullable"] == "false" else ""
                # Append enum hint for non-Edm types so user knows to check enums.txt
                type_str = p["type"]
                enum_hint = ""
                if type_str.startswith("Microsoft.Dynamics.DataEntities."):
                    short = type_str.rsplit(".", 1)[-1]
                    enum_hint = f"  [enum → grep '{short}' enums.txt]"
                out.append(f"  {key_tag}{p['name']:<55} {type_str}{req_tag}{enum_hint}")
        else:
            out.append("Properties: (none)")

        if info["nav_props"]:
            out.append("")
            out.append("NavigationProperties:")
            for nav in info["nav_props"]:
                out.append(f"  {nav['name']:<55} {nav['type']}")

        (by_entity_dir / f"{etype_name}.txt").write_text(
            "\n".join(out), encoding="utf-8"
        )

    (meta_dir / "index.txt").write_text(
        "\n".join(sorted(index_lines)), encoding="utf-8"
    )

    # ── Write fetched_at.txt ──────────────────────────────────────────────────
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (meta_dir / "fetched_at.txt").write_text(
        "\n".join([
            ts,
            f"Source:   {base_url}/data/$metadata",
            f"App:      {app_name}",
            f"Entities: {len(entity_types)}",
            f"Sets:     {len(entity_sets)}",
            f"Enums:    {enum_count}",
            f"Actions:  {action_count}",
        ]),
        encoding="utf-8",
    )

    print(f"Done.")
    print(f"  {len(entity_types):>5} entity types  → by_entity/*.txt + index.txt")
    print(f"  {len(entity_sets):>5} entity sets   → entity_sets.txt")
    print(f"  {enum_count:>5} enum types    → enums.txt")
    print(f"  {action_count:>5} actions       → actions.txt")
    print(f"Cache dir: {meta_dir}")
    print()
    print("Grep cookbook:")
    print(f'  grep -i "modif"          "{meta_dir}/index.txt"      # entities with modified fields')
    print(f'  grep "^ProdStatus"       "{meta_dir}/enums.txt"      # ProdStatus enum values')
    print(f'  grep -i "ProductionOrder" "{meta_dir}/actions.txt"   # actions on production orders')


# ── CLI query helpers ─────────────────────────────────────────────────────────

def _cmd_search(meta_dir: Path, term: str) -> None:
    """Search entity names and field names in index.txt (case-insensitive).

    Parameters
    ----------
    meta_dir : Path
        Metadata cache directory returned by ``ensure_metadata()``.
    term : str
        Search term matched against entity name, OData set name, and field names.

    Example (CLI)
    -------------
        python get_metadata.py --app "EP prod" --search "modifieddatetime"
        python get_metadata.py --app "EP prod" --search "production order"
    """
    index_file = meta_dir / "index.txt"
    if not index_file.exists():
        print("No index.txt — run without flags first to fetch metadata.", file=sys.stderr)
        sys.exit(1)

    pattern = re.compile(re.escape(term), re.IGNORECASE)
    matches = [l for l in index_file.read_text(encoding="utf-8").splitlines()
               if pattern.search(l)]

    if not matches:
        print(f"No entity/field matches for '{term}'")
        return

    print(f"Found {len(matches)} match(es) for '{term}' in entities/fields:\n")
    for line in matches:
        parts       = line.split("\t", 2)
        entity_name = parts[0]
        set_info    = parts[1] if len(parts) > 1 else ""
        fields_raw  = parts[2] if len(parts) > 2 else ""
        all_fields  = fields_raw.split(",")
        matching    = [f for f in all_fields if pattern.search(f)]
        other_ct    = len(all_fields) - len(matching)
        print(f"  {entity_name}  ({set_info})")
        if matching:
            print(f"    Matching fields: {', '.join(matching)}")
        if other_ct:
            print(f"    (+{other_ct} other fields — see by_entity/{entity_name}.txt)")
        print()


def _cmd_fields_of(meta_dir: Path, entity_name: str) -> None:
    """Print the full property listing for a specific entity type.

    Parameters
    ----------
    meta_dir : Path
        Metadata cache directory returned by ``ensure_metadata()``.
    entity_name : str
        Exact EntityType name (e.g. ``ProductionOrderHeader``).
        Case-insensitive fallback attempted if exact name not found.

    Example (CLI)
    -------------
        python get_metadata.py --app "EP prod" --fields-of ProductionOrderHeader
    """
    by_entity_dir = meta_dir / "by_entity"
    candidate     = by_entity_dir / f"{entity_name}.txt"

    if not candidate.exists():
        ci_matches = [f for f in by_entity_dir.iterdir()
                      if f.stem.lower() == entity_name.lower()]
        if not ci_matches:
            print("Entity not found: " + entity_name, file=sys.stderr)
            print("Hint: run --search to find the correct name.", file=sys.stderr)
            sys.exit(1)
        candidate = ci_matches[0]

    print(candidate.read_text(encoding="utf-8"))


def _cmd_set_of(meta_dir: Path, set_name: str) -> None:
    """Show which EntityType an OData EntitySet name maps to.

    Parameters
    ----------
    meta_dir : Path
        Metadata cache directory returned by ensure_metadata().
    set_name : str
        OData EntitySet name used in URLs (e.g. ProductionOrderHeaders).

    Example (CLI)
    -------------
        python get_metadata.py --app "EP prod" --set-of ProductionOrderHeaders
    """
    sets_file = meta_dir / "entity_sets.txt"
    if not sets_file.exists():
        print("entity_sets.txt not found -- run without flags first.", file=sys.stderr)
        sys.exit(1)

    pattern = re.compile(re.escape(set_name), re.IGNORECASE)
    matches = [l for l in sets_file.read_text(encoding="utf-8").splitlines()
               if pattern.search(l)]
    if matches:
        for m in matches:
            print(m)
    else:
        print("No entity set matching '" + set_name + "' found.")


def _cmd_enum(meta_dir: Path, enum_name: str) -> None:
    """Show all member values for an EnumType (exact or partial match).

    Parameters
    ----------
    meta_dir : Path
        Metadata cache directory returned by ensure_metadata().
    enum_name : str
        EnumType name or partial name (case-insensitive).

    Example (CLI)
    -------------
        python get_metadata.py --app "EP prod" --enum ProdStatus
        python get_metadata.py --app "EP prod" --enum status
    """
    enums_file = meta_dir / "enums.txt"
    if not enums_file.exists():
        print("enums.txt not found -- run without flags first to fetch metadata.", file=sys.stderr)
        sys.exit(1)

    pattern = re.compile(re.escape(enum_name), re.IGNORECASE)
    lines   = enums_file.read_text(encoding="utf-8").splitlines()
    matches = [l for l in lines if pattern.search(l.split("\t")[0])]

    if not matches:
        print("No enum type matching '" + enum_name + "' found.")
        return

    for line in matches:
        parts   = line.split("\t", 1)
        name    = parts[0]
        members = parts[1].split(",") if len(parts) > 1 else []
        print(name + ":")
        for m in members:
            kv = m.split("=", 1)
            if len(kv) == 2:
                print("  " + kv[0].ljust(40) + " = " + kv[1])
            else:
                print("  " + m)
        print()


def _cmd_action(meta_dir: Path, term: str) -> None:
    """Search action names, bound entity types, and parameter names.

    Parameters
    ----------
    meta_dir : Path
        Metadata cache directory returned by ensure_metadata().
    term : str
        Search term matched against full action line (case-insensitive).

    Example (CLI)
    -------------
        python get_metadata.py --app "EP prod" --action ProductionOrder
        python get_metadata.py --app "EP prod" --action "Returns:Edm.String"
    """
    actions_file = meta_dir / "actions.txt"
    if not actions_file.exists():
        print("actions.txt not found -- run without flags first to fetch metadata.", file=sys.stderr)
        sys.exit(1)

    pattern = re.compile(re.escape(term), re.IGNORECASE)
    lines   = actions_file.read_text(encoding="utf-8").splitlines()
    matches = [l for l in lines if pattern.search(l)]

    if not matches:
        print("No actions matching '" + term + "' found.")
        return

    print("Found " + str(len(matches)) + " action(s) matching '" + term + "':\n")
    for line in matches:
        parts  = line.split("\t")
        name   = parts[0] if len(parts) > 0 else "?"
        bound  = parts[1] if len(parts) > 1 else ""
        params = parts[2] if len(parts) > 2 else ""
        ret    = parts[3] if len(parts) > 3 else ""
        print("  " + name)
        print("    " + bound + "   " + ret)
        if params and params != "(none)":
            print("    Params: " + params)
        print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch and cache D365FO $metadata as grep-friendly split files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python get_metadata.py --app "EP prod"
  python get_metadata.py --app "EP prod" --force
  python get_metadata.py --app "EP prod" --search production
  python get_metadata.py --app "EP prod" --fields-of ProductionOrderHeader
  python get_metadata.py --app "EP prod" --set-of ProductionOrderHeaders
  python get_metadata.py --app "EP prod" --enum ProdStatus
  python get_metadata.py --app "EP prod" --action ProductionOrder
        """,
    )
    parser.add_argument("--app",       default="", help="Entra app name (default: last used)")
    parser.add_argument("--force",     action="store_true", help="Re-fetch even if cache exists")
    parser.add_argument("--search",    metavar="TERM",   help="Search entity/field names")
    parser.add_argument("--fields-of", metavar="ENTITY", dest="fields_of",
                        help="Print all fields for a named entity type")
    parser.add_argument("--set-of",    metavar="SET",    dest="set_of",
                        help="Show EntityType that an OData EntitySet maps to")
    parser.add_argument("--enum",      metavar="NAME",
                        help="Show enum member values by name (partial match OK)")
    parser.add_argument("--action",    metavar="TERM",
                        help="Search action names and their bound entity / params")
    args = parser.parse_args()

    if args.search or args.fields_of or args.set_of or args.enum or args.action:
        from get_token import get_token
        tok      = get_token(args.app)
        meta_dir = get_metadata_dir(tok["appName"])
        if not meta_dir.exists():
            print("No cached metadata at " + str(meta_dir), file=sys.stderr)
            print("Run without query flags first to fetch and cache.", file=sys.stderr)
            sys.exit(1)
        if args.search:
            _cmd_search(meta_dir, args.search)
        if args.fields_of:
            _cmd_fields_of(meta_dir, args.fields_of)
        if args.set_of:
            _cmd_set_of(meta_dir, args.set_of)
        if args.enum:
            _cmd_enum(meta_dir, args.enum)
        if args.action:
            _cmd_action(meta_dir, args.action)
        return

    ensure_metadata(args.app, force=args.force)


if __name__ == "__main__":
    main()
