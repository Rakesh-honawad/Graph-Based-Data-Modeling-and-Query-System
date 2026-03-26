// API client — works for both local & production

const API_BASE =
  process.env.REACT_APP_API_URL
    ? `${process.env.REACT_APP_API_URL}/api`
    : 'http://localhost:8000/api';

// Generic request handler
async function req(path, opts = {}) {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(opts.headers || {}),
      },
      ...opts,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({
        detail: `HTTP ${res.status}`,
      }));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }

    return res.json();
  } catch (error) {
    console.error('API Error:', error.message);
    throw error;
  }
}

// Graph APIs
export const graphApi = {
  overview: () => req('/graph/overview'),
  subgraph: (id, d = 2) =>
    req(`/graph/subgraph/${encodeURIComponent(id)}?depth=${d}`),
  nodeTypes: () => req('/graph/node-types'),
  search: (q, n = 8) =>
    req(`/graph/semantic-search?q=${encodeURIComponent(q)}&limit=${n}`),
  flow: (id) => req(`/graph/flow/${encodeURIComponent(id)}`),
};

// Analytics APIs
export const analyticsApi = {
  summary: () => req('/analytics/summary'),
  graphStats: () => req('/analytics/graph-stats'),
  topProducts: () => req('/analytics/top-products'),
  flowStatus: () => req('/analytics/flow-status'),
};

// Chat APIs
export const chatApi = {
  ask: (question, sessionId) =>
    req('/chat', {
      method: 'POST',
      body: JSON.stringify({
        question,
        session_id: sessionId,
      }),
    }),
  clear: (sessionId) =>
    req(`/chat/session/${sessionId}`, { method: 'DELETE' }),
};

// Health check
export const healthApi = {
  check: async () => {
    try {
      return await req('/health');
    } catch {
      return { status: 'unreachable' };
    }
  },
};