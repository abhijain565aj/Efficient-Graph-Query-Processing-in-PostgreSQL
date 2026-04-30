CREATE INDEX IF NOT EXISTS idx_edges_src_dst ON edges(src, dst);
CREATE INDEX IF NOT EXISTS idx_edges_dst_src ON edges(dst, src);
