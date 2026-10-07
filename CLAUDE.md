# Claude Code handoff

Start with `REPRODUCE.md` and `AGENTS.md`. Reproduce the Docker path before making product changes. Treat `evals/` as executable acceptance data and `tests/` as the regression suite. Use formal API/import scripts for seeded data; do not write directly to a local database file or expose secrets from `.env` or Docker volumes.
