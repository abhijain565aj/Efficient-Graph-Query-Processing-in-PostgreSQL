#!/usr/bin/env bash
set -e

docker compose down
docker compose up -d --force-recreate

echo "Waiting for PostgreSQL to become ready..."
until docker exec graph_pg_project pg_isready -U postgres -d graphdb >/dev/null 2>&1; do
  sleep 2
done

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate_data.py
export GRAPH_PG_CONNINFO="${GRAPH_PG_CONNINFO:-dbname=graphdb user=postgres password=postgres host=127.0.0.1 port=5433}"
python scripts/run_benchmarks.py
python scripts/plot_results.py

echo "Done. Check results/ for CSVs, plans, and plots."