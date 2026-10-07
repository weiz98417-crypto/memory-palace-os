# Handoff instructions

Read `REPRODUCE.md` before changing or running the project. Use the pinned Docker, Python, and frontend dependency files. Never commit `.env`, Docker secrets, database volumes, logs, model caches, `node_modules`, `.venv`, or generated runtime output. Keep the datasets in `evals/` and the portable knowledge fixtures in `artifacts/knowledge/` intact. Run focused tests and the relevant contract eval after changes.
