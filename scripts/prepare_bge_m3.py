"""Download the approved bge-m3 snapshot into a host-owned model cache."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


MODEL_ID = "BAAI/bge-m3"
# Must match deploy/docker-compose.yml TEI cache and scripts/prepare_scenic_agent_runtime.py.
MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--revision", default=MODEL_REVISION)
    args = parser.parse_args()

    cache_dir = args.cache_dir.expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(cache_dir)

    from huggingface_hub import snapshot_download

    snapshot_path = snapshot_download(
        repo_id=MODEL_ID,
        revision=args.revision,
        cache_dir=str(cache_dir / "hub"),
    )
    print(f"bge-m3 prepared at {snapshot_path}")
    print(f"Set BGE_M3_CACHE_DIR={cache_dir}")


if __name__ == "__main__":
    main()
