# windows-compat — Windows 控制台兼容

## ADDED Requirements

### Requirement: Log output is encoding-safe on Windows
The system SHALL configure loguru handlers with `encoding="utf-8"` on Windows platforms, preventing `UnicodeEncodeError` from emoji characters in log messages.

#### Scenario: Startup with emoji log messages
- **WHEN** the application starts on Windows with GBK console encoding
- **THEN** all log messages (including emoji-bearing ones) are written without UnicodeEncodeError

#### Scenario: Log file output preserved
- **WHEN** the application writes logs to `data/logs/` directory
- **THEN** log files contain the original emoji characters (file encoding is independent of console encoding)

### Requirement: Requirements file is complete
The system SHALL declare all required dependencies in `requirements.txt`, including `pytz`. No dependency SHALL be declared more than once.

#### Scenario: Fresh install from requirements.txt
- **WHEN** `pip install -r requirements.txt` is executed in a fresh virtual environment
- **THEN** all imports in the codebase succeed; no `ModuleNotFoundError` is raised for any project import

#### Scenario: No duplicate entries
- **WHEN** `requirements.txt` is parsed
- **THEN** each package name appears at most once
