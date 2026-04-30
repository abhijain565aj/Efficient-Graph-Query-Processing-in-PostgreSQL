-- Exact and approximate graph/recommendation functions.
-- Exact = recursive SQL baseline.
-- Approx online = bounded recursion and bounded fanout inside request.
-- Cached = industry-style serving path: precompute bounded neighborhood for hot users,
--          then only run cheap indexed lookups online.

CREATE OR REPLACE FUNCTION refresh_meme_daily_stats()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    -- Parallel hash aggregation can require large Docker shared-memory segments.
    -- For repeatable laptop-scale loading, keep this derived-table refresh single-process.
    PERFORM set_config('max_parallel_workers_per_gather', '0', true);

    TRUNCATE meme_daily_stats;

    INSERT INTO meme_daily_stats (meme_id, total_likes, recent_likes_7d, recent_likes_30d, last_like_at, approx_global_rank)
    SELECT
        lm.meme_id,
        COUNT(*)::BIGINT AS total_likes,
        COUNT(*) FILTER (WHERE lm.liked_at >= now() - interval '7 days')::BIGINT AS recent_likes_7d,
        COUNT(*) FILTER (WHERE lm.liked_at >= now() - interval '30 days')::BIGINT AS recent_likes_30d,
        MAX(lm.liked_at) AS last_like_at,
        (
            LN(1 + COUNT(*))
            + 3.0 * LN(1 + COUNT(*) FILTER (WHERE lm.liked_at >= now() - interval '7 days'))
            + 1.5 * LN(1 + COUNT(*) FILTER (WHERE lm.liked_at >= now() - interval '30 days'))
        )::REAL AS approx_global_rank
    FROM account_liked_meme lm
    GROUP BY lm.meme_id;

    ANALYZE meme_daily_stats;
END;
$$;

CREATE OR REPLACE FUNCTION fn_khop_neighbors_exact(
    p_user_id BIGINT,
    p_k INTEGER DEFAULT 2,
    p_max_neighbors INTEGER DEFAULT 100000
)
RETURNS TABLE (neighbor_id BIGINT, distance INTEGER)
LANGUAGE sql
STABLE
AS $$
    WITH RECURSIVE bfs(node_id, distance, path) AS (
        SELECT aa.dst, 1, ARRAY[p_user_id, aa.dst]
        FROM account_account aa
        WHERE aa.src = p_user_id

        UNION ALL

        SELECT aa.dst, bfs.distance + 1, bfs.path || aa.dst
        FROM bfs
        JOIN account_account aa ON aa.src = bfs.node_id
        WHERE bfs.distance < p_k
          AND NOT aa.dst = ANY(bfs.path)
    ), dedup AS (
        SELECT node_id AS neighbor_id, MIN(distance) AS distance
        FROM bfs
        WHERE node_id <> p_user_id
        GROUP BY node_id
    )
    SELECT neighbor_id, distance
    FROM dedup
    ORDER BY distance, neighbor_id
    LIMIT p_max_neighbors;
$$;

CREATE OR REPLACE FUNCTION fn_khop_neighbors_approx(
    p_user_id BIGINT,
    p_k INTEGER DEFAULT 2,
    p_degree_cap INTEGER DEFAULT 8,
    p_max_neighbors INTEGER DEFAULT 2000
)
RETURNS TABLE (neighbor_id BIGINT, distance INTEGER)
LANGUAGE sql
STABLE
AS $$
    WITH RECURSIVE frontier(node_id, distance) AS (
        SELECT seed.dst, 1
        FROM LATERAL (
            SELECT aa.dst
            FROM account_account aa
            WHERE aa.src = p_user_id
            ORDER BY aa.strength DESC, aa.dst
            LIMIT p_degree_cap
        ) seed

        UNION ALL

        SELECT nxt.dst, frontier.distance + 1
        FROM frontier
        JOIN LATERAL (
            SELECT aa.dst
            FROM account_account aa
            WHERE aa.src = frontier.node_id
              AND aa.dst <> p_user_id
            ORDER BY aa.strength DESC, aa.dst
            LIMIT p_degree_cap
        ) nxt ON TRUE
        WHERE frontier.distance < p_k
    ), dedup AS (
        SELECT node_id AS neighbor_id, MIN(distance) AS distance
        FROM frontier
        WHERE node_id <> p_user_id
        GROUP BY node_id
    )
    SELECT neighbor_id, distance
    FROM dedup
    ORDER BY distance, neighbor_id
    LIMIT p_max_neighbors;
