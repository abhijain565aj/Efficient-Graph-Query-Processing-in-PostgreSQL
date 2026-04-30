function parsePositiveInt(value, fallback, { min = 1, max = 100000 } = {}) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}

function parseRatio(value, fallback) {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, Math.min(0.5, parsed));
}

function feedQuery(mode) {
  if (mode === 'exact') {
    return {
      text: 'SELECT * FROM fn_feed_exact($1, $2, $3, $4)',
      paramBuilder: (userId, q) => [
        userId,
        parsePositiveInt(q.k, 2, { min: 1, max: 4 }),
        parsePositiveInt(q.limit, 30, { min: 1, max: 100 }),
        parsePositiveInt(q.viewWindowDays, 30, { min: 1, max: 365 }),
      ],
    };
  }

  if (mode === 'cached') {
    return {
      text: 'SELECT * FROM fn_feed_cached($1, $2, $3, $4, $5, $6, $7, $8)',
      paramBuilder: (userId, q) => [
        userId,
        parsePositiveInt(q.k, 2, { min: 1, max: 5 }),
        parsePositiveInt(q.limit, 30, { min: 1, max: 100 }),
        parsePositiveInt(q.viewWindowDays, 30, { min: 1, max: 365 }),
        parsePositiveInt(q.degreeCap, 8, { min: 1, max: 128 }),
        parsePositiveInt(q.likesPerNeighbor, 12, { min: 1, max: 200 }),
        parseRatio(q.explorationRatio, 0.10),
        parsePositiveInt(q.cacheNeighbors, 250, { min: 100, max: 100000 }),
      ],
    };
  }

  return {
    text: 'SELECT * FROM fn_feed_approx($1, $2, $3, $4, $5, $6, $7)',
    paramBuilder: (userId, q) => [
      userId,
      parsePositiveInt(q.k, 2, { min: 1, max: 5 }),
      parsePositiveInt(q.limit, 30, { min: 1, max: 100 }),
      parsePositiveInt(q.viewWindowDays, 30, { min: 1, max: 365 }),
      parsePositiveInt(q.degreeCap, 8, { min: 1, max: 128 }),
      parsePositiveInt(q.likesPerNeighbor, 12, { min: 1, max: 200 }),
      parseRatio(q.explorationRatio, 0.10),
    ],
  };
}

function neighborsQuery(mode) {
  if (mode === 'exact') {
    return {
      text: 'SELECT * FROM fn_khop_neighbors_exact($1, $2, $3)',
      paramBuilder: (userId, q) => [
        userId,
        parsePositiveInt(q.k, 2, { min: 1, max: 4 }),
        parsePositiveInt(q.maxNeighbors, 1000, { min: 1, max: 100000 }),
      ],
    };
  }

  if (mode === 'cached') {
    return {
      text: `SELECT neighbor_id, distance
             FROM account_neighbor_cache
             WHERE user_id = $1
             ORDER BY distance, rank_score DESC, neighbor_id
             LIMIT $2`,
      paramBuilder: (userId, q) => [
        userId,
        parsePositiveInt(q.maxNeighbors, 100, { min: 1, max: 100000 }),
      ],
    };
  }

  return {
    text: 'SELECT * FROM fn_khop_neighbors_approx($1, $2, $3, $4)',
    paramBuilder: (userId, q) => [
      userId,
      parsePositiveInt(q.k, 2, { min: 1, max: 5 }),
      parsePositiveInt(q.degreeCap, 8, { min: 1, max: 128 }),
      parsePositiveInt(q.maxNeighbors, 1000, { min: 1, max: 100000 }),
    ],
  };
}

module.exports = { parsePositiveInt, feedQuery, neighborsQuery };
