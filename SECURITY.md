# Security Policy

## Supported Versions

This project is a research/thesis codebase under active development. Only the `main` branch receives security updates. Tagged releases (introduced from Phase 3 onward) will follow SemVer with a 6-month security window on the latest minor version.

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report privately via one of:

1. **GitHub Private Vulnerability Reporting** — [Security tab → Report a vulnerability](https://github.com/MCTGiang/vn-portfolio-frontier/security/advisories/new) (preferred).
2. **Email** — mctgiang@gmail.com with subject prefix `[SECURITY]`.

Include:
- Affected component (file path, endpoint, or dependency).
- Steps to reproduce.
- Potential impact.
- Suggested mitigation, if any.

## Response Timeline

| Stage | Target |
|-------|--------|
| Acknowledgment | Within 5 business days |
| Initial assessment | Within 14 days |
| Fix or mitigation plan | Within 30 days for confirmed issues |

Best-effort — this is a solo thesis project, not a production service.

## Scope

**In scope:**
- Source code in `src/`, `scripts/`, `migrations/`, `tests/`.
- CI/CD workflows in `.github/`.
- Dependency vulnerabilities (surfaced by Dependabot / pip-audit).
- Migration SQL that could enable SQL injection through parameterized-query bypass.

**Out of scope:**
- Third-party services (Neon PostgreSQL, GitHub Actions runners) — report to those vendors.
- Vulnerabilities in the Vietnamese news sources this project scrapes.
- Denial-of-service via bulk scraping (rate limits are the scraper's responsibility; not this project's threat model).

## Secrets

This repository must never contain:
- Database URLs with embedded credentials (use `.env`, gitignored).
- API keys for news sources or LLM providers (also `.env`).
- Neon service tokens.

GitHub secret scanning + push protection are enabled; commits containing detected secrets are blocked at push time.

Local defense in depth is provided by `gitleaks` in `.pre-commit-config.yaml` (added Commit 9a).
