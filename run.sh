#!/bin/bash
# Memory Palace OS - Quick Start Script

set -e

echo "Starting Memory Palace OS..."

# 1. Install dependencies
pip install -r requirements.txt

# 2. Create data directory
mkdir -p data/chroma

# 3. Initialize database
python -c "from src.memory_palace.knowledge.db_init import init_db; import asyncio; asyncio.run(init_db())"

# 4. Seed initial data
python -c "from src.memory_palace.knowledge.data_seeder import seed_data; import asyncio; asyncio.run(seed_data())"

# 5. Start server
uvicorn src.memory_palace.main:app --host 0.0.0.0 --port 8000 --reload
