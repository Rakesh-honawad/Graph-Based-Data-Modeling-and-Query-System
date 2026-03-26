"""
API Routes — all endpoints for the O2C Intelligence system.

Grouped by domain:
  /graph/*       — graph exploration (overview, subgraph, search)
  /analytics/*   — KPI summary, graph statistics
  /chat          — NL → SQL → answer pipeline
  /load          — trigger ETL re-ingestion
"""

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from app.services.graph_service import get_subgraph, get_overview_graph, get_node_types
from app.services.search_service import semantic_search
from app.services.chat_service import answer_question
from app.db.connection import get_conn, DB_PATH

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_conn():
    """Return a DB connection or raise a 503 if the database is not ready."""
    try:
        return get_conn()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Graph endpoints ───────────────────────────────────────────────────────────

@router.get("/graph/overview", tags=["Graph"])
def graph_overview():
    """Return a representative sample of the graph for initial render."""
    try:
        return get_overview_graph()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/graph/subgraph/{node_id:path}", tags=["Graph"])
def subgraph(
    node_id: str,
    depth: int = Query(default=2, ge=1, le=3, description="BFS depth, 1–3 hops"),
):
    """Return the neighbourhood subgraph centred on a node."""
    try:
        return get_subgraph(node_id, depth)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/graph/node-types", tags=["Graph"])
def node_types():
    """Return all node types with counts, for sidebar legend."""
    try:
        return get_node_types()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/graph/nodes", tags=["Graph"])
