# test-health — 测试健康度

## ADDED Requirements

### Requirement: All existing unit tests pass or are explicitly skipped
Running `pytest tests/ -v` SHALL result in zero failures. Tests that cannot be fixed due to missing dependencies or deleted APIs SHALL be marked with `@pytest.mark.skip` and a reason comment.

#### Scenario: Full test suite runs without failures
- **WHEN** `pytest tests/ -v` is executed
- **THEN** the exit code is 0 (all tests pass or are skipped) and no FAIL entries appear

### Requirement: Test dependencies are declared
All packages required to run the test suite SHALL be listed in `requirements.txt`.

#### Scenario: Fresh install runs tests
- **WHEN** `pip install -r requirements.txt` is executed in a fresh environment
- **THEN** `pytest tests/ -v` can collect and run all tests without `ModuleNotFoundError`
