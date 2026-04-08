-- 1. Reachability from a source node
WITH RECURSIVE reach(node) AS (
    SELECT 1
    UNION
    SELECT e.dst
    FROM reach r
    JOIN edges e ON e.src = r.node
)
SELECT COUNT(*) AS reachable_nodes
FROM reach;

-- 2. k-hop neighborhood from a source node
WITH RECURSIVE khop(node, depth) AS (
    SELECT 1, 0
    UNION ALL
    SELECT e.dst, k.depth + 1
    FROM khop k
    JOIN edges e ON e.src = k.node
    WHERE k.depth < 3
)
SELECT COUNT(DISTINCT node) AS nodes_within_3_hops
FROM khop;

-- 3. BFS-style shortest path approximation between source and destination
WITH RECURSIVE bfs(node, depth, path) AS (
    SELECT 1, 0, ARRAY[1]
    UNION ALL
    SELECT e.dst, b.depth + 1, path || e.dst
    FROM bfs b
    JOIN edges e ON e.src = b.node
    WHERE b.depth < 6
      AND NOT (e.dst = ANY(path))
)
SELECT path, depth
FROM bfs
WHERE node = 25
ORDER BY depth
LIMIT 1;

-- 4. Mutual friends (common out-neighbors in directed representation)
SELECT e1.dst AS mutual_friend, COUNT(*)
FROM edges e1
JOIN edges e2 ON e1.dst = e2.dst
WHERE e1.src = 1 AND e2.src = 2
GROUP BY e1.dst
ORDER BY mutual_friend;

-- 5. Friend recommendation: 2-hop neighbors not already directly connected
SELECT e2.dst AS recommended_user, COUNT(*) AS support
FROM edges e1
JOIN edges e2 ON e1.dst = e2.src
LEFT JOIN edges direct ON direct.src = e1.src AND direct.dst = e2.dst
WHERE e1.src = 1
  AND e2.dst <> 1
  AND direct.dst IS NULL
GROUP BY e2.dst
ORDER BY support DESC, recommended_user
LIMIT 10;

-- 6. Contact tracing: people reached within 4 interactions
WITH RECURSIVE trace(person_id, depth) AS (
    SELECT 1, 0
    UNION ALL
    SELECT e.dst, t.depth + 1
    FROM trace t
    JOIN edges e ON e.src = t.person_id
    WHERE t.depth < 4
)
SELECT COUNT(DISTINCT person_id) AS traced_people
FROM trace;
