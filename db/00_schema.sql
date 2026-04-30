-- MemeGraph schema: social graph + meme interactions + benchmark metadata.
-- Designed for PostgreSQL 16+.
-- Derived/cache tables are UNLOGGED because they can be rebuilt from base events.

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

CREATE TABLE IF NOT EXISTS accounts (
    id          BIGINT PRIMARY KEY,
    username    TEXT NOT NULL,
    region_id   SMALLINT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memes (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    category      TEXT NOT NULL,
    creator_id    BIGINT,
    quality_score REAL NOT NULL DEFAULT 0.5,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Directed follow/connection edge. For undirected friendship datasets, load both (u,v) and (v,u).
CREATE TABLE IF NOT EXISTS account_account (
    src        BIGINT NOT NULL,
    dst        BIGINT NOT NULL,
    strength   REAL NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (src, dst),
    CHECK (src <> dst)
);

CREATE TABLE IF NOT EXISTS account_liked_meme (
    account_id BIGINT NOT NULL,
    meme_id    INTEGER NOT NULL,
    liked_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    weight     REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (account_id, meme_id)
);

-- Multiple views of the same meme are allowed, hence viewed_at participates in the key.
CREATE TABLE IF NOT EXISTS account_viewed_meme (
    account_id BIGINT NOT NULL,
    meme_id    INTEGER NOT NULL,
    viewed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, meme_id, viewed_at)
);

-- Derived candidate statistics. Rebuilt after bulk load; safe to keep unlogged.
CREATE UNLOGGED TABLE IF NOT EXISTS meme_daily_stats (
    meme_id            INTEGER PRIMARY KEY,
    total_likes        BIGINT NOT NULL DEFAULT 0,
    recent_likes_7d    BIGINT NOT NULL DEFAULT 0,
    recent_likes_30d   BIGINT NOT NULL DEFAULT 0,
    last_like_at       TIMESTAMPTZ,
    approx_global_rank REAL NOT NULL DEFAULT 0
);

-- Derived online-serving neighbor cache. This is the main industry-style serving optimization:
-- keep recursive traversal out of the request path for hot users.
CREATE UNLOGGED TABLE IF NOT EXISTS account_neighbor_cache (
    user_id      BIGINT NOT NULL,
    neighbor_id  BIGINT NOT NULL,
    distance     SMALLINT NOT NULL,
    rank_score   REAL NOT NULL DEFAULT 0,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, neighbor_id)
);


-- Derived final feed cache. This is the production-style optimization:
-- precompute candidate generation/ranking for active users and serve by indexed lookup.
CREATE UNLOGGED TABLE IF NOT EXISTS account_feed_cache (
    user_id             BIGINT NOT NULL,
    cache_key           TEXT NOT NULL,
    rank_index          INTEGER NOT NULL,
    meme_id             INTEGER NOT NULL,
    score               DOUBLE PRECISION NOT NULL,
    neighbor_like_count BIGINT NOT NULL,
    closest_distance    INTEGER NOT NULL,
    reason              TEXT NOT NULL,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, cache_key, rank_index),
    UNIQUE (user_id, cache_key, meme_id)
);

CREATE TABLE IF NOT EXISTS benchmark_runs (
    id             BIGSERIAL PRIMARY KEY,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    label          TEXT NOT NULL,
    index_scenario TEXT NOT NULL,
    dataset_label  TEXT NOT NULL,
    notes          TEXT
);

CREATE TABLE IF NOT EXISTS benchmark_measurements (
    id             BIGSERIAL PRIMARY KEY,
    run_id         BIGINT REFERENCES benchmark_runs(id) ON DELETE CASCADE,
    measured_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    query_name     TEXT NOT NULL,
    mode           TEXT NOT NULL,
    user_id        BIGINT NOT NULL,
    k              INTEGER NOT NULL,
    result_limit   INTEGER NOT NULL,
    latency_ms     DOUBLE PRECISION NOT NULL,
    planning_ms    DOUBLE PRECISION,
    execution_ms   DOUBLE PRECISION,
    returned_rows  INTEGER,
    buffers_hit    BIGINT,
    buffers_read   BIGINT
);

-- Optimized default indexes. These are recreated by db/02_index_scenarios.sql during experiments.
CREATE INDEX IF NOT EXISTS idx_account_account_src_strength_dst
    ON account_account (src, strength DESC, dst);

CREATE INDEX IF NOT EXISTS idx_account_account_dst_src
    ON account_account (dst, src);

CREATE INDEX IF NOT EXISTS idx_liked_account_recent
    ON account_liked_meme (account_id, liked_at DESC)
    INCLUDE (meme_id, weight);

CREATE INDEX IF NOT EXISTS idx_liked_meme_recent
    ON account_liked_meme (meme_id, liked_at DESC)
    INCLUDE (account_id, weight);

CREATE INDEX IF NOT EXISTS idx_viewed_account_recent_meme
    ON account_viewed_meme (account_id, viewed_at DESC, meme_id);

CREATE INDEX IF NOT EXISTS idx_memes_category_created
    ON memes (category, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_meme_daily_stats_rank
    ON meme_daily_stats (approx_global_rank DESC, meme_id)
    INCLUDE (total_likes, recent_likes_7d, recent_likes_30d, last_like_at);

CREATE INDEX IF NOT EXISTS idx_neighbor_cache_user_dist_score
    ON account_neighbor_cache (user_id, distance, rank_score DESC, neighbor_id);


CREATE INDEX IF NOT EXISTS idx_feed_cache_user_key_rank
    ON account_feed_cache (user_id, cache_key, rank_index)
    INCLUDE (meme_id, score, neighbor_like_count, closest_distance, reason, generated_at);

CREATE INDEX IF NOT EXISTS brin_liked_at
    ON account_liked_meme USING BRIN (liked_at);

CREATE INDEX IF NOT EXISTS brin_viewed_at
    ON account_viewed_meme USING BRIN (viewed_at);

ANALYZE;
