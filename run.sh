#!/usr/bin/env bash
set -euo pipefail

python_bin="${PYTHON_BIN:-python3}"
python_version="$($python_bin -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$python_version" != "3.11" && "$python_version" != "3.12" ]]; then
  echo "Memory Palace OS requires Python 3.11 or 3.12; found $python_version" >&2
  exit 2
fi

"$python_bin" -m pip install -r requirements.txt
mkdir -p data
exec "$python_bin" -m uvicorn main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
