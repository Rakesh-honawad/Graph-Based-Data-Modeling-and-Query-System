# O2C Intelligence — Graph-Based Data Modeling & Query System

> A context graph system with an LLM-powered natural-language query interface for SAP Order-to-Cash (O2C) data.
> Built with **React 18 + D3.js v7 + FastAPI + SQLite + Google Gemini / Groq**.

---

## 🔗 Live Demo & Repository

| | Link |
|---|---|
| 🌐 **Live Demo** | [graph-based-data-modeling-and-query-sandy.vercel.app](https://graph-based-data-modeling-and-query-sandy.vercel.app) |
| 📦 **GitHub** | [github.com/Rakesh-honawad/Graph-Based-Data-Modeling-and-Query-System](https://github.com/Rakesh-honawad/Graph-Based-Data-Modeling-and-Query-System) |

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Graph Model](#graph-model)
- [LLM Integration & Prompting Strategy](#llm-integration--prompting-strategy)
- [Guardrails](#guardrails)
- [Project Structure](#project-structure)
- [API Reference](#api-reference)
- [Setup & Running Locally](#setup--running-locally)
- [Example Queries](#example-queries)
- [Architecture Decisions & Tradeoffs](#architecture-decisions--tradeoffs)
- [Bonus Features Implemented](#bonus-features-implemented)
- [AI Session Logs](#ai-session-logs)

---

## Overview

Real-world SAP Order-to-Cash data is spread across many fragmented tables — sales orders, deliveries, billing documents, journal entries, payments — with no easy way to trace how they connect.

This system:

1. **Ingests** raw JSONL data from 19 SAP entity types and builds a unified relational graph in SQLite
2. **Visualises** that graph using D3.js force layout — expandable nodes, zoomable canvas, type filters
3. **Exposes a chat interface** where users ask questions in plain English
4. **Dynamically generates SQL** per query via an LLM (not a static FAQ) and executes it against the real database
5. Returns **data-grounded, natural-language answers** alongside highlighted graph nodes

This is not a retrieval-augmented FAQ. Every answer is backed by a freshly generated SQL query against live data.

---

## Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                          FRONTEND (React 18)                          │
│                                                                       │
│   ┌─────────────────────┐        ┌──────────────────────────────┐    │
│   │   Graph Panel        │        │      Chat Panel               │    │
│   │   D3 Force Layout    │◄──────►│  NL Input → API → Response   │    │
│   │   Expand / Zoom      │        │  SQL Reveal / Result Table    │    │
│   └─────────────────────┘        └──────────────────────────────┘    │
│              ▲                                  ▲                     │
│              │  REST / JSON                     │                     │
└──────────────┼──────────────────────────────────┼─────────────────────┘
               │                                  │
┌──────────────▼──────────────────────────────────▼─────────────────────┐
│                       BACKEND (FastAPI + Python)                       │
│                                                                        │
│  ┌──────────────┐  ┌────────────────┐  ┌────────────────────────────┐ │
│  │ graph_service│  │  chat_service  │  │     search_service         │ │
│  │ BFS subgraph │  │  NL→SQL→Answer │  │  Hybrid semantic search    │ │
│  │ expansion    │  │  + guardrails  │  │  over graph nodes          │ │
│  └──────┬───────┘  └───────┬────────┘  └────────────────────────────┘ │
│         │                  │                                           │
│         ▼                  ▼                                           │
│  ┌────────────────────────────────────────┐                           │
│  │           SQLite Database               │                           │
│  │  graph_nodes / graph_edges              │                           │
│  │  + 19 entity tables (O2C domain)        │                           │
│  └────────────────────────────────────────┘                           │
│                            ▲                                           │
│                   scripts/etl.py                                       │
└────────────────────────────────────────────────────────────────────────┘
                             ▲
                    data/raw/ (19 JSONL folders)
```

### Data Flow

```
Raw JSONL files
    │
    ▼
ETL (etl.py) — normalise, deduplicate, build graph_nodes + graph_edges
    │
    ▼
SQLite — single file, zero ops overhead, git-committable
    │
    ├──► graph_service  →  BFS expansion  →  D3 graph JSON
    │
    └──► chat_service   →  NL → LLM → SQL → execute → LLM → answer
```

---

## Tech Stack

| Layer | Technology | Reason |
|---|---|---|
| Frontend framework | React 18 | Component model + hooks |
| Graph visualisation | D3.js v7 | Force layout, zoom, SVG control |
| Backend framework | FastAPI | Async, auto OpenAPI docs, fast |
| Database | SQLite | Zero ops, portable, sufficient for ~700 nodes |
| LLM provider | Google Gemini / Groq | Free tier, fast inference |
| Deployment (frontend) | Vercel | Auto deploys from main branch |
| Deployment (backend) | Render | Free tier, Procfile-driven |
| Language | Python 3.10+, JavaScript (ES2022) | — |

---

## Graph Model

### Node Types

| Node Type | Description | Key Properties |
|---|---|---|
| `SalesOrder` | SAP sales order header | order_id, customer, net_value, currency, date |
| `SalesOrderItem` | Line item on a sales order | item_no, material, quantity, unit_price |
| `OutboundDelivery` | Shipment header | delivery_id, ship_to, actual_gi_date |
| `BillingDocument` | Invoice / credit note | billing_id, billing_type, net_value |
| `JournalEntry` | Accounting document | journal_id, posting_date, amount |
| `Payment` | Incoming payment record | payment_id, amount, payment_date |
| `Customer` | Business partner | customer_id, name, city, country |
| `Material` | Product / SKU | material_id, description, material_type |
| `Plant` | Shipping or production plant | plant_id, name, country |

### Edge Types (Relationships)

```
SalesOrder ──────────── has_item ──────────► SalesOrderItem
SalesOrderItem ─────── references ─────────► Material
SalesOrder ─────────── fulfilled_by ───────► OutboundDelivery
SalesOrder ─────────── invoiced_as ────────► BillingDocument
BillingDocument ─────── settled_by ─────────► Payment
BillingDocument ─────── recorded_in ────────► JournalEntry
OutboundDelivery ────── ships_from ─────────► Plant
Customer ───────────── placed ──────────────► SalesOrder
Customer ───────────── receives ────────────► OutboundDelivery
```

This models the complete **Order-to-Cash chain**: Customer → Order → Delivery → Billing → Payment → Accounting.

---

## LLM Integration & Prompting Strategy

### Two-Call Pattern

Every chat query follows a strict two-LLM-call pipeline:

```
User question
    │
    ▼
[1] Guardrail check ──── no O2C keywords? ──► reject (no LLM call made)
    │
    ▼
[2] LLM Call 1: NL → SQL
    │   System prompt includes:
    │   - Full SQLite schema (all 19 tables + graph_nodes/graph_edges)
    │   - 4 labelled few-shot Q&A examples
    │   - Strict JSON output format: { intent, sql, answer_template }
    │   - Instruction: SELECT only, no mutations
    ▼
[3] SQL safety check ─── contains DROP/DELETE/INSERT? ──► reject
    │
    ▼
[4] Execute SQL against SQLite (real data, zero fabrication)
    │
    ▼
[5] LLM Call 2: Results → natural language
    │   System prompt includes:
    │   - Original user question
    │   - The SQL that ran
    │   - The actual result rows (JSON)
    │   - Instruction: summarise faithfully, no invention
    ▼
Response: { answer, sql, rows, highlighted_nodes }
```

**Why two calls?** Call 1 is kept deterministic and structured (JSON output). Call 2 is flexible prose formatting. Mixing both into one call produces inconsistent SQL.

### Conversation Memory

The last 4 turns per session are included in each LLM request. Follow-up questions like *"What about last month?"* resolve correctly without re-stating the full context.

### Few-Shot Examples in System Prompt

The system prompt for Call 1 includes 4 domain-specific Q&A examples covering:
- Aggregation (top products by billing count)
- Trace queries (full O2C chain for a document)
- Diagnostic queries (orders with broken flow)
- Date-range filtering

---

## Guardrails

The system uses a layered guardrail approach to restrict queries to the O2C domain:

### Layer 1 — Keyword Gate (no LLM cost)

Before any LLM call, the user's question is checked for at least one O2C-domain keyword:

```
sales, order, delivery, billing, invoice, payment, customer,
material, product, journal, plant, document, shipment, item, flow
```

If none match → immediate rejection with:

> *"This system is designed to answer questions related to the provided SAP Order-to-Cash dataset only. Please ask about sales orders, deliveries, billing documents, payments, customers, or materials."*

### Layer 2 — SQL Safety Filter

After LLM Call 1, the generated SQL is checked:
- Must start with `SELECT`
- Must not contain `DROP`, `DELETE`, `INSERT`, `UPDATE`, `TRUNCATE`

Any violation → rejection without execution.

### Layer 3 — LLM System Prompt Reinforcement

The system prompt for Call 1 explicitly states:
- Only generate SELECT queries
- Only reference schema tables provided
- Return `null` for `sql` if the question cannot be answered from the data

### Examples of Rejected Prompts

| User Input | Rejection Reason |
|---|---|
| "Write a poem about logistics" | No O2C keywords |
| "What is the capital of France?" | No O2C keywords |
| "Show me all users and drop the table" | SQL safety filter |
| "Tell me a joke" | No O2C keywords |

---

## Project Structure

```
o2c-intelligence/
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx                        # Root: state + API orchestration
│   │   ├── components/
│   │   │   ├── Layout/
│   │   │   │   ├── TopBar.jsx             # Header + O2C pipeline indicator + status
│   │   │   │   └── TopBar.css
│   │   │   ├── Sidebar/
│   │   │   │   ├── Sidebar.jsx            # Entity type filter, search, KPI cards
│   │   │   │   └── Sidebar.css
│   │   │   ├── Graph/
│   │   │   │   ├── GraphPanel.jsx         # D3 canvas host + zoom + legend
│   │   │   │   ├── GraphPanel.css
│   │   │   │   ├── NodeDetail.jsx         # Selected node metadata side panel
│   │   │   │   └── NodeDetail.css
│   │   │   └── Chat/
│   │   │       ├── ChatPanel.jsx          # Message list + SQL reveal + results table
│   │   │       └── ChatPanel.css
│   │   ├── hooks/
│   │   │   ├── useGraph.js                # D3 lifecycle (init / render / zoom / highlight)
│   │   │   └── useChat.js                 # Session management + message history
│   │   ├── utils/
│   │   │   ├── api.js                     # All fetch calls, single source of truth
│   │   │   └── graphConstants.js          # Node colours, sizes, labels — edit once, applies everywhere
│   │   └── styles/
│   │       ├── tokens.css                 # CSS design tokens + keyframe animations
│   │       └── utils.css                  # Shared utility classes
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── main.py                        # FastAPI entry point, CORS, lifespan
│   │   ├── api/
│   │   │   └── routes.py                  # All HTTP endpoints
│   │   ├── services/
│   │   │   ├── graph_service.py           # BFS subgraph expansion, overview sampling
│   │   │   ├── chat_service.py            # NL→SQL two-call pipeline + guardrails + memory
│   │   │   └── search_service.py          # Hybrid text/semantic search over entities
│   │   └── db/
│   │       └── connection.py              # SQLite connection pool
│   ├── scripts/
│   │   └── etl.py                         # Raw JSONL ingestion → SQLite graph builder
│   └── requirements.txt
│
├── data/
│   └── raw/                               # 19 JSONL source folders (not committed, gitignored)
│
├── ai-session-logs/
│   └── claude-session-log-v2.md           # Full AI-assisted development transcript
│
├── Procfile                               # Render.com deployment command
├── render.yaml                            # Render infrastructure-as-code
└── README.md
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Server + DB readiness check |
| `GET` | `/api/graph/overview` | Initial graph load for render (sampled) |
| `GET` | `/api/graph/subgraph/{id}` | BFS neighbourhood expansion from a node |
| `GET` | `/api/graph/node-types` | Entity type counts for sidebar filter |
| `GET` | `/api/graph/semantic-search?q=` | Hybrid text search over graph nodes |
| `GET` | `/api/graph/flow/{id}` | Full O2C chain trace for a document |
| `GET` | `/api/analytics/summary` | KPI dashboard totals |
| `GET` | `/api/analytics/top-products` | Products ranked by billing document count |
| `GET` | `/api/analytics/graph-stats` | Degree centrality + hub node detection |
| `POST` | `/api/chat` | Natural language → SQL → answer |
| `DELETE` | `/api/chat/session/{id}` | Clear conversation memory for a session |
| `POST` | `/api/load` | Re-trigger ETL (reload data) |

Interactive Swagger docs available at `http://localhost:8000/docs`.

---

## Setup & Running Locally

### Prerequisites

- Python 3.10+
- Node.js 18+
- A free API key from [Google Gemini](https://ai.google.dev) or [Groq](https://console.groq.com)

### 1. Clone the repository

```bash
git clone https://github.com/Rakesh-honawad/Graph-Based-Data-Modeling-and-Query-System.git
cd Graph-Based-Data-Modeling-and-Query-System
```

### 2. Backend setup

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your LLM API key:
# GEMINI_API_KEY=your_key_here
# or
# GROQ_API_KEY=your_key_here
```

### 3. Place raw data

The raw dataset goes into `data/raw/` with this layout:

```
data/raw/
├── sales_order_headers/*.jsonl
├── sales_order_items/*.jsonl
├── outbound_delivery_headers/*.jsonl
├── outbound_delivery_items/*.jsonl
├── billing_documents/*.jsonl
├── billing_document_items/*.jsonl
├── journal_entries/*.jsonl
├── payments/*.jsonl
├── customers/*.jsonl
├── materials/*.jsonl
└── plants/*.jsonl
    ... (19 folders total)
```

### 4. Run ETL

```bash
cd backend
python scripts/etl.py
# This creates data/o2c_graph.db
```

### 5. Start the backend

```bash
uvicorn app.main:app --reload --port 8000
```

### 6. Start the frontend

```bash
cd frontend
npm install
npm start
# Opens at http://localhost:3000
```

### 7. Verify

```bash
curl http://localhost:8000/health
# Expected: { "status": "healthy", "db_ready": true }
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | One of these | Google Gemini API key |
| `GROQ_API_KEY` | One of these | Groq API key |
| `LLM_PROVIDER` | Optional | `gemini` (default) or `groq` |
| `DB_PATH` | Optional | Path to SQLite file (default: `../data/o2c_graph.db`) |

---

## Example Queries

These are all answerable through the chat interface:

| Query | What it demonstrates |
|---|---|
| "Trace the full flow for billing document 90504262" | Multi-hop BFS chain trace |
| "Which sales orders were delivered but never billed?" | Broken flow / gap detection |
| "Show me all orders for customer C1001 in the last quarter" | Filtered traversal + date range |
| "What is the total payment amount received this month?" | Aggregation with date filter |
| "Which plants handled the most deliveries?" | Entity ranking |

---

## Architecture Decisions & Tradeoffs

### SQLite over Neo4j

For ~700 nodes and ~2,000 edges, SQLite with two virtual graph tables (`graph_nodes` and `graph_edges`) achieves identical expressiveness to a dedicated graph database. BFS traversal is implemented in Python over SQL joins, which is fast enough at this scale. The tradeoff is that complex multi-hop Cypher-style queries require more hand-crafted SQL, but this is acceptable given that the LLM generates those queries dynamically.

Zero operational overhead — no separate database process, no authentication, no backups needed. The entire graph is a single `.db` file that can be version-controlled or attached to any FastAPI instance.

### D3.js via `useRef` — Not React State

The D3 simulation and zoom transform are stored in React refs, not state. This is intentional. D3 operates on the DOM at 60fps during tick updates; driving that through React's reconciler would produce continuous re-renders and degraded performance. The hook (`useGraph.js`) owns all D3 lifecycle events, and React is only involved when top-level data (nodes/edges) changes.

### Two-Call LLM Pattern

Separating NL→SQL (Call 1) and results→prose (Call 2) makes each call deterministic in its own domain. Call 1 can be evaluated and tested independently (is the SQL correct?). Call 2 can be swapped for a simpler template formatter without touching SQL logic. Mixing both into a single call produces inconsistent output.

### `zoomFit()` on Every Graph Load

After each data load, the graph auto-frames itself using `getBBox()` on the inner `<g>` group, applies a 0.85× scale factor, and centres the translate. This prevents the common D3 issue of graphs rendering off-screen or at 1:1 scale on large datasets.

### Single `graphConstants.js`

All visual properties (node colours, stroke widths, label fonts, sizes per entity type) live in a single file. Changing a node colour once propagates to the graph canvas, the sidebar legend, the node detail badge, and the TopBar pipeline strip simultaneously.

### Warm Stone Palette

The UI uses a cream/terracotta colour scheme rather than standard blue/purple. This was a deliberate choice to differentiate the tool visually from generic AI dashboards and improve readability across display types.

---

## Bonus Features Implemented

- ✅ **Natural language to SQL translation** — dynamic per query, not static
- ✅ **Node highlighting** — nodes referenced in a chat response are highlighted on the graph
- ✅ **Hybrid semantic search** — text + entity type search over graph nodes in the sidebar
- ✅ **Conversation memory** — last 4 turns per session; follow-up questions work naturally
- ✅ **SQL reveal** — users can expand each chat response to see the exact SQL that was run
- ✅ **Results table** — raw query results are shown in a collapsible table alongside the prose answer
- ✅ **KPI dashboard** — sidebar shows live aggregated metrics (total orders, total billing value, etc.)
- ✅ **Full O2C chain trace endpoint** — `/api/graph/flow/{id}` returns the complete chain for any document

---

## AI Session Logs

AI tools were used extensively throughout this project. Full session transcripts are available in:

```
ai-session-logs/
└── claude-session-log-v2.md    # Claude Code session — architecture, ETL, LLM pipeline, D3 hooks
```

The logs cover:
- Initial architecture decisions and tradeoff reasoning
- ETL design and JSONL schema discovery
- LLM prompting strategy iteration (single-call vs two-call, JSON output format)
- Guardrail design
- D3 `useRef` pattern for performance
- Debugging the BFS subgraph expansion
- Deployment configuration for Vercel + Render

---

## License

This project was built as part of a technical assignment. All SAP O2C dataset rights belong to their respective owners.
