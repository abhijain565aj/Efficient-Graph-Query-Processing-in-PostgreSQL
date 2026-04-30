import { useEffect, useMemo, useState } from 'react';
import { buildComparePath, buildFeedPath, getJson, postJson } from './api.js';
import FeedTable from './components/FeedTable.jsx';
import MetricCard from './components/MetricCard.jsx';
import StatsPanel from './components/StatsPanel.jsx';

const MODE_LABELS = {
  exact: 'Exact recursive SQL',
  approx: 'Online bounded approx',
  cached: 'Precomputed feed cache',
};

const MODE_DESCRIPTIONS = {
  exact: 'Correctness baseline: recursive k-hop traversal is done during the request.',
  approx: 'Bounds the traversal fanout and recent likes per neighbor during the request.',
  cached: 'Production-style path: ranked feed is precomputed, then served by indexed lookup.',
};

function formatMs(x) {
  if (x === undefined || x === null || Number.isNaN(Number(x))) return '—';
  return `${Number(x).toFixed(2)} ms`;
}

function paramText(mode, result, compare) {
  const p = result?.params || {};
  if (mode === 'exact') {
    return `k=${p.k ?? compare?.k ?? '—'}, limit=${p.limit ?? compare?.limit ?? '—'}, recent-view window=${p.viewWindowDays ?? 30}d`;
  }
  if (mode === 'approx') {
    return `k=${p.k ?? compare?.k ?? '—'}, degree cap=${p.degreeCap ?? 16}, likes/neighbor=${p.likesPerNeighbor ?? 24}, limit=${p.limit ?? compare?.limit ?? '—'}`;
  }
  return `k=${p.k ?? compare?.k ?? '—'}, cache items=${p.cacheItems ?? compare?.defaults?.cached?.cacheItems ?? 250}, limit=${p.limit ?? compare?.limit ?? '—'}`;
}

function ModeSummary({ mode, result, compare, active, onClick }) {
  const ok = result?.ok !== false;
  return (
    <button className={`mode-card ${active ? 'active' : ''}`} onClick={onClick} type="button">
      <div className="mode-topline">
        <span>{MODE_LABELS[mode]}</span>
        <strong>{ok ? formatMs(result?.latencyMs) : 'failed'}</strong>
      </div>
      <p>{MODE_DESCRIPTIONS[mode]}</p>
      <div className="mode-params">{paramText(mode, result, compare)}</div>
      {result?.error && <div className="mode-error">{result.error}</div>}
    </button>
  );
}

