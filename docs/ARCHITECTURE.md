# Architecture

MemeGraph separates correctness, approximation, and serving speed.

## Base tables

- `accounts`: users in the social graph.
- `memes`: recommendable meme objects.
- `account_account`: directed social edges.
- `account_liked_meme`: meme likes.
- `account_viewed_meme`: recent view events used for filtering. It uses a surrogate `view_id` primary key because repeated views of the same meme by the same user are valid in dense workloads.

## Derived tables

- `meme_daily_stats`: global/trending meme statistics.
- `account_neighbor_cache`: approximate k-hop neighbor cache for hot users.
- `account_feed_cache`: final precomputed ranked feed rows.

The cache tables are `UNLOGGED` because they are rebuildable from base events.

## Query modes

### Exact

`fn_feed_exact` uses `fn_khop_neighbors_exact`, which is a recursive CTE. It is the correctness baseline and demonstrates graph traversal inside PostgreSQL.

### Online approximate

`fn_feed_approx` uses bounded fanout and bounded recent-like lookups. It is approximate because it does not expand every possible neighbor and does not read all likes of every neighbor.

### Cached serving

`refresh_feed_cache_for_user` precomputes ranked feed rows using the approximate pipeline. `fn_feed_cached` serves the request by indexed lookup from `account_feed_cache`.

This is closer to production recommendation systems: expensive candidate generation happens offline or nearline; online requests must be predictable and fast.

## App layer

The Express backend exposes comparison endpoints. The React frontend intentionally exposes only a small set of controls and displays exact, approx, and cached results together for the same user/k query.
