// API client — all fetch calls in one place

const BASE = process.env.REACT_APP_API_URL
  ? `${process.env.REACT_APP_API_URL}/api`
  : (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
      ? 'http://localhost:8000/api'
      : `${window.location.origin}/api`);

async function req(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

export const graphApi = {
  overview:  ()           => req('/graph/overview'),
  subgraph:  (id, d = 2) => req(`/graph/subgraph/${encodeURIComponent(id)}?depth=${d}`),
  nodeTypes: ()           => req('/graph/node-types'),
  search:    (q, n = 8)  => req(`/graph/semantic-search?q=${encodeURIComponent(q)}&limit=${n}`),
  flow:      (id)         => req(`/graph/flow/${encodeURIComponent(id)}`),
};

export const analyticsApi = {
  summary:    () => req('/analytics/summary'),
  graphStats: () => req('/analytics/graph-stats'),
  topProducts:() => req('/analytics/top-products'),
  flowStatus: () => req('/analytics/flow-status'),
};

export const chatApi = {
  ask:   (question, sessionId) =>
    req('/chat', { method: 'POST', body: JSON.stringify({ question, session_id: sessionId }) }),
  clear: (sessionId) =>
    req(`/chat/session/${sessionId}`, { method: 'DELETE' }),
};

export const healthApi = {
  check: () => req('/health').catch(() => ({ status: 'unreachable' })),
};
