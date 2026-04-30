# Project Report: MemeGraph PostgreSQL Recommendation Benchmark

## Problem

We study how PostgreSQL can support graph-like recommendation workloads using relational schema, recursive SQL, indexes, and approximation.

The application is a social-media meme feed. A request for user `u` should:

1. find accounts within `k` hops,
2. collect memes liked by those accounts,
3. filter memes recently viewed by `u`,
4. mix in a small trending/exploration component,
5. rank candidates by social score, recency, popularity, and quality.

## Main database challenge

Exact k-hop traversal expands rapidly on dense graphs. Even if PostgreSQL can express the traversal using recursive CTEs, doing this for every feed request is not a good serving strategy at scale.

## Implemented approaches

### Exact recursive baseline

The exact query is implemented using recursive SQL. It is useful for correctness and for showing how relational systems evaluate graph traversal.

### Online bounded approximation

The approximate query limits:

- the number of outgoing edges expanded per frontier node,
- the number of recent likes read per neighbor,
- and the final candidate set.

This trades exactness for predictable latency.

### Precomputed feed cache

The cached path precomputes ranked feed rows in `account_feed_cache`. The online request then becomes an indexed lookup by `(user_id, cache_key, rank_index)`.

This is the intended industry-style optimization in the project.

## Benchmarking methodology

The benchmark runner measures normal `SELECT` latency and separately samples a few `EXPLAIN ANALYZE` plans. This keeps latency numbers closer to actual application behavior while preserving query-plan evidence.

We compare index scenarios:

- no extra index,
- single-column indexes,
- composite indexes,
- optimized covering/cache/trending indexes.

We evaluate multiple scales and densities:

- small / small_dense,
- medium / medium_dense,
- large / large_dense.

Dense variants are important because tiny sparse graphs can fit in memory and make all plans look similar.

## Expected conclusion

The exact recursive baseline is expressive and correct, but becomes unstable as k and density increase. Online approximation reduces the expansion cost. The precomputed feed-cache path gives the most predictable serving latency because it moves candidate generation out of the request path.
