import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.memory_palace.config.env_validator import EnvValidator
from src.memory_palace.config.secrets import read_secret
from src.memory_palace.tools.llm_wrapper import LLMClient


def test_env_validator_import_does_not_snapshot_secrets_before_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://dotenv-user@localhost:5432/dotenv-db",
                "REDIS_URL=redis://localhost:6379/9",
                "DEEPSEEK_API_KEY=sk-dotenv-backed-test-secret",
                "MEMORY_PALACE_JWT_SECRET=dotenv-jwt-secret-with-at-least-32-characters",
                "ADMIN_PASSWORD=dotenv-admin-password",
            ]
        ),
        encoding="utf-8",
    )
    script = """
import os
import sys

from dotenv import load_dotenv

for key in (
    "DATABASE_URL",
    "REDIS_URL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API_KEY_FILE",
    "MEMORY_PALACE_JWT_SECRET",
    "ADMIN_PASSWORD",
):
    os.environ.pop(key, None)

import src.memory_palace.config.env_validator

assert "src.memory_palace.config.secrets" not in sys.modules
load_dotenv(os.environ["TEST_DOTENV_PATH"])

from src.memory_palace.config.secrets import secrets

assert secrets.DATABASE_URL == "postgresql://dotenv-user@localhost:5432/dotenv-db"
assert secrets.REDIS_URL == "redis://localhost:6379/9"
assert secrets.LLM_PRIMARY_API_KEY == "sk-dotenv-backed-test-secret"
assert secrets.JWT_SECRET == "dotenv-jwt-secret-with-at-least-32-characters"
assert secrets.ADMIN_PASSWORD == "dotenv-admin-password"
"""
    process_env = os.environ.copy()
    process_env["TEST_DOTENV_PATH"] = str(env_file)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env=process_env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_main_bootstrap_loads_environment_before_global_secrets_snapshot():
    script = """
import os

import dotenv

for key in (
    "DATABASE_URL",
    "REDIS_URL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API_KEY_FILE",
    "MEMORY_PALACE_JWT_SECRET",
    "ADMIN_PASSWORD",
):
    os.environ.pop(key, None)

def load_test_environment(*args, **kwargs):
    os.environ.update(
        {
            "APP_ENV": "prod",
            "DEMO_MODE": "false",
            "DATABASE_URL": "postgresql://bootstrap-user@localhost:5432/bootstrap-db",
            "REDIS_URL": "redis://localhost:6379/8",
            "DEEPSEEK_API_KEY": "sk-bootstrap-test-secret",
            "LLM_DEFAULT_MODEL": "deepseek-v4-flash",
            "MEMORY_PALACE_JWT_SECRET": "bootstrap-jwt-secret-with-at-least-32-characters",
            "ADMIN_PASSWORD": "bootstrap-admin-password",
        }
    )
    return True

dotenv.load_dotenv = load_test_environment

import main
from src.memory_palace.config.secrets import secrets

assert secrets.DATABASE_URL == "postgresql://bootstrap-user@localhost:5432/bootstrap-db"
assert secrets.REDIS_URL == "redis://localhost:6379/8"
assert secrets.LLM_PRIMARY_API_KEY == "sk-bootstrap-test-secret"
assert secrets.JWT_SECRET == "bootstrap-jwt-secret-with-at-least-32-characters"
assert secrets.ADMIN_PASSWORD == "bootstrap-admin-password"
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_read_secret_uses_mounted_file_without_exporting_value(tmp_path, monkeypatch):
    secret_file = tmp_path / "deepseek_api_key"
    secret_file.write_text("\ufeffsk-file-backed-test-secret\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY_FILE", str(secret_file))

    assert read_secret("DEEPSEEK_API_KEY") == "sk-file-backed-test-secret"
    assert "DEEPSEEK_API_KEY" not in os.environ


def test_environment_validation_accepts_file_backed_deepseek_key(tmp_path, monkeypatch):
    secret_file = tmp_path / "deepseek_api_key"
    secret_file.write_text("sk-file-backed-test-secret\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY_FILE", str(secret_file))

    result = EnvValidator().validate()

    assert not any(error.startswith("DEEPSEEK_API_KEY:") for error in result.errors)


@pytest.mark.asyncio
async def test_llm_client_uses_file_backed_deepseek_key(tmp_path, monkeypatch):
    secret_file = tmp_path / "deepseek_api_key"
    secret_file.write_text("sk-file-backed-test-secret\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY_FILE", str(secret_file))

    sdk_client = await LLMClient().get_client()

    assert sdk_client.api_key == "sk-file-backed-test-secret"
    await sdk_client.close()
