"""Prepare pinned scenic Agent runtime models and container images for offline use."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Callable, Iterable


HATCHET_REVISION = "v0.107.1"
TEI_IMAGE = "ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4"
IMAGE_SPECS = (
    "pgvector/pgvector:0.8.1-pg15-bookworm",
    "postgres:15.6",
    "redis:7.2.5-alpine",
    "nginx:1.25.5-alpine",
    TEI_IMAGE,
    f"ghcr.io/hatchet-dev/hatchet/hatchet-engine:{HATCHET_REVISION}",
    f"ghcr.io/hatchet-dev/hatchet/hatchet-api:{HATCHET_REVISION}",
    f"ghcr.io/hatchet-dev/hatchet/hatchet-migrate:{HATCHET_REVISION}",
    f"ghcr.io/hatchet-dev/hatchet/hatchet-admin:{HATCHET_REVISION}",
    "jaegertracing/all-in-one:1.62.0",
)
MODEL_SPECS = {
    "bge_m3": {
        "repo_id": "BAAI/bge-m3",
        "revision": "5617a9f61b028005a4858fdac845db406aefb181",
    },
    "reranker": {
        "repo_id": "BAAI/bge-reranker-base",
        "revision": "2cfc18c9415c912f9d8155881c133215df768a70",
    },
}

CommandRunner = Callable[..., object]


def prepare_images(images: Iterable[str] = IMAGE_SPECS, *, runner: CommandRunner = subprocess.run) -> None:
    for image in images:
        runner(["docker", "pull", image], check=True)


def prepare_models(
    *,
    model_cache_dir: str | Path,
    reranker_dir: str | Path,
    snapshot_download: Callable[..., str] | None = None,
) -> None:
    if snapshot_download is None:
        from huggingface_hub import snapshot_download as huggingface_snapshot_download

        snapshot_download = huggingface_snapshot_download

    cache_path = Path(model_cache_dir).expanduser().resolve()
    reranker_path = Path(reranker_dir).expanduser().resolve()
    cache_path.mkdir(parents=True, exist_ok=True)
    reranker_path.mkdir(parents=True, exist_ok=True)

    bge_m3 = MODEL_SPECS["bge_m3"]
    snapshot_download(
        repo_id=bge_m3["repo_id"],
        revision=bge_m3["revision"],
        cache_dir=str(cache_path / "hub"),
    )

    reranker = MODEL_SPECS["reranker"]
    snapshot_download(
        repo_id=reranker["repo_id"],
        revision=reranker["revision"],
        local_dir=str(reranker_path),
    )


def _compose_command(project: str, env_file: str, compose_file: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-p",
        project,
        "--env-file",
        env_file,
        "-f",
        compose_file,
        "--profile",
        "agent-runtime",
    ]


def initialize_hatchet(
    *,
    project: str,
    env_file: str,
    compose_file: str,
    runner: CommandRunner = subprocess.run,
) -> None:
    compose = _compose_command(project, env_file, compose_file)
    runner([*compose, "up", "-d", "--wait", "hatchet-postgres"], check=True)
    runner([*compose, "run", "--rm", "hatchet-migrate"], check=True)
    runner([*compose, "run", "--rm", "hatchet-admin"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-cache-dir", type=Path)
    parser.add_argument("--reranker-dir", type=Path)
    parser.add_argument("--skip-models", action="store_true")
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--migrate-hatchet", action="store_true")
    parser.add_argument("--project", default="memory-palace-scenic")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--compose-file", default="deploy/docker-compose.yml")
    args = parser.parse_args()

    if not args.skip_images:
        prepare_images()
    if not args.skip_models:
        if args.model_cache_dir is None or args.reranker_dir is None:
            parser.error("--model-cache-dir and --reranker-dir are required unless --skip-models is set")
        prepare_models(
            model_cache_dir=args.model_cache_dir,
            reranker_dir=args.reranker_dir,
        )
    if args.migrate_hatchet:
        initialize_hatchet(
            project=args.project,
            env_file=args.env_file,
            compose_file=args.compose_file,
        )

    print("Scenic Agent runtime offline assets are prepared.")
    if args.migrate_hatchet:
        print("Hatchet database migration and quickstart completed.")


if __name__ == "__main__":
    main()
