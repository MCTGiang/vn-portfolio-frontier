# Contributing to vn-portfolio-frontier

Thanks for considering a contribution. This project is part of an HUST second-bachelor's degree programme (2025-2027) and follows conventions carried over from its predecessor [`vn-portfolio-optimizer`](https://github.com/MCTGiang/vn-portfolio-optimizer).

## Development setup

**Prerequisites:** Python 3.11+, Git, Docker Desktop, a [Neon Cloud](https://neon.tech) Postgres project (region `ap-southeast-1`), and (recommended) [DBeaver](https://dbeaver.io/) for schema inspection.

```bash
git clone https://github.com/MCTGiang/vn-portfolio-frontier.git
cd vn-portfolio-frontier

python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash
# source .venv/bin/activate        # macOS / Linux

pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env               # then fill in your Neon connection string

pytest -v                           # smoke-test the install
```

## Branch conventions

Semantic prefixes required — the CI matrix and PR template rely on them:

| Prefix       | Use for                                    |
|--------------|--------------------------------------------|
| `feat/`      | New user-facing feature                    |
| `fix/`       | Bug fix                                    |
| `docs/`      | Documentation only                         |
| `test/`      | Adding or modifying tests                  |
| `refactor/`  | Code cleanup without behavior change       |
| `chore/`     | Tooling, config, dependencies              |
| `ci/`        | CI/CD or GitHub Actions changes            |
| `infra/`     | Docker, Neon, dbt, or deployment infra     |
| `polish/`    | Small quality-of-life improvements         |

Descriptive slugs: `test/pytest-fixture-scoping`, **not** `test/day6`.  
Delete branches after merge.

## Commit conventions

[Conventional Commits](https://www.conventionalcommits.org):

```
<type>: <imperative subject, no trailing period>

<optional body — the "why", not the "what">

<optional footer — refs, breaking changes, co-authors>
```

Types mirror the branch prefixes above. Multi-line commits with `git commit -F- << 'EOF' ... EOF` are the norm.

## Pull request workflow

1. Feature branch off `main`
2. Small atomic commits, each Conventional Commits format
3. Verify locally: `pytest -v`, `black --check .`, `ruff check .`
4. Push and open PR: `gh pr create --fill`
5. CI must be green before merge
6. Squash-merge to `main`; `--delete-branch` cleans up

Small doc-only or config changes may go direct to `main`.

## Verification discipline

Carried over from Project 1 — hard-won lessons:

- **Never** claim `X tests pass` in a commit message without a fresh `pytest -v`
- **Never** claim coverage percentages without actual `--cov` output
- **Never** assume an API signature — `grep '^def ' src/module.py` first
- Verify all metrics with evidence before writing to git

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](./LICENSE) covering this project.
