const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const compression = require('compression');
const morgan = require('morgan');
const { pool } = require('./db');
const { TinyTtlCache } = require('./cache');
const { parsePositiveInt, feedQuery, neighborsQuery } = require('./queries');

const app = express();
const port = Number(process.env.BACKEND_PORT || 4000);
const responseCache = new TinyTtlCache({ max: 5000, ttlMs: Number(process.env.FEED_CACHE_TTL_MS || 5000) });

app.use(helmet());
app.use(cors());
app.use(compression());
app.use(express.json({ limit: '1mb' }));
app.use(morgan(process.env.NODE_ENV === 'production' ? 'combined' : 'dev'));

function modeFromQuery(q) {
  if (q.mode === 'exact') return 'exact';
  if (q.mode === 'cached') return 'cached';
  return 'approx';
}

function cacheKey(req) {
  return `${req.path}:${JSON.stringify(req.query)}`;
}

async function timedQuery(text, values) {
  const started = process.hrtime.bigint();
  const result = await pool.query(text, values);
  const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
  return { result, elapsedMs };
}

function commonFrontendParams(query) {
  return {
    k: parsePositiveInt(query.k, 2, { min: 1, max: 5 }),
    limit: parsePositiveInt(query.limit, 20, { min: 1, max: 100 }),
    viewWindowDays: parsePositiveInt(query.viewWindowDays, 30, { min: 1, max: 365 }),
    // Opinionated defaults: frontend intentionally keeps these fixed to avoid parameter confusion.
    degreeCap: parsePositiveInt(query.degreeCap, 16, { min: 1, max: 128 }),
    likesPerNeighbor: parsePositiveInt(query.likesPerNeighbor, 24, { min: 1, max: 200 }),
    cacheItems: parsePositiveInt(query.cacheItems || query.cacheNeighbors, 250, { min: 30, max: 5000 }),
  };
}

async function runFeedMode(userId, mode, params) {
  const q = feedQuery(mode);
  const queryObj = {
    mode,
    k: params.k,
    limit: params.limit,
    viewWindowDays: params.viewWindowDays,
    degreeCap: params.degreeCap,
    likesPerNeighbor: params.likesPerNeighbor,
    cacheNeighbors: params.cacheItems,
  };
  const values = q.paramBuilder(userId, queryObj);
  const { result, elapsedMs } = await timedQuery(q.text, values);
  return {
    ok: true,
    mode,
    latencyMs: elapsedMs,
    params: mode === 'exact'
      ? { k: params.k, limit: params.limit, viewWindowDays: params.viewWindowDays }
      : mode === 'approx'
        ? { k: params.k, limit: params.limit, viewWindowDays: params.viewWindowDays, degreeCap: params.degreeCap, likesPerNeighbor: params.likesPerNeighbor }
        : { k: params.k, limit: params.limit, viewWindowDays: params.viewWindowDays, cacheItems: params.cacheItems },
    items: result.rows,
  };
}

app.get('/', (_req, res) => {
  res.type('html').send(`<!doctype html>
<html><head><title>MemeGraph API</title><style>
body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:840px;margin:40px auto;padding:0 20px;line-height:1.6;color:#172033;background:#f5f7fb}
.card{background:white;border-radius:18px;padding:24px;box-shadow:0 12px 35px rgba(40,62,100,.08)}
code{background:#eef3ff;padding:2px 6px;border-radius:6px} a{color:#2d5bff;font-weight:700}
</style></head><body><div class="card">
<h1>MemeGraph backend is running</h1>
<p>This is the API server. Open the React UI at <a href="http://localhost:5173">http://localhost:5173</a>.</p>
<p>Useful endpoints: <code>/health</code>, <code>/api/stats</code>, <code>/api/users/42/feed/compare?k=2</code>, <code>/api/users/42/feed?mode=cached</code>.</p>
</div></body></html>`);
});

