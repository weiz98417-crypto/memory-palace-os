"""Build and verify an optional offline frontend release bundle.

The bundle keeps source canonical: it contains a git source archive, the base
images and dependency metadata needed by the existing Dockerfile. The offline
verification reuses deploy/Dockerfile with --network=none and compares every
file under /static/client with the online build.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Iterable


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None, log: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True)
    if log is not None:
        log.append(f"$ {' '.join(command)}")
        log.extend(part for part in (result.stdout, result.stderr) if part)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}\n{result.stderr}")
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def copy_image_tree(image: str, source: str, target: Path, *, cwd: Path, log: list[str]) -> None:
    created = run(["docker", "create", image], cwd=cwd, log=log).stdout.strip().splitlines()[-1]
    try:
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        run(["docker", "cp", f"{created}:{source}/.", str(target)], cwd=cwd, log=log)
    finally:
        subprocess.run(["docker", "rm", "-f", created], cwd=cwd, capture_output=True, text=True)


def build_online(args: argparse.Namespace, log: list[str]) -> None:
    command = [
        "docker", "buildx", "build",
        "--file", "deploy/Dockerfile",
        "--target", "frontend-builder",
        "--no-cache",
        "--build-arg", f"NODE_IMAGE={args.node_image}",
        "--build-arg", f"PYTHON_BASE_IMAGE={args.python_image}",
        "--output", f"type=image,name={args.online_image}",
        ".",
    ]
    run(command, cwd=args.repo_root, log=log)


def build_offline(args: argparse.Namespace, source_dir: Path, log: list[str]) -> None:
    command = [
        "docker", "buildx", "build",
        "--file", "deploy/Dockerfile",
        "--target", "frontend-builder-offline",
        "--network=none",
        "--build-arg", f"NODE_IMAGE={args.node_image}",
        "--build-arg", f"PYTHON_BASE_IMAGE={args.python_image}",
        "--output", f"type=image,name={args.offline_image}",
        ".",
    ]
    run(command, cwd=source_dir, log=log)


def export_offline_inputs(repo_root: Path, image: str, target_dir: Path, log: list[str]) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    created = run(
        [
            "docker", "create", image, "sh", "-lc",
            "find . -type d -name node_modules -prune -print0 | tar --null -T - -czf /tmp/node_modules.tar.gz",
        ],
        cwd=repo_root,
        log=log,
    ).stdout.strip().splitlines()[-1]
    try:
        run(["docker", "start", "-a", created], cwd=repo_root, log=log)
        run(["docker", "cp", f"{created}:/tmp/node_modules.tar.gz", str(target_dir / "node_modules.tar.gz")], cwd=repo_root, log=log)
        run([sys.executable, "scripts/export_openapi.py", str(target_dir / "openapi.json")], cwd=repo_root, log=log)
    finally:
        subprocess.run(["docker", "rm", "-f", created], cwd=repo_root, capture_output=True, text=True)


def save_image(repo_root: Path, image: str, target: Path, log: list[str]) -> None:
    run(["docker", "save", "--output", str(target), image], cwd=repo_root, log=log)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an offline frontend bundle and verify no-network reconstruction.")
    parser.add_argument("--output", type=Path, default=Path("artifacts/frontend-offline-bundle"))
    parser.add_argument("--node-image", default="docker.1ms.run/library/node:24.15.0-bookworm-slim")
    parser.add_argument("--python-image", default="python:3.11-slim")
    parser.add_argument("--online-image", default="memory-palace-frontend-online:latest")
    parser.add_argument("--offline-image", default="memory-palace-frontend-offline:latest")
    parser.add_argument("--skip-offline-verify", action="store_true")
    args = parser.parse_args()
    args.repo_root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if args.repo_root not in output.parents:
        raise RuntimeError(f"offline bundle output must stay inside repository: {output}")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    image_dir = output / "images"
    image_dir.mkdir()
    log: list[str] = []
    started = time.time()
    commit = run(["git", "rev-parse", "HEAD"], cwd=args.repo_root, log=log).stdout.strip()
    source_archive = output / "source.tar.gz"
    run(
        ["git", "archive", "--format=tar.gz", "--output", str(source_archive), "HEAD"],
        cwd=args.repo_root,
        log=log,
    )

    try:
        build_online(args, log)
        copy_image_tree(args.online_image, "/static/client", output / "online-static-client", cwd=args.repo_root, log=log)
        online_hashes = tree_hashes(output / "online-static-client")

        save_image(args.repo_root, args.node_image, image_dir / "node-image.tar", log)
        save_image(args.repo_root, args.python_image, image_dir / "python-image.tar", log)

        offline_dir = output / "offline-source"
        offline_dir.mkdir()
        with tarfile.open(source_archive, "r:gz") as archive:
            archive.extractall(offline_dir)
        offline_context = offline_dir / "offline"
        export_offline_inputs(args.repo_root, args.online_image, offline_context, log)

        if not args.skip_offline_verify:
            build_offline(args, offline_dir, log)
            copy_image_tree(args.offline_image, "/static/client", output / "offline-static-client", cwd=args.repo_root, log=log)
            offline_hashes = tree_hashes(output / "offline-static-client")
            if online_hashes != offline_hashes:
                raise RuntimeError("offline frontend output differs from online build")
        else:
            offline_hashes = {}

        files = []
        for path in sorted(output.rglob("*")):
            if path.is_file() and path.name != "manifest.json":
                files.append({
                    "path": path.relative_to(output).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                })
        manifest = {
            "bundle_version": 1,
            "commit": commit,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "node_image": args.node_image,
            "python_image": args.python_image,
            "online_image": args.online_image,
            "offline_image": args.offline_image,
            "offline_verified": not args.skip_offline_verify,
            "online_static_client_sha256": online_hashes,
            "offline_static_client_sha256": offline_hashes,
            "files": files,
            "offline_command": (
                "docker load --input images/node-image.tar && "
                "docker load --input images/python-image.tar && "
                "docker buildx build --file deploy/Dockerfile --target frontend-builder "
                "--network=none "
                "--output type=image,name=memory-palace-frontend-offline:latest ."
            ),
            "duration_seconds": round(time.time() - started, 2),
        }
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "build-transcript.log").write_text("\n".join(log), encoding="utf-8")
    except Exception:
        (output / "build-transcript.log").write_text("\n".join(log), encoding="utf-8")
        raise
    print(json.dumps({"output": str(output), "manifest": str(output / "manifest.json"), "offline_verified": not args.skip_offline_verify}, ensure_ascii=False))


if __name__ == "__main__":
    main()