def list_nodes(
    node_type: Optional[str] = None,
    limit: int = Query(default=100, le=500),
):
    """List graph nodes, optionally filtered by type."""
    conn = _safe_conn()
    try:
        if node_type:
            rows = conn.execute(
                "SELECT node_id, node_type, ref_id, label FROM graph_nodes WHERE node_type=? LIMIT ?",
                (node_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT node_id, node_type, ref_id, label FROM graph_nodes LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/graph/search", tags=["Graph"])
def search_nodes(q: str, limit: int = 20):
    """Simple text search over node labels and reference IDs."""
    conn = _safe_conn()
    try:
        rows = conn.execute(
            "SELECT node_id, node_type, ref_id, label FROM graph_nodes "
            "WHERE label LIKE ? OR ref_id LIKE ? LIMIT ?",
            (f"%{q}%", f"%{q}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/graph/semantic-search", tags=["Graph"])
def graph_semantic_search(q: str, limit: int = 8):
    """Hybrid (semantic + keyword) search over graph nodes."""
    try:
        results = semantic_search(q, limit)
        return {"results": results}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/graph/flow/{node_id:path}", tags=["Graph"])
def flow_trace(node_id: str):
    """
    Return the full O2C flow chain connected to a given node:
    SalesOrder → Delivery → BillingDoc → Payment → JournalEntry.
    """
    try:
        return get_subgraph(node_id, depth=3)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Analytics endpoints ───────────────────────────────────────────────────────

@router.get("/analytics/summary", tags=["Analytics"])
def analytics_summary():
    """KPI summary: counts, revenue totals, broken-flow indicators."""
    conn = _safe_conn()
    try:
        def scalar(sql, params=()):
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else 0

        total_so      = scalar("SELECT COUNT(*) FROM sales_order_headers")
        total_del     = scalar("SELECT COUNT(*) FROM outbound_delivery_headers")
        total_bill    = scalar("SELECT COUNT(*) FROM billing_document_headers")
        total_pay     = scalar("SELECT COUNT(*) FROM payments_accounts_receivable")
        total_revenue = scalar("SELECT COALESCE(SUM(amount_in_transaction_currency),0) FROM payments_accounts_receivable")
        total_cust    = scalar("SELECT COUNT(*) FROM business_partners")
        total_prod    = scalar("SELECT COUNT(*) FROM products")
        cancelled     = scalar("SELECT COUNT(*) FROM billing_document_headers WHERE is_cancelled=1")

        # Orders with no delivery
        no_del = scalar("""
            SELECT COUNT(*) FROM sales_order_headers so
            WHERE NOT EXISTS (
                SELECT 1 FROM outbound_delivery_items di
                WHERE di.reference_sales_order = so.sales_order
            )
        """)

        # Delivered but not billed
        del_not_billed = scalar("""
            SELECT COUNT(*) FROM sales_order_headers so
            WHERE EXISTS (
                SELECT 1 FROM outbound_delivery_items di
                WHERE di.reference_sales_order = so.sales_order
            )
            AND NOT EXISTS (
                SELECT 1 FROM billing_document_items bi
                JOIN outbound_delivery_items di2
                  ON bi.reference_delivery_doc = di2.delivery_document
                WHERE di2.reference_sales_order = so.sales_order
            )
        """)

        return {
            "total_sales_orders":     total_so,
            "total_deliveries":       total_del,
            "total_billing_docs":     total_bill,
            "total_payments":         total_pay,
            "total_revenue":          total_revenue,
            "total_customers":        total_cust,
            "total_products":         total_prod,
            "cancelled_billing_docs": cancelled,
            "orders_no_delivery":     no_del,
            "delivered_not_billed":   del_not_billed,
        }
    finally:
        conn.close()


@router.get("/analytics/top-products", tags=["Analytics"])
def top_products(limit: int = Query(default=10, le=50)):
    """Products ranked by number of associated billing documents."""
    conn = _safe_conn()
    try:
        rows = conn.execute("""
            SELECT
                COALESCE(pd.product_description, p.product) AS name,
                p.product,
                COUNT(DISTINCT bi.billing_document) AS bill_count
            FROM billing_document_items bi
            JOIN products p ON bi.material = p.product
            LEFT JOIN product_descriptions pd
                ON p.product = pd.product AND pd.language = 'EN'
            GROUP BY p.product
            ORDER BY bill_count DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/analytics/flow-status", tags=["Analytics"])
def flow_status():
    """Breakdown of delivery and billing statuses."""
    conn = _safe_conn()
    try:
        delivery_statuses = conn.execute("""
            SELECT overall_delivery_status AS status, COUNT(*) AS count
            FROM sales_order_headers
            GROUP BY overall_delivery_status
        """).fetchall()

        billing_statuses = conn.execute("""
            SELECT overall_billing_status AS status, COUNT(*) AS count
            FROM sales_order_headers
            GROUP BY overall_billing_status
        """).fetchall()

        return {
            "delivery_statuses": [dict(r) for r in delivery_statuses],
            "billing_statuses":  [dict(r) for r in billing_statuses],
        }
    finally:
        conn.close()


@router.get("/analytics/graph-stats", tags=["Analytics"])
def graph_stats():
    """
    Graph topology metrics:
    degree centrality, hub nodes, edge-type distribution, density.
    """
    conn = _safe_conn()
    try:
        out_deg, in_deg = {}, {}

        for row in conn.execute("SELECT src_node, COUNT(*) AS c FROM graph_edges GROUP BY src_node"):
            out_deg[row["src_node"]] = row["c"]
        for row in conn.execute("SELECT dst_node, COUNT(*) AS c FROM graph_edges GROUP BY dst_node"):
            in_deg[row["dst_node"]] = row["c"]

        all_nodes = set(out_deg) | set(in_deg)
        degree = {n: out_deg.get(n, 0) + in_deg.get(n, 0) for n in all_nodes}

        top_hub_ids = sorted(degree, key=lambda n: -degree[n])[:10]
        hubs = []
        for nid in top_hub_ids:
            row = conn.execute(
                "SELECT label, node_type FROM graph_nodes WHERE node_id=?", (nid,)
            ).fetchone()
            if row:
                hubs.append({
                    "node_id":    nid,
                    "label":      row["label"],
                    "type":       row["node_type"],
                    "degree":     degree[nid],
                    "in_degree":  in_deg.get(nid, 0),
                    "out_degree": out_deg.get(nid, 0),
                })

        edge_types = [
            dict(r) for r in conn.execute(
                "SELECT edge_type, COUNT(*) AS count FROM graph_edges GROUP BY edge_type ORDER BY count DESC"
            ).fetchall()
        ]

        total_nodes = conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
        total_edges = conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
        avg_degree  = round(sum(degree.values()) / len(degree), 2) if degree else 0
        max_degree  = max(degree.values()) if degree else 0
        density     = round(total_edges / (total_nodes * (total_nodes - 1)), 6) if total_nodes > 1 else 0

        return {
            "total_nodes":        total_nodes,
            "total_edges":        total_edges,
            "avg_degree":         avg_degree,
            "max_degree":         max_degree,
            "density":            density,
            "top_hubs":           hubs,
            "edge_type_distribution": edge_types,
        }
    finally:
        conn.close()


# ── Chat endpoint ─────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = "default"


@router.post("/chat", tags=["Chat"])
def chat(req: ChatRequest):
    """Accept a natural-language question and return a data-backed answer."""
    return answer_question(req.question, session_id=req.session_id or "default")


@router.delete("/chat/session/{session_id}", tags=["Chat"])
def clear_session(session_id: str):
    """Clear conversation memory for a given session."""
    from app.services.chat_service import _sessions
    _sessions.pop(session_id, None)
    return {"status": "ok", "message": f"Session '{session_id}' cleared"}


# ── ETL / data load ───────────────────────────────────────────────────────────

@router.post("/load", tags=["Admin"])
def trigger_load():
    """
    Trigger ETL re-ingestion without restarting the server.
    Runs scripts/etl.py as a subprocess.
    """
    import subprocess
    import sys
    from pathlib import Path

    etl_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "etl.py"
    if not etl_path.exists():
        raise HTTPException(status_code=404, detail=f"ETL script not found at {etl_path}")

    result = subprocess.run(
        [sys.executable, str(etl_path)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr[-2000:])

    return {"status": "ok", "message": "ETL completed successfully", "output": result.stdout[-1000:]}
