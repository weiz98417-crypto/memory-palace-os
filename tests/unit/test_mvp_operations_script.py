import json
from pathlib import Path
import shutil
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "mvp.ps1"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def run_mvp_script(*arguments: str) -> subprocess.CompletedProcess[str]:
    if not POWERSHELL:
        pytest.skip("PowerShell is required for MVP operations script tests")
    return subprocess.run(
        [
            POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT_PATH),
            *arguments,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_help_lists_complete_enterprise_mvp_command_set():
    result = run_mvp_script("help")

    assert result.returncode == 0
    for command in (
        "install",
        "start",
        "status",
        "migrate",
        "bootstrap-uat",
        "verify",
        "backup",
        "restore",
        "logs",
        "upgrade",
        "restart-app",
        "stop",
        "doctor",
    ):
        assert f"mvp.cmd {command}" in result.stdout


@pytest.mark.parametrize(
    "command",
    (
        "install", "start", "migrate", "bootstrap-uat", "verify", "logs",
        "upgrade", "restart-app", "stop",
    ),
)
def test_deployment_commands_require_explicit_environment_file(command):
    result = run_mvp_script(command)

    assert result.returncode != 0
    assert "EnvFile" in f"{result.stdout}\n{result.stderr}"


def test_restore_requires_explicit_target_project(tmp_path):
    result = run_mvp_script(
        "restore",
        "-BackupId",
        "backup-20260728",
        "-BackupRoot",
        str(tmp_path),
    )

    assert result.returncode != 0
    assert "TargetProject" in f"{result.stdout}\n{result.stderr}"


def test_restore_accepts_prd_positional_backup_id(tmp_path):
    result = run_mvp_script("restore", "backup-20260728", "-BackupRoot", str(tmp_path))

    assert result.returncode != 0
    assert "TargetProject" in f"{result.stdout}\n{result.stderr}"


def test_restore_rejects_backup_id_path_traversal(tmp_path):
    result = run_mvp_script(
        "restore",
        "-BackupId",
        "..\\outside",
        "-BackupRoot",
        str(tmp_path),
        "-TargetProject",
        "memory-palace-restore",
    )

    assert result.returncode != 0
    output = f"{result.stdout}\n{result.stderr}"
    assert "BackupId" in output
    assert "direct child" in output


def test_restore_requires_exact_typed_target_confirmation(tmp_path):
    result = run_mvp_script(
        "restore",
        "-BackupId",
        "backup-20260728",
        "-BackupRoot",
        str(tmp_path),
        "-TargetProject",
        "memory-palace-restore",
        "-ConfirmTarget",
        "memory-palace-other",
    )

    assert result.returncode != 0
    output = f"{result.stdout}\n{result.stderr}"
    assert "ConfirmTarget" in output


def test_restore_to_source_project_requires_force(tmp_path):
    result = run_mvp_script(
        "restore",
        "-Project",
        "memory-palace-mvp",
        "-BackupId",
        "backup-20260728",
        "-BackupRoot",
        str(tmp_path),
        "-TargetProject",
        "memory-palace-mvp",
        "-ConfirmTarget",
        "memory-palace-mvp",
    )

    assert result.returncode != 0
    output = f"{result.stdout}\n{result.stderr}"
    assert "source project" in output
    assert "-Force" in output


def test_restore_requires_explicit_environment_file(tmp_path):
    result = run_mvp_script(
        "restore",
        "-BackupId",
        "backup-20260728",
        "-BackupRoot",
        str(tmp_path),
        "-TargetProject",
        "memory-palace-restore",
        "-ConfirmTarget",
        "memory-palace-restore",
    )

    assert result.returncode != 0
    output = f"{result.stdout}\n{result.stderr}"
    assert "EnvFile" in output
    assert "secret" in output.lower()


def test_restore_requires_isolated_target_secrets_volume(tmp_path):
    result = run_mvp_script(
        "restore",
        "-BackupId",
        "backup-20260728",
        "-BackupRoot",
        str(tmp_path),
        "-TargetProject",
        "memory-palace-restore",
        "-ConfirmTarget",
        "memory-palace-restore",
        "-EnvFile",
        str(PROJECT_ROOT / ".env.example"),
    )

    assert result.returncode != 0
    assert "TargetSecretsVolume" in f"{result.stdout}\n{result.stderr}"


def test_restore_rejects_shared_global_secrets_volume(tmp_path):
    result = run_mvp_script(
        "restore",
        "-BackupId",
        "backup-20260728",
        "-BackupRoot",
        str(tmp_path),
        "-TargetProject",
        "memory-palace-restore",
        "-ConfirmTarget",
        "memory-palace-restore",
        "-EnvFile",
        str(PROJECT_ROOT / ".env.example"),
        "-TargetSecretsVolume",
        "memory-palace-secrets",
    )

    assert result.returncode != 0
    output = f"{result.stdout}\n{result.stderr}"
    assert "TargetSecretsVolume" in output
    assert "shared" in output.lower()


def test_restore_rejects_tampered_artifact_checksum(tmp_path):
    backup_id = "tampered-backup"
    backup_directory = tmp_path / backup_id
    backup_directory.mkdir()
    (backup_directory / "postgres.dump").write_bytes(b"not-a-real-dump")
    (backup_directory / "chroma-data.tar.gz").write_bytes(b"not-a-real-archive")
    (backup_directory / "embedding-cache.tar.gz").write_bytes(b"not-a-real-cache")
    (backup_directory / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "memory-palace-mvp-backup/v2",
                "backup_id": backup_id,
                "source": {
                    "compose_project": "memory-palace-mvp",
                    "compose_file_sha256": "0" * 64,
                },
                "artifacts": {
                    "postgres": {"file": "postgres.dump", "sha256": "0" * 64},
                    "chroma": {"file": "chroma-data.tar.gz", "sha256": "0" * 64},
                    "embedding_cache": {
                        "file": "embedding-cache.tar.gz",
                        "sha256": "0" * 64,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_mvp_script(
        "restore",
        "-BackupId",
        backup_id,
        "-BackupRoot",
        str(tmp_path),
        "-TargetProject",
        "memory-palace-restore",
        "-ConfirmTarget",
        "memory-palace-restore",
        "-EnvFile",
        str(PROJECT_ROOT / ".env.example"),
        "-TargetSecretsVolume",
        "memory-palace-restore-secrets",
    )

    assert result.returncode != 0
    assert "checksum mismatch" in f"{result.stdout}\n{result.stderr}"


def test_backup_v2_contract_covers_embedding_cache_and_safe_restore():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert '$ManifestSchema = "memory-palace-mvp-backup/v2"' in source
    assert '$EmbeddingArtifactName = "embedding-cache.tar.gz"' in source
    assert 'Get-ProjectVolume -ComposeProject $Project -Volume "embedding-cache"' in source
    assert 'New-ProjectVolume -ComposeProject $TargetProject -Volume "embedding-cache"' in source
    assert 'foreach ($volume in @("pg-data", "chroma-data", "embedding-cache"))' in source
    assert '"tar", "-tvzf", "/backup/$ArtifactName"' in source
    assert '"--no-same-permissions"' in source


def test_restore_forces_explicit_isolated_secrets_volume_into_compose():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "[string]$TargetSecretsVolume" in source
    assert '$env:MEMORY_PALACE_SECRETS_VOLUME = $TargetSecretsVolume' in source
    assert "Initialize-EmptySecretsVolume" in source
    assert "Initialize-RestoreApplicationSecret" in source
    assert '$env:DEEPSEEK_BASE_URL = "http://127.0.0.1:9/v1"' in source


def test_successful_backup_records_completed_platform_evidence():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "function Write-BackupRecord" in source
    assert "INSERT INTO backup_records" in source
    assert '$previousErrorPreference = $ErrorActionPreference' in source
    assert '-Status "COMPLETED"' in source
    assert ":'backup_id'" not in source
    assert source.index("Move-Item -LiteralPath $partialDirectory -Destination $finalDirectory") < source.index(
        "Write-BackupRecord",
        source.index("function Invoke-Backup"),
    )


def test_enterprise_mvp_lifecycle_commands_use_formal_compose_and_explicit_configuration():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    for command in (
        "Install", "Start", "Migrate", "Verify", "Logs", "Upgrade",
        "RestartApp", "Stop",
    ):
        assert f"function Invoke-{command}" in source
    assert 'Join-Path $ProjectRoot "deploy\\docker-compose.yml"' in source
    assert '"compose", "--env-file", $ResolvedEnvFile, "-f", $ResolvedComposeFile' in source
    assert 'throw "EnvFile is required;' in source
    assert '[string]$SecretsVolume = "memory-palace-secrets"' in source
    assert "[switch]$AllowDirtyBuild" in source
    assert "[switch]$Offline" in source
    assert "Offline install: using locally cached pinned images." in source
    assert "Offline upgrade: using locally cached pinned images." in source
    assert "function Get-ReleaseRevision" in source
    assert "function Register-ReleaseImage" in source
    assert '"image", "tag"' in source
    assert '"volume", "create"' in source
    assert "No credential was written" in source


def test_start_and_migrate_use_idempotent_formal_postgres_initialization():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    start_source = source[source.index("function Invoke-Start") : source.index("function Invoke-Migrate")]
    migration_source = source[
        source.index("function Invoke-PostgresMigration") : source.index("function Invoke-Start")
    ]

    assert start_source.index('@("up", "-d", "postgres", "redis", "chromadb")') < start_source.index(
        "Invoke-PostgresMigration"
    )
    assert start_source.index("Invoke-PostgresMigration") < start_source.index(
        '@("up", "-d", "--no-deps", "app")'
    )
    assert "src.memory_palace.knowledge.db_init import init_database" in migration_source
    assert "src.memory_palace.knowledge.postgres_client import PostgresDBClient" in migration_source
    assert "bootstrap_identity_store" in migration_source
    assert "CREATE TABLE IF NOT EXISTS mvp_schema_migrations" in migration_source
    assert "ON CONFLICT(version) DO UPDATE" in migration_source


def test_uat_bootstrap_uses_formal_api_script_and_external_secret():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    bootstrap_source = source[source.index("function Invoke-UatBootstrap") : source.index("function Invoke-Verify")]

    assert 'SecretName "uat_employee_password"' in bootstrap_source
    assert 'scripts\\set_uat_employee_secret.ps1' in bootstrap_source
    assert '@("exec", "-T", "app", "python", "scripts/bootstrap_uat.py")' in bootstrap_source
    assert "psql" not in bootstrap_source
    assert "DELETE FROM" not in bootstrap_source


def test_verify_logs_and_stop_keep_runtime_operations_safe():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    verify_source = source[source.index("function Invoke-Verify") : source.index("function Protect-LogText")]
    logs_source = source[source.index("function Protect-LogText") : source.index("function Invoke-Stop")]
    stop_source = source[source.index("function Invoke-Stop") : source.index("function Write-UpgradeRollbackHint")]

    assert "Invoke-Doctor" in verify_source
    assert '"http://localhost:8000/health"' in verify_source
    assert '"http://127.0.0.1/admin/"' in verify_source
    assert "[int]$Tail = 200" in source
    assert "[switch]$Follow" in source
    assert "[REDACTED]" in logs_source
    assert '@("stop")' in stop_source
    assert '"down"' not in stop_source
    assert '"--volumes"' not in stop_source


def test_restart_app_is_fixed_scope_and_proves_runtime_change():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert '"restart-app"' in source
    assert "function Invoke-RestartApp" in source
    restart_source = source[
        source.index("function Invoke-RestartApp") : source.index("function Invoke-Stop")
    ]
    assert '@("restart", "app")' in restart_source
    assert "Get-ServiceRuntimeIdentity" in restart_source
    assert 'Wait-ServiceReady -ComposeProject $context.Project -Service "app"' in restart_source
    assert 'foreach ($service in @("postgres", "redis", "chromadb", "nginx"))' in restart_source
    assert "App runtime identity did not change" in restart_source
    assert "Non-App service changed during restart-app" in restart_source
    assert '"down"' not in restart_source
    assert '"--volumes"' not in restart_source
    assert '"force-recreate"' not in restart_source
    assert '"restart-app" {' in source[source.index("switch ($Command)") :]


def test_upgrade_is_backup_first_and_emits_non_destructive_recovery_command():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    upgrade_source = source[source.index("function Invoke-Upgrade") : source.index("function Invoke-Restore")]
    rollback_source = source[
        source.index("function Write-UpgradeRollbackHint") : source.index("function Invoke-Upgrade")
    ]

    assert upgrade_source.index("Invoke-Backup") < upgrade_source.index(
        '@("pull", "postgres", "redis", "chromadb", "nginx")'
    )
    assert upgrade_source.index('@("build", "app")') < upgrade_source.index("Invoke-PostgresMigration")
    assert upgrade_source.index("Invoke-PostgresMigration") < upgrade_source.index('"--force-recreate", "app"')
    assert upgrade_source.index('"--force-recreate", "app"') < upgrade_source.index("Invoke-Verify")
    assert "scripts\\mvp.cmd restore" in rollback_source
    assert "-TargetSecretsVolume" in rollback_source
    assert "Existing data and secrets were not deleted" in rollback_source
    assert '"down"' not in upgrade_source
    assert '"--volumes"' not in upgrade_source


def test_lifecycle_rejects_compose_override_and_requires_real_healthchecks():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    deployment_source = source[
        source.index("function Assert-DeploymentParameters") : source.index("function Resolve-SafeBackupRoot")
    ]
    wait_source = source[source.index("function Wait-ContainerReady") : source.index("function Get-ServiceManifest")]
    doctor_source = source[
        source.index("function Invoke-Doctor") : source.index("\ntry {\n    switch ($Command)")
    ]

    assert "official ComposeFile" in deployment_source
    assert 'deploy\\docker-compose.yml' in deployment_source
    assert '$health -eq "healthy"' in wait_source
    assert '$health -eq "not-configured"' in wait_source
    assert "has no healthcheck" in wait_source
    assert '$status.Health -eq "healthy"' in doctor_source


def test_runtime_discovery_ignores_standalone_containers_inheriting_image_labels():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    discovery_start = source.index("function Get-ServiceContainers")
    discovery_source = source[
        discovery_start : source.index("function Get-ServiceContainer {", discovery_start)
    ]

    assert '"--filter", "label=com.docker.compose.container-number"' in discovery_source