function ComparisonTable({ compare }) {
  const rows = ['exact', 'approx', 'cached'];
  return (
    <div className="table-wrap compact-table">
      <table>
        <thead>
          <tr>
            <th>Mode</th>
            <th>Latency</th>
            <th>Rows</th>
            <th>What is timed?</th>
            <th>Parameters used</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((mode) => {
            const r = compare?.modes?.[mode];
            return (
              <tr key={mode}>
                <td><strong>{MODE_LABELS[mode]}</strong></td>
                <td>{r?.ok === false ? 'failed' : formatMs(r?.latencyMs)}</td>
                <td>{r?.items?.length ?? '—'}</td>
                <td>{MODE_DESCRIPTIONS[mode]}</td>
                <td>{paramText(mode, r, compare)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function App() {
  const [userId, setUserId] = useState(42);
  const [k, setK] = useState(2);
  const [limit, setLimit] = useState(20);
  const [compare, setCompare] = useState(null);
  const [focusedMode, setFocusedMode] = useState('cached');
  const [individual, setIndividual] = useState(null);
  const [stats, setStats] = useState([]);
  const [error, setError] = useState('');
  const [apiStatus, setApiStatus] = useState('checking');
  const [loading, setLoading] = useState(false);
  const [individualLoading, setIndividualLoading] = useState(false);

  const comparePath = useMemo(() => buildComparePath({ userId, k, limit }), [userId, k, limit]);

  async function checkHealth() {
    try {
      await getJson('/health');
      setApiStatus('online');
    } catch (e) {
      setApiStatus('offline');
      setError(`Backend not reachable. Start with ./app.sh. Details: ${e.message}`);
    }
  }

  async function loadStats() {
    try {
      const data = await getJson('/api/stats');
      setStats(data.stats || []);
    } catch (e) {
      setError(e.message);
    }
  }

  async function runComparison() {
    setLoading(true);
    setError('');
    setIndividual(null);
    try {
      const data = await getJson(comparePath);
      setCompare(data);
      setFocusedMode('cached');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function refreshCache() {
    setLoading(true);
    setError('');
    try {
      await postJson(`/api/users/${userId}/refresh-feed-cache?k=${k}&limit=${limit}&cacheItems=250`);
      await runComparison();
    } catch (e) {
      setError(e.message);
      setLoading(false);
    }
  }

  async function runIndividual(mode) {
    setIndividualLoading(true);
    setError('');
    try {
      const data = await getJson(buildFeedPath({ userId, mode, k, limit }));
      setIndividual(data);
      setFocusedMode(mode);
    } catch (e) {
      setError(e.message);
    } finally {
      setIndividualLoading(false);
    }
  }

  useEffect(() => {
    checkHealth();
    loadStats();
  }, []);

  const focused = individual || compare?.modes?.[focusedMode];

  return (
    <div className="page">
      <header className="hero">
        <div>
          <div className="eyebrow">CS349 Database Systems Project</div>
          <h1>MemeGraph</h1>
          <p>
            Compare exact recursive SQL, online bounded approximation, and precomputed feed-cache serving
            for the same user and k-hop query in one view.
          </p>
        </div>
        <div className="hero-badge">
          <span>API: {apiStatus}</span>
          <span>PostgreSQL graph queries</span>
          <span>Approx + cached serving</span>
        </div>
      </header>

      <StatsPanel stats={stats} />

      <section className="panel controls simple-controls">
        <div>
          <label>User ID</label>
          <input type="number" value={userId} min="1" onChange={(e) => setUserId(Number(e.target.value))} />
        </div>
        <div>
          <label>k-hop distance</label>
          <select value={k} onChange={(e) => setK(Number(e.target.value))}>
            <option value={1}>1 hop</option>
            <option value={2}>2 hops</option>
            <option value={3}>3 hops</option>
          </select>
        </div>
        <div>
          <label>Results per mode</label>
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            <option value={10}>10 memes</option>
            <option value={20}>20 memes</option>
            <option value={30}>30 memes</option>
            <option value={50}>50 memes</option>
          </select>
        </div>
        <button onClick={runComparison} disabled={loading}>{loading ? 'Comparing...' : 'Compare all 3 modes'}</button>
        <button className="dark" onClick={refreshCache} disabled={loading} title="Recompute account_feed_cache for this user and k before comparing">
          Rebuild cache + compare
        </button>
      </section>

      {error && <div className="error">{error}</div>}

      <section className="panel explanation tight">
        <h2>Parameters are fixed per mode to keep the demo clear</h2>
        <p>
          Exact uses only k-hop and recent-view filtering. Approx uses <code>degreeCap=16</code> and <code>likesPerNeighbor=24</code>.
          Cached uses <code>cacheItems=250</code> and serves from <code>account_feed_cache</code>. These values are shown next to each mode below.
        </p>
      </section>

      <section className="mode-grid">
        {['exact', 'approx', 'cached'].map((mode) => (
          <ModeSummary
            key={mode}
            mode={mode}
            result={compare?.modes?.[mode]}
            compare={compare}
            active={focusedMode === mode && !individual}
            onClick={() => { setFocusedMode(mode); setIndividual(null); }}
          />
        ))}
      </section>

      <section className="metrics-grid">
        <MetricCard label="Cache build latency" value={compare ? formatMs(compare.primeCache?.latencyMs) : '—'} hint="only for cached mode preparation" />
        <MetricCard label="Cached items built" value={compare?.primeCache?.cachedItems ?? '—'} hint="account_feed_cache rows" />
        <MetricCard label="Total compare time" value={compare ? formatMs(compare.totalLatencyMs) : '—'} hint="includes exact + approx + cached" />
        <MetricCard label="Response cache" value={compare?.responseCache || '—'} hint="short TTL API response cache" />
      </section>

      {compare && (
        <section className="panel">
          <div className="section-heading">
            <h2>One-view comparison</h2>
            <p>Same user, same k-hop, three serving strategies.</p>
          </div>
          <ComparisonTable compare={compare} />
        </section>
      )}

      <section className="panel individual-panel">
        <div className="section-heading">
          <h2>Individual mode view</h2>
          <p>Click a mode card above or run one mode directly.</p>
        </div>
        <div className="mode-actions">
          {['exact', 'approx', 'cached'].map((mode) => (
            <button key={mode} type="button" onClick={() => runIndividual(mode)} disabled={individualLoading}>
              {individualLoading ? 'Running...' : `Run ${mode}`}
            </button>
          ))}
        </div>
        <div className="focus-header">
          <strong>{individual ? `${MODE_LABELS[individual.mode]} (individual run)` : MODE_LABELS[focusedMode]}</strong>
          <span>{focused?.ok === false ? focused.error : formatMs(focused?.latencyMs)}</span>
        </div>
        <FeedTable items={focused?.items || []} />
      </section>
    </div>
  );
}
