"""
Graph service — subgraph BFS expansion and overview graph.
Fixed BFS: frontier correctly tracks only newly discovered nodes per iteration.
"""

import json
from app.db.connection import get_conn


def get_subgraph(node_id: str, depth: int = 2) -> dict:
    """
    BFS from node_id up to `depth` hops.
    Returns all reachable nodes and the edges connecting them.
    """
    conn = get_conn()
    visited_nodes: set = set()
    visited_edges: set = set()
    all_nodes: dict = {}
    all_edges: list = []

    # Seed: just the starting node
    frontier = {node_id}

    for _ in range(depth):
        if not frontier:
            break

        frontier_list = list(frontier)
        placeholders  = ",".join("?" * len(frontier_list))

        # Fetch node metadata for the current frontier
        for row in conn.execute(
            f"SELECT node_id, node_type, ref_id, label, metadata "
            f"FROM graph_nodes WHERE node_id IN ({placeholders})",
            frontier_list,
        ):
            nid = row["node_id"]
            visited_nodes.add(nid)
            if nid not in all_nodes:
                all_nodes[nid] = {
                    "id": nid,
                    "type": row["node_type"],
                    "ref_id": row["ref_id"],
                    "label": row["label"],
                    "data": json.loads(row["metadata"] or "{}"),
                }

        # Fetch all edges touching the frontier (both directions)
        next_frontier: set = set()
        for row in conn.execute(
            f"SELECT edge_id, src_node, dst_node, edge_type, metadata "
            f"FROM graph_edges "
            f"WHERE src_node IN ({placeholders}) OR dst_node IN ({placeholders})",
            frontier_list + frontier_list,
        ):
            eid = row["edge_id"]
            if eid not in visited_edges:
                visited_edges.add(eid)
                all_edges.append({
                    "id": eid,
                    "source": row["src_node"],
                    "target": row["dst_node"],
                    "type": row["edge_type"],
                    "data": json.loads(row["metadata"] or "{}"),
                })
            # Discover new neighbors — only nodes not yet visited
            for neighbor in (row["src_node"], row["dst_node"]):
                if neighbor not in visited_nodes:
                    next_frontier.add(neighbor)

        frontier = next_frontier  # ← Fixed: only truly new nodes, not all unvisited

    # Resolve any neighbor nodes that were referenced in edges but not yet fetched
    missing = {
        n for e in all_edges
        for n in (e["source"], e["target"])
        if n not in all_nodes
    }
    if missing:
        ph = ",".join("?" * len(missing))
        for row in conn.execute(
            f"SELECT node_id, node_type, ref_id, label, metadata "
            f"FROM graph_nodes WHERE node_id IN ({ph})",
            list(missing),
        ):
            nid = row["node_id"]
            all_nodes[nid] = {
                "id": nid,
                "type": row["node_type"],
                "ref_id": row["ref_id"],
                "label": row["label"],
                "data": json.loads(row["metadata"] or "{}"),
            }

    conn.close()
    return {"nodes": list(all_nodes.values()), "edges": all_edges}


def get_overview_graph() -> dict:
    """
    Return a representative sample graph for the initial view.
    Loads a bounded number of each node type plus the edges connecting them.
    """
    conn = get_conn()
    nodes: dict = {}
    edges: list = []

    type_limits = {
        "Customer": 8,
        "Product": 20,
        "Plant": 15,
        "SalesOrder": 30,
        "Delivery": 25,
        "BillingDoc": 30,
        "Payment": 20,
        "JournalEntry": 20,
    }

    for ntype, limit in type_limits.items():
        for row in conn.execute(
            "SELECT node_id, node_type, ref_id, label, metadata "
            "FROM graph_nodes WHERE node_type=? LIMIT ?",
            (ntype, limit),
        ):
            nid = row["node_id"]
            nodes[nid] = {
                "id": nid,
                "type": row["node_type"],
                "ref_id": row["ref_id"],
                "label": row["label"],
                "data": json.loads(row["metadata"] or "{}"),
            }

    # Only include edges where BOTH endpoints are in the sampled set
    node_ids = list(nodes.keys())
    if node_ids:
        ph = ",".join("?" * len(node_ids))
        for row in conn.execute(
            f"SELECT edge_id, src_node, dst_node, edge_type, metadata "
            f"FROM graph_edges "
            f"WHERE src_node IN ({ph}) AND dst_node IN ({ph})",
            node_ids + node_ids,
        ):
            edges.append({
                "id": row["edge_id"],
                "source": row["src_node"],
                "target": row["dst_node"],
                "type": row["edge_type"],
                "data": json.loads(row["metadata"] or "{}"),
            })

    conn.close()
    return {"nodes": list(nodes.values()), "edges": edges}


def get_node_types() -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT node_type, COUNT(*) as cnt FROM graph_nodes GROUP BY node_type ORDER BY cnt DESC"
    ).fetchall()
    conn.close()
    return [{"type": r["node_type"], "count": r["cnt"]} for r in rows]


def search_nodes_by_ref(ref_id: str) -> dict | None:
    """Find a node by its domain ref_id (e.g. a billing doc number)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT node_id, node_type, ref_id, label, metadata "
        "FROM graph_nodes WHERE ref_id = ? LIMIT 1",
        (ref_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["node_id"],
        "type": row["node_type"],
        "ref_id": row["ref_id"],
        "label": row["label"],
        "data": json.loads(row["metadata"] or "{}"),
    }
