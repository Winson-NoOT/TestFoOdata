# Credential Resolution via bws (Bitwarden Secrets Manager)

All D365FO credentials come from **Bitwarden Secrets Manager** through the
`bws` CLI. There is no `config.json` — nothing is stored on disk except a
short-lived token cache.

---

## Model

- Each **bws project** = one D365FO environment. The project **name** is the
  friendly environment name (e.g. `Shaefer dev3`, `VSTECS`).
- Within a project, **secrets** hold the Entra app's:
  - **tenant id**
  - **client (app) id**
  - **client secret**
  - **base URL** — by team convention stored in a secret's **`note`** field
    (it may also appear as a secret value).

> **Secret naming is NOT fixed.** Keys vary across projects (e.g. `app id`
> vs `barcode app id`). Match by intent, not by exact key name. When mapping
> is ambiguous, inspect the secrets and ask the user — never guess silently.

---

## Prerequisites

- `BWS_ACCESS_TOKEN` must be set in the environment (machine-account token).
  It already is in this environment per `AGENTS.md`.
- `bws` must be on PATH. Verify once if unsure: `bws --version`.

If `BWS_ACCESS_TOKEN` is missing or `bws` is not found → tell the user and
stop. There is no fallback credential source.

---

## Normal path — let the scripts resolve

In almost all cases you do **not** call `bws` by hand. `get_token.py` →
`bws_creds.resolve_creds()` resolves everything automatically. Just call
`init_session(env_name)` (see `d365-scripts.md`). The helper:

1. Lists projects (`bws project list`) → environments.
2. Selects the project by the name you pass (or last-used / sole project).
3. Lists its secrets and maps tenant / client / secret / base URL using
   tolerant heuristics.
4. Fetches and caches the token.

`resolve_creds` saves the chosen environment to
`~/.d365fo-integration/last-env.txt` so the next call can default to it.

---

## Selecting an environment

- **User named an environment** (or it was established earlier this session) →
  pass that name to `init_session("Name")`.
- **Not specified** → list environments and let the user pick:

  ```bash
  python3 <scripts>/bws_creds.py envs
  ```

  Present the names with `ASK_TOOL`. If only one project exists, use it
  directly. **STOP and wait** for the selection — do not draft queries first.

---

## When automatic mapping fails

If `resolve_creds` cannot confidently map a field, it raises an error that
lists every secret key + note in the project. When that happens — or any time
the structure looks unusual — inspect the secrets yourself:

```bash
python3 <scripts>/bws_creds.py secrets "Shaefer dev3"
```

This prints each secret's `key` and `note` (values are never printed). Decide
which secret is the tenant id, client id, client secret, and which `note`
holds the base URL. If it is still unclear, use `ASK_TOOL` to ask the user to
identify the right secret for each field before proceeding.

Raw single-secret access if you need a specific value:

```bash
bws secret get <secret-id>
```

---

## Verifying

Confirm a live token fetches for the selected environment:

```bash
python3 <scripts>/get_token.py --app "Shaefer dev3"
```

A successful run prints the base URL and token-ready line. Any error here
means a credential is wrong or mis-mapped — fix it before running queries.

If `get_token.py` is unavailable, see `d365-token-manual.md` (it also sources
credentials from `bws`).

---

## When to load this file

Load when:
- Resolving which environment / credentials to use at the start of a task.
- The env-gate needs to fetch a token and the environment is unknown.
- `resolve_creds` raised a mapping error and you need to inspect secrets.
