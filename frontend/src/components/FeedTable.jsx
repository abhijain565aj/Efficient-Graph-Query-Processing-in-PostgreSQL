export default function FeedTable({ items }) {
  if (!items?.length) {
    return <div className="empty">No recommendations returned yet. Run the comparison first.</div>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Rank</th>
            <th>Meme</th>
            <th>Category</th>
            <th>Score</th>
            <th>Neighbor likes</th>
            <th>Closest hop</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {items.map((m, idx) => (
            <tr key={`${m.meme_id}-${idx}`}>
              <td>{idx + 1}</td>
              <td>{m.title || `Meme ${m.meme_id}`}</td>
              <td><span className="pill">{m.category || 'unknown'}</span></td>
              <td>{Number(m.score || 0).toFixed(3)}</td>
              <td>{m.neighbor_like_count ?? '—'}</td>
              <td>{Number(m.closest_distance) === 999 ? 'explore' : (m.closest_distance ?? '—')}</td>
              <td>{m.reason || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
