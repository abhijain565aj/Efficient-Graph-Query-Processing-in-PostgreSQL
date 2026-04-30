.PHONY: init-db \
	generate-small generate-medium generate-large generate-small-dense generate-medium-dense generate-large-dense \
	load-small load-medium load-large load-small-dense load-medium-dense load-large-dense \
	benchmark-small benchmark-medium benchmark-large benchmark-small-dense benchmark-medium-dense benchmark-large-dense \
	bench plot stress backend frontend clean clean-db

init-db:
	./scripts/init_db.sh

generate-small:
	python src/data_generation.py --preset small --out data/generated/small

generate-medium:
	python src/data_generation.py --preset medium --out data/generated/medium

generate-large:
	python src/data_generation.py --preset large --out data/generated/large

generate-small-dense:
	python src/data_generation.py --preset small_dense --out data/generated/small_dense

generate-medium-dense:
	python src/data_generation.py --preset medium_dense --out data/generated/medium_dense

generate-large-dense:
	python src/data_generation.py --preset large_dense --out data/generated/large_dense

load-small:
	./scripts/load_data.sh data/generated/small

load-medium:
	./scripts/load_data.sh data/generated/medium

load-large:
	./scripts/load_data.sh data/generated/large

load-small-dense:
	./scripts/load_data.sh data/generated/small_dense

load-medium-dense:
	./scripts/load_data.sh data/generated/medium_dense

load-large-dense:
	./scripts/load_data.sh data/generated/large_dense

benchmark-small:
	./scripts/run_dataset_benchmark.sh small

benchmark-medium:
	./scripts/run_dataset_benchmark.sh medium

benchmark-large:
	./scripts/run_dataset_benchmark.sh large

benchmark-small-dense:
	./scripts/run_dataset_benchmark.sh small_dense

benchmark-medium-dense:
	./scripts/run_dataset_benchmark.sh medium_dense

benchmark-large-dense:
	./scripts/run_dataset_benchmark.sh large_dense

bench:
	python src/run_benchmarks.py --users 50 --k-values 1 2 3 --modes exact approx cached --prime-cache --out analysis_outputs/benchmarks.csv

plot:
	python src/plotter.py --input analysis_outputs/benchmarks.csv --outdir analysis_outputs/plots

stress:
	python src/stress_test_api.py --base-url http://localhost:4000 --users 1000 --requests 2000 --concurrency 64 --mode cached --out analysis_outputs/api_stress.csv

backend:
	cd backend && npm install && npm run dev

frontend:
	cd frontend && npm install && npm run dev

clean:
	rm -rf data/generated/* analysis_outputs/*
	mkdir -p data/generated analysis_outputs
	touch data/generated/.gitkeep

clean-db:
	docker compose down -v
