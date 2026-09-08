# Development environment setup

Step-by-step guide for a fresh contributor (or a fresh laptop). Written for **Windows + Git Bash** which is the maintainer's environment; macOS/Linux notes marked where they differ.

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| **Python** | 3.11+ (3.13 recommended, matches maintainer local) | [python.org](https://www.python.org/downloads/) or `winget install Python.Python.3.13` |
| **Git** | 2.30+ | [git-scm.com](https://git-scm.com/downloads) — installer bundles Git Bash on Windows |
| **GitHub CLI** | 2.90+ | `winget install GitHub.cli` |
| **Docker Desktop** | Latest | [docker.com](https://www.docker.com/products/docker-desktop) — needed from Phase 3 |
| **DBeaver Community** | Latest | [dbeaver.io](https://dbeaver.io/download/) — recommended for schema inspection |
| **Neon Cloud account** | Free tier | [neon.tech](https://neon.tech) — sign in with GitHub |

## Clone and install

Open **Git Bash** (Windows) or your terminal (macOS/Linux). Choose a project directory:

```bash
cd /d/Projects            # Windows Git Bash path convention
# cd ~/Projects           # macOS / Linux

git clone https://github.com/MCTGiang/vn-portfolio-frontier.git
cd vn-portfolio-frontier
```

## Create a virtualenv and install the package

Editable install pulls in runtime deps (pandas, scipy, streamlit, ...) plus dev deps (pytest, black, ruff, jupyter). First install takes ~5–10 minutes depending on your connection.

```bash
python -m venv .venv
source .venv/Scripts/activate     # Windows Git Bash
# source .venv/bin/activate       # macOS / Linux

python -m pip install --upgrade pip
pip install -e ".[dev]"
```

**Verify** — should see `(.venv)` in your prompt and `pip list` should include `vn-portfolio-frontier` at version `0.1.0`.

## Configure the Neon connection

Copy the env template and fill in your connection string:

```bash
cp .env.example .env
```

Then edit `.env` (any text editor) and paste your Neon connection string:

```
NEON_DATABASE_URL="postgresql://portfolio_owner:npg_YOUR_PASSWORD@ep-XXX-XXX.ap-southeast-1.aws.neon.tech/portfolio?sslmode=require"
```

**Never commit `.env`** — it is git-ignored by design. If you need the connection string on a different machine, retrieve it fresh from the [Neon console](https://console.neon.tech).

**Get your connection string:**
1. Open your Neon project dashboard
2. Left sidebar → **Connection Details**
3. Copy the `postgresql://` URI (make sure `sslmode=require` is included)

## Run the tests

```bash
pytest -v
```

Expected on a clean install (Phase 1 baseline):

```
tests/test_smoke.py::test_package_importable PASSED
tests/test_smoke.py::test_version_is_nonempty_string PASSED
tests/test_smoke.py::test_sample_tickers_fixture_yields_list PASSED

============ 3 passed in 0.17s ============
```

**100% coverage** on the tiny `src/vn_portfolio_frontier/__init__.py` — expected to drop as feature code lands.

## Format and lint

Run before every commit:

```bash
black .              # format in place
ruff check .         # lint
ruff check --fix .   # lint + auto-fix simple issues
```

CI (GitHub Actions) runs both in `--check` mode on every PR — if formatting drifts, CI fails.

## Common tasks

**Update dependencies** (when `pyproject.toml` changes on `main`):
```bash
git pull origin main
pip install -e ".[dev]"
```

**Start a feature branch:**
```bash
git checkout main
git pull origin main
git checkout -b feat/your-feature-slug
# ... work, commit ...
git push -u origin feat/your-feature-slug
gh pr create --fill
```

See [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for branch naming and commit conventions.

**Run pytest by marker** (once features land):
```bash
pytest -v -m unit          # only fast unit tests (< 5s)
pytest -v -m integration   # tests hitting Neon or external APIs
pytest -v -m "not slow"    # everything except > 5s tests
```

**Inspect Neon schema** (once Phase 2 lands):
1. Open DBeaver
2. New connection → PostgreSQL
3. Paste connection string from `.env`
4. Test connection → Finish
5. Left panel: `portfolio` → Schemas → `public` → Tables

## Troubleshooting

**`pip install` hangs on "Collecting yfinance"** — pip is backtracking through versions. Wait 1–2 min. If it truly hangs > 5 min, `Ctrl+C` and re-run — sometimes a cached wheel unblocks it.

**`bash: gh: command not found`** after installing GitHub CLI on Windows — PATH not refreshed. In current shell:
```bash
export PATH="/c/Program Files/GitHub CLI:$PATH"
```
Permanent fix: close and reopen Git Bash from Start menu (not the same window).

**Bracketed paste artifacts** (`[200~` prefix in commands) — Git Bash paste mode conflict. Add to `~/.bashrc`:
```bash
bind 'set enable-bracketed-paste off'
```

**`ERROR: Failed to build psycopg2`** — you have `psycopg2` (source) not `psycopg2-binary` in your env. Uninstall + reinstall:
```bash
pip uninstall psycopg2 psycopg2-binary -y
pip install psycopg2-binary
```

**Neon connection times out first query, works second query** — expected behavior. Neon "scales to zero" after ~5 min idle. First query wakes it up (1–3 s). See [ADR-002](./architecture.md#adr-002-neon-cloud-postgresql-as-primary-database).

## Further reading

- [`architecture.md`](./architecture.md) — Why the stack is what it is
- [`roadmap.md`](./roadmap.md) — Phase timeline
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — How to contribute
- [Project 1 setup guide](https://github.com/MCTGiang/vn-portfolio-optimizer/blob/main/docs/setup.md) — Predecessor project reference
