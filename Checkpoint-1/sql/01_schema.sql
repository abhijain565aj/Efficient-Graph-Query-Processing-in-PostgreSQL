DROP TABLE IF EXISTS edges;
DROP TABLE IF EXISTS nodes;

CREATE TABLE nodes (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    node_type TEXT NOT NULL DEFAULT 'person'
);

CREATE TABLE edges (
    src INTEGER NOT NULL REFERENCES nodes(id),
    dst INTEGER NOT NULL REFERENCES nodes(id),
    weight INTEGER NOT NULL DEFAULT 1,
    interaction_type TEXT NOT NULL DEFAULT 'generic',
    PRIMARY KEY (src, dst)
);
