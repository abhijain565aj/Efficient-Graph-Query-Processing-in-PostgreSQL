import MetricCard from './MetricCard.jsx';

export default function StatsPanel({ stats }) {
  const map = Object.fromEntries((stats || []).map((s) => [s.table_name, s.rows]));
  return (
    <div className="metrics-grid">
      <MetricCard label="Users" value={map.accounts || '—'} hint="social graph nodes" />
      <MetricCard label="Memes" value={map.memes || '—'} hint="recommendable items" />
      <MetricCard label="Edges" value={map.account_account || '—'} hint="directed follows" />
      <MetricCard label="Likes" value={map.account_liked_meme || '—'} hint="social signal" />
      <MetricCard label="Views" value={map.account_viewed_meme || '—'} hint="recent-view filter" />
    </div>
  );
}