$$;

CREATE OR REPLACE FUNCTION refresh_neighbor_cache_for_user(
    p_user_id BIGINT,
    p_k INTEGER DEFAULT 2,
    p_degree_cap INTEGER DEFAULT 8,
    p_max_neighbors INTEGER DEFAULT 2000
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    DELETE FROM account_neighbor_cache WHERE user_id = p_user_id;

    INSERT INTO account_neighbor_cache (user_id, neighbor_id, distance, rank_score, generated_at)
    SELECT
        p_user_id,
        n.neighbor_id,
        n.distance::SMALLINT,
        (1.0 / n.distance)::REAL AS rank_score,
        now()
    FROM fn_khop_neighbors_approx(p_user_id, p_k, p_degree_cap, p_max_neighbors) n
    ON CONFLICT (user_id, neighbor_id) DO UPDATE SET
        distance = EXCLUDED.distance,
        rank_score = EXCLUDED.rank_score,
        generated_at = EXCLUDED.generated_at;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

CREATE OR REPLACE FUNCTION fn_feed_exact(
    p_user_id BIGINT,
    p_k INTEGER DEFAULT 2,
    p_limit INTEGER DEFAULT 30,
    p_view_window_days INTEGER DEFAULT 30
)
RETURNS TABLE (
    meme_id INTEGER,
    title TEXT,
    category TEXT,
    score DOUBLE PRECISION,
    neighbor_like_count BIGINT,
    closest_distance INTEGER,
    reason TEXT
)
LANGUAGE sql
STABLE
AS $$
    WITH neighbors AS (
        SELECT * FROM fn_khop_neighbors_exact(p_user_id, p_k, 200000)
    ), candidate_likes AS (
        SELECT
            lm.meme_id,
            COUNT(*)::BIGINT AS neighbor_like_count,
            MIN(n.distance) AS closest_distance,
            MAX(lm.liked_at) AS freshest_like_at,
            SUM(lm.weight / n.distance::DOUBLE PRECISION) AS social_score
        FROM neighbors n
        JOIN account_liked_meme lm ON lm.account_id = n.neighbor_id
        GROUP BY lm.meme_id
    ), filtered AS (
        SELECT c.*
        FROM candidate_likes c
        WHERE NOT EXISTS (
            SELECT 1
            FROM account_viewed_meme v
            WHERE v.account_id = p_user_id
              AND v.meme_id = c.meme_id
              AND v.viewed_at >= now() - make_interval(days => p_view_window_days)
        )
    ), ranked AS (
        SELECT
            m.id AS meme_id,
            m.title,
            m.category,
            (
                f.social_score
                + 0.25 * LN(1 + f.neighbor_like_count)
                + 0.10 * COALESCE(s.approx_global_rank, 0)
                + 0.05 * m.quality_score
                + 0.10 / (1 + EXTRACT(EPOCH FROM (now() - f.freshest_like_at)) / 86400.0)
            )::DOUBLE PRECISION AS score,
            f.neighbor_like_count,
            f.closest_distance,
            'exact recursive k-hop social score'::TEXT AS reason
        FROM filtered f
        JOIN memes m ON m.id = f.meme_id
        LEFT JOIN meme_daily_stats s ON s.meme_id = f.meme_id
    )
    SELECT *
    FROM ranked
    ORDER BY score DESC, meme_id
    LIMIT p_limit;
$$;

CREATE OR REPLACE FUNCTION fn_feed_approx(
    p_user_id BIGINT,
    p_k INTEGER DEFAULT 2,
    p_limit INTEGER DEFAULT 30,
    p_view_window_days INTEGER DEFAULT 30,
    p_degree_cap INTEGER DEFAULT 8,
    p_likes_per_neighbor INTEGER DEFAULT 12,
    p_exploration_ratio DOUBLE PRECISION DEFAULT 0.10
)
RETURNS TABLE (
    meme_id INTEGER,
    title TEXT,
    category TEXT,
    score DOUBLE PRECISION,
    neighbor_like_count BIGINT,
    closest_distance INTEGER,
    reason TEXT
)
LANGUAGE sql
STABLE
AS $$
    WITH params AS (
        SELECT
            GREATEST(1, FLOOR(p_limit * (1.0 - p_exploration_ratio))::INTEGER) AS social_limit,
            GREATEST(0, p_limit - GREATEST(1, FLOOR(p_limit * (1.0 - p_exploration_ratio))::INTEGER)) AS explore_limit
    ), neighbors AS (
        SELECT * FROM fn_khop_neighbors_approx(p_user_id, p_k, p_degree_cap, 2000)
    ), bounded_likes AS (
        SELECT
            n.neighbor_id,
            n.distance,
            lm.meme_id,
            lm.liked_at,
            lm.weight
        FROM neighbors n
        JOIN LATERAL (
            SELECT lm.meme_id, lm.liked_at, lm.weight
            FROM account_liked_meme lm
            WHERE lm.account_id = n.neighbor_id
            ORDER BY lm.liked_at DESC
            LIMIT p_likes_per_neighbor
        ) lm ON TRUE
    ), social_candidates AS (
        SELECT
            bl.meme_id,
            COUNT(*)::BIGINT AS neighbor_like_count,
            MIN(bl.distance) AS closest_distance,
            MAX(bl.liked_at) AS freshest_like_at,
            SUM(bl.weight / bl.distance::DOUBLE PRECISION) AS social_score
        FROM bounded_likes bl
        GROUP BY bl.meme_id
    ), filtered_social AS (
        SELECT sc.*
        FROM social_candidates sc
        WHERE NOT EXISTS (
            SELECT 1
            FROM account_viewed_meme v
            WHERE v.account_id = p_user_id
              AND v.meme_id = sc.meme_id
              AND v.viewed_at >= now() - make_interval(days => p_view_window_days)
        )
    ), social_ranked AS (
        SELECT
            m.id AS meme_id,
            m.title,
            m.category,
            (
                fs.social_score
                + 0.35 * LN(1 + fs.neighbor_like_count)
                + 0.15 * COALESCE(s.approx_global_rank, 0)
                + 0.08 * m.quality_score
                + 0.15 / (1 + EXTRACT(EPOCH FROM (now() - fs.freshest_like_at)) / 86400.0)
            )::DOUBLE PRECISION AS score,
            fs.neighbor_like_count,
            fs.closest_distance,
            'online bounded traversal'::TEXT AS reason
        FROM filtered_social fs
        JOIN memes m ON m.id = fs.meme_id
        LEFT JOIN meme_daily_stats s ON s.meme_id = fs.meme_id
        ORDER BY score DESC, meme_id
        LIMIT (SELECT social_limit FROM params)
    ), exploration AS (
        SELECT
            m.id AS meme_id,
            m.title,
            m.category,
            (0.10 * s.approx_global_rank + 0.05 * m.quality_score)::DOUBLE PRECISION AS score,
            s.total_likes::BIGINT AS neighbor_like_count,
            999 AS closest_distance,
            'indexed trending fallback'::TEXT AS reason
        FROM meme_daily_stats s
        JOIN memes m ON m.id = s.meme_id
        WHERE NOT EXISTS (
            SELECT 1
            FROM account_viewed_meme v
            WHERE v.account_id = p_user_id
              AND v.meme_id = s.meme_id
              AND v.viewed_at >= now() - make_interval(days => p_view_window_days)
        )
          AND NOT EXISTS (SELECT 1 FROM social_ranked sr WHERE sr.meme_id = s.meme_id)
        ORDER BY s.approx_global_rank DESC, s.meme_id
        LIMIT GREATEST(0, (SELECT explore_limit FROM params))
    )
    SELECT * FROM social_ranked
    UNION ALL
    SELECT * FROM exploration
    ORDER BY score DESC, meme_id
    LIMIT p_limit;
$$;

CREATE OR REPLACE FUNCTION make_feed_cache_key(
    p_k INTEGER,
    p_view_window_days INTEGER,
    p_degree_cap INTEGER,
    p_likes_per_neighbor INTEGER,
    p_exploration_ratio DOUBLE PRECISION
)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CONCAT(
        'k=', p_k,
        '|vw=', p_view_window_days,
        '|dc=', p_degree_cap,
        '|lpn=', p_likes_per_neighbor,
        '|er=', ROUND(p_exploration_ratio::NUMERIC, 3)
    );
$$;

CREATE OR REPLACE FUNCTION refresh_feed_cache_for_user(
    p_user_id BIGINT,
    p_k INTEGER DEFAULT 2,
    p_cache_items INTEGER DEFAULT 200,
    p_view_window_days INTEGER DEFAULT 30,
    p_degree_cap INTEGER DEFAULT 8,
    p_likes_per_neighbor INTEGER DEFAULT 12,
    p_exploration_ratio DOUBLE PRECISION DEFAULT 0.10
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_key TEXT;
    v_count INTEGER;
BEGIN
    v_key := make_feed_cache_key(p_k, p_view_window_days, p_degree_cap, p_likes_per_neighbor, p_exploration_ratio);

    DELETE FROM account_feed_cache
    WHERE user_id = p_user_id
      AND cache_key = v_key;

    INSERT INTO account_feed_cache (
        user_id, cache_key, rank_index, meme_id, score,
        neighbor_like_count, closest_distance, reason, generated_at
    )
    SELECT
        p_user_id,
        v_key,
        ROW_NUMBER() OVER (ORDER BY f.score DESC, f.meme_id)::INTEGER AS rank_index,
        f.meme_id,
        f.score,
        f.neighbor_like_count,
        f.closest_distance,
        'precomputed ' || f.reason,
        now()
    FROM fn_feed_approx(
        p_user_id,
        p_k,
        p_cache_items,
        p_view_window_days,
        p_degree_cap,
        p_likes_per_neighbor,
        p_exploration_ratio
    ) f
    ON CONFLICT (user_id, cache_key, meme_id) DO UPDATE SET
        rank_index = EXCLUDED.rank_index,
        score = EXCLUDED.score,
        neighbor_like_count = EXCLUDED.neighbor_like_count,
        closest_distance = EXCLUDED.closest_distance,
        reason = EXCLUDED.reason,
        generated_at = EXCLUDED.generated_at;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

CREATE OR REPLACE FUNCTION fn_feed_cached(
    p_user_id BIGINT,
    p_k INTEGER DEFAULT 2,
    p_limit INTEGER DEFAULT 30,
    p_view_window_days INTEGER DEFAULT 30,
    p_degree_cap INTEGER DEFAULT 8,
    p_likes_per_neighbor INTEGER DEFAULT 12,
    p_exploration_ratio DOUBLE PRECISION DEFAULT 0.10,
    p_cache_items INTEGER DEFAULT 200
)
RETURNS TABLE (
    meme_id INTEGER,
    title TEXT,
    category TEXT,
    score DOUBLE PRECISION,
    neighbor_like_count BIGINT,
    closest_distance INTEGER,
    reason TEXT
)
LANGUAGE plpgsql
AS $$
#variable_conflict use_column
DECLARE
    v_key TEXT;
BEGIN
    v_key := make_feed_cache_key(p_k, p_view_window_days, p_degree_cap, p_likes_per_neighbor, p_exploration_ratio);

    -- Self-healing fallback for demos: the first uncached request computes the feed once.
    -- Benchmark scripts prime this table before timing, so measured cached latency is the
    -- production serving-path latency: an indexed lookup and small primary-key joins only.
    IF NOT EXISTS (
        SELECT 1
        FROM account_feed_cache c
        WHERE c.user_id = p_user_id
          AND c.cache_key = v_key
        LIMIT 1
    ) THEN
        PERFORM refresh_feed_cache_for_user(
            p_user_id,
            p_k,
            GREATEST(p_limit, p_cache_items),
            p_view_window_days,
            p_degree_cap,
            p_likes_per_neighbor,
            p_exploration_ratio
        );
    END IF;

    RETURN QUERY
    SELECT
        fc.meme_id,
        m.title,
        m.category,
        fc.score,
        fc.neighbor_like_count,
        fc.closest_distance,
        fc.reason || ' [feed-cache hit]' AS reason
    FROM account_feed_cache fc
    JOIN memes m ON m.id = fc.meme_id
    WHERE fc.user_id = p_user_id
      AND fc.cache_key = v_key
    ORDER BY fc.rank_index
    LIMIT p_limit;
END;
$$;

CREATE OR REPLACE VIEW v_dataset_stats AS
SELECT 'accounts' AS table_name, COUNT(*)::BIGINT AS rows FROM accounts
UNION ALL SELECT 'memes', COUNT(*) FROM memes
UNION ALL SELECT 'account_account', COUNT(*) FROM account_account
UNION ALL SELECT 'account_liked_meme', COUNT(*) FROM account_liked_meme
UNION ALL SELECT 'account_viewed_meme', COUNT(*) FROM account_viewed_meme
UNION ALL SELECT 'meme_daily_stats', COUNT(*) FROM meme_daily_stats
UNION ALL SELECT 'account_neighbor_cache', COUNT(*) FROM account_neighbor_cache
UNION ALL SELECT 'account_feed_cache', COUNT(*) FROM account_feed_cache;
