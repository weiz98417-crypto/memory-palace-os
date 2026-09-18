from pathlib import Path

from scripts.prepare_scenic_agent_runtime import (
    HATCHET_REVISION,
    IMAGE_SPECS,
    MODEL_SPECS,
    initialize_hatchet,
    prepare_images,
    prepare_models,
)


def test_offline_manifest_pins_models_and_all_runtime_images():
    assert HATCHET_REVISION == "v0.107.1"
    assert MODEL_SPECS["bge_m3"]["revision"] == "5617a9f61b028005a4858fdac845db406aefb181"
    assert MODEL_SPECS["reranker"]["revision"] == "2cfc18c9415c912f9d8155881c133215df768a70"
    assert "ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4" in IMAGE_SPECS
    assert "jaegertracing/all-in-one:1.62.0" in IMAGE_SPECS
    for role in ("engine", "api", "migrate", "admin"):
        assert f"ghcr.io/hatchet-dev/hatchet/hatchet-{role}:v0.107.1" in IMAGE_SPECS


def test_prepare_images_pulls_every_pinned_image_once():
    calls = []

    def runner(command, check):
        calls.append((command, check))

    prepare_images(IMAGE_SPECS, runner=runner)

    assert len(calls) == len(IMAGE_SPECS)
    assert all(command[:2] == ["docker", "pull"] for command, _ in calls)
    assert all(check is True for _, check in calls)


def test_prepare_models_uses_pinned_revisions_and_onsite_directories(tmp_path):
    calls = []

    def snapshot_download(**kwargs):
        calls.append(kwargs)
        return str(kwargs.get("local_dir") or kwargs.get("cache_dir"))

    prepare_models(
        model_cache_dir=tmp_path / "hf",
        reranker_dir=tmp_path / "reranker",
        snapshot_download=snapshot_download,
    )

    by_repo = {call["repo_id"]: call for call in calls}
    assert by_repo["BAAI/bge-m3"]["revision"] == MODEL_SPECS["bge_m3"]["revision"]
    assert Path(by_repo["BAAI/bge-m3"]["cache_dir"]) == tmp_path / "hf" / "hub"
    assert by_repo["BAAI/bge-reranker-base"]["revision"] == MODEL_SPECS["reranker"]["revision"]
    assert Path(by_repo["BAAI/bge-reranker-base"]["local_dir"]) == tmp_path / "reranker"


def test_initialize_hatchet_runs_postgres_pull_up_and_one_shot_jobs_in_order():
    commands = []

    def runner(command, check):
        commands.append(command)

    initialize_hatchet(
        project="memory-palace-scenic",
        env_file=".env",
        compose_file="deploy/docker-compose.yml",
        runner=runner,
    )

    assert len(commands) == 3
    assert commands[0][:3] == ["docker", "compose", "-p"]
    assert "up" in commands[0] and "hatchet-postgres" in commands[0]
    assert "run" in commands[1] and "hatchet-migrate" in commands[1]
    assert "run" in commands[2] and "hatchet-admin" in commands[2]
