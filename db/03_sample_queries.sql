-- Useful manual queries.

-- Dataset summary.
SELECT * FROM v_dataset_stats ORDER BY table_name;

-- Refresh popularity rollup after loading data.
SELECT refresh_meme_daily_stats();

-- Prime graph-neighbor cache for visualization.
SELECT refresh_neighbor_cache_for_user(42, 2, 10, 250);

-- Prime final feed cache for serving.
SELECT refresh_feed_cache_for_user(42, 2, 250, 30, 10, 14, 0.10);

-- Compare exact, online approximate and cached neighbors for one user.
SELECT * FROM fn_khop_neighbors_exact(42, 2, 100) LIMIT 20;
SELECT * FROM fn_khop_neighbors_approx(42, 2, 10, 100) LIMIT 20;
SELECT neighbor_id, distance
FROM account_neighbor_cache
WHERE user_id = 42
ORDER BY distance, rank_score DESC
LIMIT 20;

-- Feed recommendations.
SELECT * FROM fn_feed_exact(42, 2, 30, 30);
SELECT * FROM fn_feed_approx(42, 2, 30, 30, 10, 14, 0.10);
SELECT * FROM fn_feed_cached(42, 2, 30, 30, 10, 14, 0.10, 250);

-- Plan analysis. Do this on a few samples, not every benchmark query.
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT * FROM fn_feed_cached(42, 2, 30, 30, 10, 14, 0.10, 250);

-- Index scenario example.
SELECT apply_index_scenario('optimized');
