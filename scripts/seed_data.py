"""
Demo seed data loader. Loads scenario YAMLs into in-memory cache + SQLite.

Usage:
    python scripts/seed_data.py --scenario daily
    python scripts/seed_data.py --scenario emergency --dry-run
"""

import os
import sys
import json
import argparse
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


async def load_scenario(name: str, dry_run: bool = False) -> dict:
    """Load seed data for a scenario."""
    seed_dir = Path(__file__).resolve().parent / "seed_data"
    yaml_path = seed_dir / f"{name}.yaml"

    if not yaml_path.exists():
        raise FileNotFoundError(f"Scenario file not found: {yaml_path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    result = {
        "scenario": data.get("scenario", name),
        "label": data.get("label", ""),
        "knowledge_count": 0,
        "persona_count": 0,
        "todo_count": 0,
    }

    if dry_run:
        result["knowledge_count"] = len(data.get("knowledge", []))
        result["persona_count"] = len(data.get("personas", []))
        result["todo_count"] = len(data.get("todos", []))
        return result

    # ── 1. Knowledge → In-memory cache ────────────────────────────────────
    knowledge_items = data.get("knowledge", [])
    try:
        from src.memory_palace.core.gateway import _demo_knowledge_cache
        _demo_knowledge_cache.clear()
        _demo_knowledge_cache.extend(knowledge_items)
    except ImportError:
        pass
    result["knowledge_count"] = len(knowledge_items)

    # ── 2. Personas + Todos (async) ──────────────────────────────────────
    from src.memory_palace.knowledge.db_client import db_client
    from src.memory_palace.core.task_graph import task_graph
    import uuid as _uuid
    import asyncio

    personas_data = data.get("personas", [])
    todos_data = data.get("todos", [])

    async def _insert_all():
        p_count = 0
        for persona in personas_data:
            persona_id = str(_uuid.uuid4())
            entries = persona.get("logic_entries", [])
            import time as _time
            now = _time.time()
            await db_client.execute(
                "INSERT INTO personas (id, venue_id, job_title, logic_entries, raw_answers, description, created_at, updated_at) VALUES (?, '', ?, ?, '{}', '', ?, ?)",
                (persona_id, persona.get("job_title", ""), json.dumps(entries, ensure_ascii=False), now, now),
            )
            p_count += 1

        t_count = 0
        for todo in todos_data:
            tasks = todo.get("expected_tasks", [])
            created_ids = []
            for i, t in enumerate(tasks):
                deps = [created_ids[d] for d in t.get("depends_on", []) if d < len(created_ids)]
                task = await task_graph.create_task(
                    session_id=f"demo_{name}",
                    description=t["description"],
                    dependencies=deps,
                    assigned_agent="todo_write"
                )
                created_ids.append(task.id)
            t_count += len(created_ids)
        return p_count, t_count

    try:
        loop = asyncio.get_running_loop()
        # Already inside an event loop (FastAPI), await directly
        p_count, t_count = await _insert_all()
    except RuntimeError:
        # No running loop, use asyncio.run()
        p_count, t_count = asyncio.run(_insert_all())
    result["persona_count"] = p_count
    result["todo_count"] = t_count

    return result


if __name__ == "__main__":
    import asyncio as _asyncio
    parser = argparse.ArgumentParser(description="Load demo seed data")
    parser.add_argument("--scenario", choices=["daily", "emergency"], required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = _asyncio.run(load_scenario(args.scenario, dry_run=args.dry_run))
    print(json.dumps(result, ensure_ascii=False, indent=2))
