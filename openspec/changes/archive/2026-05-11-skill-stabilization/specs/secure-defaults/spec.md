# secure-defaults — 安全默认配置

## ADDED Requirements

### Requirement: .gitignore protects sensitive files
The repository SHALL contain a `.gitignore` file that excludes `data/memory.db`, `data/logs/`, `.env`, `__pycache__/`, `.venv/`, and `htmlcov/`.

#### Scenario: .env is not tracked
- **WHEN** `git status` is run
- **THEN** `.env` does not appear as an untracked file

#### Scenario: database files are not tracked
- **WHEN** `git status` is run
- **THEN** files under `data/` do not appear as untracked files

### Requirement: .env.example remains tracked
The `.env.example` file SHALL remain tracked in git as a template for new developers.

#### Scenario: .env.example is versioned
- **WHEN** `git status` is run after adding `.gitignore`
- **THEN** `.env.example` changes are still tracked
