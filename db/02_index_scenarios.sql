-- Helper functions for repeatable index scenario benchmarking.
-- Usage: SELECT apply_index_scenario('optimized');

CREATE OR REPLACE FUNCTION drop_experiment_indexes()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    DROP INDEX IF EXISTS idx_account_account_src_strength_dst;
    DROP INDEX IF EXISTS idx_account_account_dst_src;
    DROP INDEX IF EXISTS idx_account_account_src;
    DROP INDEX IF EXISTS idx_account_account_dst;
    DROP INDEX IF EXISTS idx_liked_account_recent;
    DROP INDEX IF EXISTS idx_liked_meme_recent;
    DROP INDEX IF EXISTS idx_liked_account;
    DROP INDEX IF EXISTS idx_liked_meme;
    DROP INDEX IF EXISTS idx_viewed_account_recent_meme;
    DROP INDEX IF EXISTS idx_viewed_account_meme;
    DROP INDEX IF EXISTS idx_memes_category_created;
    DROP INDEX IF EXISTS idx_meme_daily_stats_rank;
    DROP INDEX IF EXISTS idx_neighbor_cache_user_dist_score;
    DROP INDEX IF EXISTS idx_feed_cache_user_key_rank;
    DROP INDEX IF EXISTS brin_liked_at;
    DROP INDEX IF EXISTS brin_viewed_at;
END;
$$;

CREATE OR REPLACE FUNCTION apply_index_scenario(p_scenario TEXT)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM drop_experiment_indexes();

    IF p_scenario = 'no_extra_index' THEN
        -- Primary-key indexes remain. No secondary/covering/BRIN/cache-serving indexes.
        NULL;

    ELSIF p_scenario = 'single_column' THEN
        CREATE INDEX IF NOT EXISTS idx_account_account_src ON account_account(src);
        CREATE INDEX IF NOT EXISTS idx_account_account_dst ON account_account(dst);
        CREATE INDEX IF NOT EXISTS idx_liked_account ON account_liked_meme(account_id);
        CREATE INDEX IF NOT EXISTS idx_liked_meme ON account_liked_meme(meme_id);
        CREATE INDEX IF NOT EXISTS idx_viewed_account_meme ON account_viewed_meme(account_id, meme_id);
        CREATE INDEX IF NOT EXISTS idx_neighbor_cache_user_dist_score ON account_neighbor_cache(user_id, distance, rank_score DESC, neighbor_id);
        CREATE INDEX IF NOT EXISTS idx_feed_cache_user_key_rank ON account_feed_cache(user_id, cache_key, rank_index) INCLUDE (meme_id, score, neighbor_like_count, closest_distance, reason, generated_at);

    ELSIF p_scenario = 'composite' THEN
        CREATE INDEX IF NOT EXISTS idx_account_account_src_strength_dst ON account_account(src, strength DESC, dst);
        CREATE INDEX IF NOT EXISTS idx_account_account_dst_src ON account_account(dst, src);
        CREATE INDEX IF NOT EXISTS idx_liked_account_recent ON account_liked_meme(account_id, liked_at DESC) INCLUDE (meme_id, weight);
        CREATE INDEX IF NOT EXISTS idx_viewed_account_recent_meme ON account_viewed_meme(account_id, viewed_at DESC, meme_id);
        CREATE INDEX IF NOT EXISTS idx_neighbor_cache_user_dist_score ON account_neighbor_cache(user_id, distance, rank_score DESC, neighbor_id);
        CREATE INDEX IF NOT EXISTS idx_feed_cache_user_key_rank ON account_feed_cache(user_id, cache_key, rank_index) INCLUDE (meme_id, score, neighbor_like_count, closest_distance, reason, generated_at);

    ELSIF p_scenario = 'optimized' THEN
        CREATE INDEX IF NOT EXISTS idx_account_account_src_strength_dst ON account_account(src, strength DESC, dst);
        CREATE INDEX IF NOT EXISTS idx_account_account_dst_src ON account_account(dst, src);
        CREATE INDEX IF NOT EXISTS idx_liked_account_recent ON account_liked_meme(account_id, liked_at DESC) INCLUDE (meme_id, weight);
        CREATE INDEX IF NOT EXISTS idx_liked_meme_recent ON account_liked_meme(meme_id, liked_at DESC) INCLUDE (account_id, weight);
        CREATE INDEX IF NOT EXISTS idx_viewed_account_recent_meme ON account_viewed_meme(account_id, viewed_at DESC, meme_id);
        CREATE INDEX IF NOT EXISTS idx_memes_category_created ON memes(category, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_meme_daily_stats_rank ON meme_daily_stats(approx_global_rank DESC, meme_id) INCLUDE (total_likes, recent_likes_7d, recent_likes_30d, last_like_at);
        CREATE INDEX IF NOT EXISTS idx_neighbor_cache_user_dist_score ON account_neighbor_cache(user_id, distance, rank_score DESC, neighbor_id);
        CREATE INDEX IF NOT EXISTS idx_feed_cache_user_key_rank ON account_feed_cache(user_id, cache_key, rank_index) INCLUDE (meme_id, score, neighbor_like_count, closest_distance, reason, generated_at);
        CREATE INDEX IF NOT EXISTS brin_liked_at ON account_liked_meme USING BRIN(liked_at);
        CREATE INDEX IF NOT EXISTS brin_viewed_at ON account_viewed_meme USING BRIN(viewed_at);

    ELSE
        RAISE EXCEPTION 'Unknown index scenario: %. Valid: no_extra_index, single_column, composite, optimized', p_scenario;
    END IF;

    ANALYZE;
    RETURN p_scenario;
END;
$$;
