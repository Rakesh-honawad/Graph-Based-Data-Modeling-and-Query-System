# O2C Intelligence — Order to Cash Graph System

A context graph system with an LLM-powered natural-language query interface for SAP Order-to-Cash data.
Built with **React 18 + D3.js v7 + FastAPI + SQLite**.

---

## What It Does

- Ingests SAP O2C data into a SQLite graph (sales orders, deliveries, billing docs, payments, journal entries, customers, products, plants)
- Visualises the full relationship graph with D3 force layout — expandable, zoomable, filterable
- Accepts natural-language questions in a chat interface
- **Dynamically generates SQL** per question via Gemini/Groq LLM — not a static FAQ system
- Executes queries against the real database and returns data-grounded answers
- Highlights relevant graph nodes for every chat response

---

## Setup (5 minutes)

### Prerequisites
- Python 3.10+ · Node.js 18+ · A free [Gemini](https://ai.google.dev) or [Groq](https://console.groq.com) API key

### 1. Backend
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # add your API key here
```

### 2. Place raw data
```
data/raw/sales_order_headers/*.jsonl
data/raw/outbound_delivery_headers/*.jsonl
... (19 folders)
```

### 3. Run ETL
```bash
cd backend && python scripts/etl.py
```

### 4. Start API
```bash
uvicorn app.main:app --reload --port 8000
```

### 5. Start frontend
```bash
cd frontend && npm install && npm start
```

### 6. Verify
```
GET http://localhost:8000/health  →  { "status": "healthy", "db_ready": true }
```

---

## Project Structure

```
o2c-intelligence/
├── frontend/
│   ├── src/
│   │   ├── App.jsx                            # Root: state + API orchestration
│   │   ├── components/
│   │   │   ├── Layout/TopBar.jsx/.css         # Header + O2C pipeline strip + status
│   │   │   ├── Sidebar/Sidebar.jsx/.css       # Search, type filter, KPI cards
│   │   │   ├── Graph/GraphPanel.jsx/.css      # D3 canvas + zoom + legend
│   │   │   ├── Graph/NodeDetail.jsx/.css      # Selected-node metadata panel
│   │   │   └── Chat/ChatPanel.jsx/.css        # Messages + SQL reveal + results table
│   │   ├── hooks/
│   │   │   ├── useGraph.js                    # D3 lifecycle (init/render/zoom/highlight)
│   │   │   └── useChat.js                     # Session, message history
│   │   ├── utils/
│   │   │   ├── api.js                         # All fetch calls centralised
│   │   │   └── graphConstants.js              # Node colors, sizes, labels — single source
│   │   └── styles/
│   │       ├── tokens.css                     # Design tokens + keyframes
│   │       └── utils.css                      # Shared utility classes
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── main.py                            # FastAPI entry point
│   │   ├── api/routes.py                      # All endpoints
│   │   ├── services/
│   │   │   ├── graph_service.py               # BFS subgraph expansion
│   │   │   ├── chat_service.py                # NL→SQL, guardrails, memory
│   │   │   └── search_service.py              # Hybrid semantic search
│   │   └── db/connection.py                   # SQLite connection
│   ├── scripts/etl.py                         # Data ingestion + graph builder
│   └── requirements.txt
│
└── ai-session-logs/
    └── claude-session-log-v2.md               # Full AI-assisted development log
```

---

## LLM Integration — NL → SQL Pipeline

Every question follows this path:

```
User question
    │
    ▼
[1] Keyword guardrail ───── no O2C keywords? → reject (no LLM call)
    │
    ▼
[2] LLM call 1 ────────────── NL → { intent, sql, answer_template } JSON
    │                          Full schema context + 4 example Q&A pairs
    ▼
[3] SQL safety check ───────── not SELECT or contains DROP/DELETE? → reject
    │
    ▼
[4] Execute against SQLite ─── real data, not fabricated
    │
    ▼
[5] LLM call 2 ────────────── SQL results → natural language summary
    │
    ▼
Response: { answer, sql, rows, highlighted_nodes }
```

**Conversation memory:** last 4 turns per session — follow-up questions work naturally.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Server + DB readiness |
| GET | `/api/graph/overview` | Initial graph for render |
| GET | `/api/graph/subgraph/{id}` | BFS neighbourhood expansion |
| GET | `/api/graph/node-types` | Type counts for filter sidebar |
| GET | `/api/graph/semantic-search?q=` | Hybrid text search |
| GET | `/api/graph/flow/{id}` | Full O2C chain trace |
| GET | `/api/analytics/summary` | KPI dashboard |
| GET | `/api/analytics/top-products` | Products by billing count |
| GET | `/api/analytics/graph-stats` | Degree centrality + hub nodes |
| POST | `/api/chat` | NL → SQL → answer |
| DELETE | `/api/chat/session/{id}` | Clear conversation memory |
| POST | `/api/load` | Re-run ETL |

Interactive docs at `http://localhost:8000/docs`

---

## Architecture Decisions

**SQLite over Neo4j** — For ~700 nodes, SQLite with virtual graph tables (`graph_nodes` + `graph_edges`) achieves identical expressiveness. BFS in Python over SQL. Zero operational overhead.

**D3 via `useRef`** — Simulation and zoom stored in refs, not React state. 60fps tick updates never trigger re-renders.

**`zoomFit()` on every load** — Graph auto-frames after each data load. 0.85× scale + centred translate. Uses `getBBox()` on the inner `<g>` group.

**Warm stone palette** — Cream/terracotta instead of standard blue/purple. Distinguishes the tool from generic AI dashboards; reads well on all displays.

**Single `graphConstants.js`** — All node visual properties in one file. A single edit updates graph circles, sidebar legend, node detail badge, and TopBar all at once.

**Two-call LLM pattern** — Call 1 translates NL to SQL (structured, predictable). Call 2 formats results into prose (flexible, human-readable). The LLM never fabricates data — it only formats what SQL returned.