app.get('/health', async (_req, res) => {
  try {
    const { rows } = await pool.query('SELECT 1 AS ok');
    res.json({ ok: true, db: rows[0].ok === 1 });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

app.get('/api/stats', async (_req, res) => {
  try {
    const { result, elapsedMs } = await timedQuery('SELECT * FROM v_dataset_stats ORDER BY table_name', []);
    res.json({ latencyMs: elapsedMs, stats: result.rows });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/users/:id/refresh-neighbor-cache', async (req, res) => {
  const userId = parsePositiveInt(req.params.id, 1, { min: 1, max: Number.MAX_SAFE_INTEGER });
  const k = parsePositiveInt(req.query.k, 2, { min: 1, max: 5 });
  const degreeCap = parsePositiveInt(req.query.degreeCap, 16, { min: 1, max: 128 });
  const cacheNeighbors = parsePositiveInt(req.query.cacheNeighbors, 250, { min: 100, max: 100000 });
  try {
    const { result, elapsedMs } = await timedQuery(
      'SELECT refresh_neighbor_cache_for_user($1, $2, $3, $4) AS cached_neighbors',
      [userId, k, degreeCap, cacheNeighbors]
    );
    res.json({ ok: true, userId, k, degreeCap, cacheNeighbors, cachedNeighbors: result.rows[0].cached_neighbors, latencyMs: elapsedMs });
  } catch (err) {
    res.status(500).json({ error: err.message, userId });
  }
});

app.post('/api/users/:id/refresh-feed-cache', async (req, res) => {
  const userId = parsePositiveInt(req.params.id, 1, { min: 1, max: Number.MAX_SAFE_INTEGER });
  const params = commonFrontendParams(req.query);
  try {
    const { result, elapsedMs } = await timedQuery(
      'SELECT refresh_feed_cache_for_user($1, $2, $3, $4, $5, $6, 0.10) AS cached_items',
      [userId, params.k, params.cacheItems, params.viewWindowDays, params.degreeCap, params.likesPerNeighbor]
    );
    res.json({ ok: true, userId, ...params, cachedItems: result.rows[0].cached_items, latencyMs: elapsedMs });
  } catch (err) {
    res.status(500).json({ error: err.message, userId });
  }
});

app.post('/api/admin/refresh-stats', async (_req, res) => {
  try {
    const { elapsedMs } = await timedQuery('SELECT refresh_meme_daily_stats()', []);
    res.json({ ok: true, latencyMs: elapsedMs });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/users/:id/feed/compare', async (req, res) => {
  const userId = parsePositiveInt(req.params.id, 1, { min: 1, max: Number.MAX_SAFE_INTEGER });
  const params = commonFrontendParams(req.query);
  const started = process.hrtime.bigint();

  try {
    // Prime only the cached serving path before comparing. Exact and online-approx remain live request paths.
    const prime = await timedQuery(
      'SELECT refresh_feed_cache_for_user($1, $2, $3, $4, $5, $6, 0.10) AS cached_items',
      [userId, params.k, params.cacheItems, params.viewWindowDays, params.degreeCap, params.likesPerNeighbor]
    );

    const modes = {};
    for (const mode of ['exact', 'approx', 'cached']) {
      try {
        modes[mode] = await runFeedMode(userId, mode, params);
      } catch (err) {
        modes[mode] = { ok: false, mode, error: err.message, params };
      }
    }

    const totalLatencyMs = Number(process.hrtime.bigint() - started) / 1e6;
    const payload = {
      userId,
      k: params.k,
      limit: params.limit,
      defaults: {
        viewWindowDays: params.viewWindowDays,
        approx: { degreeCap: params.degreeCap, likesPerNeighbor: params.likesPerNeighbor },
        cached: { cacheItems: params.cacheItems },
      },
      primeCache: { latencyMs: prime.elapsedMs, cachedItems: prime.result.rows[0]?.cached_items ?? 0 },
      totalLatencyMs,
      responseCache: 'not-used-for-compare',
      modes,
    };
    return res.json(payload);
  } catch (err) {
    return res.status(500).json({ error: err.message, userId, params });
  }
});

app.get('/api/users/:id/feed', async (req, res) => {
  const userId = parsePositiveInt(req.params.id, 1, { min: 1, max: Number.MAX_SAFE_INTEGER });
  const mode = modeFromQuery(req.query);
  const key = cacheKey(req);
  const cached = responseCache.get(key);
  if (cached) return res.json({ ...cached, cache: 'hit' });

  try {
    const q = feedQuery(mode);
    const values = q.paramBuilder(userId, req.query);
    const { result, elapsedMs } = await timedQuery(q.text, values);
    const payload = {
      userId,
      mode,
      k: values[1],
      limit: values[2],
      latencyMs: elapsedMs,
      cache: 'miss',
      items: result.rows,
    };
    responseCache.set(key, payload);
    return res.json(payload);
  } catch (err) {
    return res.status(500).json({ error: err.message, mode, userId });
  }
});

app.get('/api/users/:id/neighbors', async (req, res) => {
  const userId = parsePositiveInt(req.params.id, 1, { min: 1, max: Number.MAX_SAFE_INTEGER });
  const mode = modeFromQuery(req.query);
  try {
    const q = neighborsQuery(mode);
    const values = q.paramBuilder(userId, req.query);
    const { result, elapsedMs } = await timedQuery(q.text, values);
    res.json({ userId, mode, k: parsePositiveInt(req.query.k, 2, { min: 1, max: 5 }), latencyMs: elapsedMs, items: result.rows });
  } catch (err) {
    res.status(500).json({ error: err.message, mode, userId });
  }
});

app.get('/api/memes/:id', async (req, res) => {
  const memeId = parsePositiveInt(req.params.id, 1, { min: 1, max: Number.MAX_SAFE_INTEGER });
  try {
    const { result, elapsedMs } = await timedQuery(
      `SELECT m.*, COALESCE(s.total_likes, 0) AS total_likes,
              COALESCE(s.recent_likes_7d, 0) AS recent_likes_7d,
              COALESCE(s.approx_global_rank, 0) AS approx_global_rank
       FROM memes m
       LEFT JOIN meme_daily_stats s ON s.meme_id = m.id
       WHERE m.id = $1`,
      [memeId]
    );
    if (!result.rows.length) return res.status(404).json({ error: 'meme not found' });
    res.json({ latencyMs: elapsedMs, item: result.rows[0] });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/benchmarks/latest', async (req, res) => {
  const limit = parsePositiveInt(req.query.limit, 50, { min: 1, max: 500 });
  try {
    const { result, elapsedMs } = await timedQuery(
      `SELECT * FROM benchmark_measurements ORDER BY measured_at DESC LIMIT $1`,
      [limit]
    );
    res.json({ latencyMs: elapsedMs, items: result.rows });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.use((req, res) => {
  res.status(404).json({ error: 'not found', path: req.path });
});

app.listen(port, () => {
  console.log(`MemeGraph backend listening on http://localhost:${port}`);
});
