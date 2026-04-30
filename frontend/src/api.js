const API_BASE = import.meta.env.VITE_API_BASE || ''; // empty string uses Vite proxy in local dev

async function parseResponse(res) {
  const text = await res.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch { body = { error: text || 'Non-JSON response from backend' }; }
  if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
  return body;
}

export async function getJson(path) {
  const res = await fetch(`${API_BASE}${path}`);
  return parseResponse(res);
}

export async function postJson(path) {
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST' });
  return parseResponse(res);
}

export function buildComparePath({ userId, k, limit }) {
  const p = new URLSearchParams({
    k: String(k),
    limit: String(limit),
    // Keep algorithm-specific parameters fixed and explicit in the UI cards.
    viewWindowDays: '30',
    degreeCap: '16',
    likesPerNeighbor: '24',
    cacheItems: '250',
  });
  return `/api/users/${userId}/feed/compare?${p.toString()}`;
}

export function buildFeedPath({ userId, mode, k, limit }) {
  const p = new URLSearchParams({
    mode,
    k: String(k),
    limit: String(limit),
    viewWindowDays: '30',
    degreeCap: '16',
    likesPerNeighbor: '24',
    cacheNeighbors: '250',
  });
  return `/api/users/${userId}/feed?${p.toString()}`;
}
