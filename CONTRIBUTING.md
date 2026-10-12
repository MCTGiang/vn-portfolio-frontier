# Contributing to vn-portfolio-frontier

This project is a HUST undergraduate thesis implementation (Project 2 - Efficient
Frontier Portfolio Optimization with Vietnamese Financial News Sentiment Signals).
It is public on GitHub. The guidelines below apply to any change that lands on
`main`.

## Language convention

All code artifacts in this repository use **English only**:

- Python docstrings and inline comments
- SQL comments and column descriptions
- Variable, function, class, and module names
- Commit messages and PR titles / bodies
- Documentation files (`README.md`, `docs/*`, `CONTRIBUTING.md`)

Vietnamese is reserved for two places outside this repo:

- The thesis report (`vn-p2-report`, local-only until defense)
- Interactive discussion between contributors (chat, meetings)

Vietnamese data **values** stored in the database (sector names, company names
from vnstock, Vietnamese news headlines in `news_sentiment`) are legitimate
content and remain in Vietnamese - the ASCII convention applies to *source
code* that developers read, not to runtime data.

### ASCII enforcement

A pre-commit hook (`check-ascii`) scans every `.py` and `.sql` file in a diff
and fails the commit if non-ASCII characters appear outside of SQL/Python
string literals. Common cases the hook catches:

- Em-dashes `-` (use ASCII hyphen `-`)
- Unicode arrows `->` (use `->`)
- Smart quotes `" "` or `' '` (use straight `"` or `'`)
- Vietnamese narrative in docstrings or comments

Rules of thumb:

- Section references: write `ADR-015 section 2.4`, not `ADR-015 2.4`
- Multiplication in formulas: `shares * price`, not `shares x price`
- Comparisons in docstrings: `>=` / `<=`, not `>=` / `<=`

To check locally before committing:

```bash
pre-commit run check-ascii --all-files
```

## Commit messages

Follow Conventional Commits:

```
<type>(<scope>): <subject>

<body>
```

Allowed `<type>` values:

| Type       | Use for                                                      |
|------------|--------------------------------------------------------------|
| `feat`     | New feature                                                  |
| `fix`      | Bug fix                                                      |
| `docs`     | Documentation only (README, ADRs, CONTRIBUTING)              |
| `test`     | Adding or correcting tests                                   |
| `refactor` | Code change that neither fixes a bug nor adds a feature      |
| `chore`    | Build config, tooling, dependencies, formatting, admin       |
| `ci`       | CI pipeline changes                                          |
| `infra`    | Database migrations, deployment, infrastructure              |
| `polish`   | Minor UI / wording / cosmetic adjustments                    |

Scope should name the sprint (`sprint11`, `sprint12`) or the feature area
(`f2`, `cost-model`) when relevant.

**Subject**: imperative mood, no trailing period, under 72 characters.

**Body**: optional. Explain *why* over *what*; the diff shows what. Use blank
line between subject and body, hard-wrap at 72 characters.

## Branch naming

Prefix branches by their commit type, slash-separated:

- `feat/sprint11-day6-simulator`
- `fix/sprint11-day4.5-review`
- `docs/adr-016-testing`
- `chore/day1-4-english-translation`

## Pull requests

1. Branch from `main`. Keep PRs focused: one logical change per PR.
2. Open the PR against `main`. All five CI checks must pass before merge
   (lint + Python 3.11 / 3.12 / 3.13 matrix + pip-audit).
3. Use squash-merge to keep `main` history linear. Delete the branch after
   merge.
4. Include a brief test plan in the PR body (what you ran, what the counts /
   coverage are).

## Testing

- Unit tests live in `tests/unit/`; integration tests in `tests/`.
- Target coverage: 85%+ on domain and application layers.
- `hypothesis` property-based tests are encouraged for domain invariants
  (NFR-R-07 Deterministic Reproducibility, VWAP math).
- Integration tests requiring Neon skip cleanly on CI (no
  `NEON_DATABASE_URL` set). Run locally with the env var exported.

Full suite:

```bash
pytest tests/ -q
ruff check src/ tests/
lint-imports --config importlinter.ini
```

## Architecture

Follow ADR-015 Hexagonal boundaries:

- `domain/` must not import from `application/`, `infrastructure/`, or
  `interface/`.
- `application/services/` must depend on `application/ports/` Protocols, never
  on concrete Neon implementations.
- `application/ports/` must not import from `infrastructure/`.

The `import-linter` hook enforces these on every commit.

## Secrets

Never commit real credentials. All configuration goes through Pydantic
`BaseSettings` with `SecretStr` fields (see `src/vn_portfolio_frontier/
config.py`). Use `.env` for local development (gitignored). The `gitleaks`
hook scans every commit for high-entropy strings.

## Questions

Open an issue or discussion thread in the GitHub repository.
