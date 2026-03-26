"""
Semantic / Hybrid Search Service — zero external dependencies.

Approach:
  - On first call, builds an in-memory TF-IDF index from graph_nodes
    (node_id, label, type, and key metadata fields)
  - Query time: tokenise query → compute TF-IDF cosine similarity → rank nodes
  - Hybrid: combine TF-IDF score with exact substring match score
  - Results include node_id, label, type, score, and a snippet

Why TF-IDF over embeddings:
  - No API cost, no external model, works offline
  - Handles partial matches, rare tokens, and domain abbreviations (e.g. "SO", "PO")
  - Fast enough for ~700 nodes at query time
"""

import re, math, json
from collections import defaultdict
from typing import Optional
from app.db.connection import get_conn

# ── Index state (built once, reused) ─────────────────────────────────────────
_index_built = False
_idf: dict[str, float] = {}
_tf_docs: list[dict] = []       # [{node_id, label, type, text, tf: {token: float}, raw_meta}]
_node_lookup: dict[str, dict] = {}  # node_id → full node dict


def _tokenise(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, filter short tokens."""
    text = text.lower()
    tokens = re.findall(r"[a-z0-9]+", text)
    return [t for t in tokens if len(t) >= 2]


def _build_index():
    global _index_built, _idf, _tf_docs, _node_lookup

    conn = get_conn()
    rows = conn.execute(
        "SELECT node_id, node_type, ref_id, label, metadata FROM graph_nodes"
    ).fetchall()
    conn.close()

    docs = []
    df: dict[str, int] = defaultdict(int)   # document frequency

    for row in rows:
        meta = json.loads(row["metadata"] or "{}")
        # Build a rich text blob for each node
        parts = [
            row["label"] or "",
            row["node_type"] or "",
            row["ref_id"] or "",
        ]
        # Add key metadata values (amounts, dates, statuses)
        for k, v in meta.items():
            if v and str(v).strip():
                parts.append(str(v))

        text = " ".join(parts)
        tokens = _tokenise(text)

        # Term frequency (normalised)
        tf: dict[str, float] = defaultdict(float)
        for t in tokens:
            tf[t] += 1.0
        if tokens:
            max_freq = max(tf.values())
            for t in tf:
                tf[t] = tf[t] / max_freq  # normalise to [0, 1]

        for t in set(tokens):
            df[t] += 1

        node_dict = {
            "id": row["node_id"],
            "type": row["node_type"],
            "ref_id": row["ref_id"],
            "label": row["label"],
            "data": meta,
        }
        docs.append({
            "node_id": row["node_id"],
            "label": row["label"],
            "type": row["node_type"],
            "text": text,
            "tf": dict(tf),
            "node": node_dict,
        })
        _node_lookup[row["node_id"]] = node_dict

    N = len(docs)
    # IDF: log(N / (1 + df[t]))
    _idf = {t: math.log(N / (1 + df[t])) for t in df}

    # Precompute TF-IDF vector magnitude for each doc
    for doc in docs:
        magnitude = math.sqrt(sum(
            (doc["tf"].get(t, 0) * _idf.get(t, 0)) ** 2
            for t in doc["tf"]
        ))
        doc["magnitude"] = magnitude if magnitude > 0 else 1.0

    _tf_docs = docs
    _index_built = True


def _ensure_index():
    if not _index_built:
        _build_index()


def _tfidf_score(query_tokens: list[str], doc: dict) -> float:
    """Cosine similarity between query TF-IDF vector and document TF-IDF vector."""
    if not query_tokens:
        return 0.0

    # Query TF (raw count normalised)
    q_tf: dict[str, float] = defaultdict(float)
    for t in query_tokens:
        q_tf[t] += 1.0
    max_q = max(q_tf.values())
    q_vec = {t: (c / max_q) * _idf.get(t, 0) for t, c in q_tf.items()}

    # Dot product
    dot = sum(
        q_vec.get(t, 0) * doc["tf"].get(t, 0) * _idf.get(t, 0)
        for t in q_vec
    )
    # Query magnitude
    q_mag = math.sqrt(sum(v ** 2 for v in q_vec.values()))

    if q_mag == 0 or doc["magnitude"] == 0:
        return 0.0
    return dot / (q_mag * doc["magnitude"])


def _exact_score(query: str, doc: dict) -> float:
    """Bonus score for exact or near-exact substring matches."""
    q = query.lower()
    text = doc["text"].lower()
    label = doc["label"].lower() if doc["label"] else ""

    score = 0.0
    if q == label:                    score += 1.0   # exact label match
    elif label.startswith(q):         score += 0.6   # prefix match
    elif q in label:                  score += 0.4   # substring in label
    elif q in text:                   score += 0.2   # substring in full text
    # Bonus for node type matching query
    if q in doc["type"].lower():      score += 0.3
    return score


def semantic_search(
    query: str,
    limit: int = 10,
    node_type: Optional[str] = None,
) -> list[dict]:
    """
    Hybrid search: TF-IDF cosine similarity + exact substring match.
    Returns ranked list of nodes with scores.
    """
    _ensure_index()
    if not query or not query.strip():
        return []

    query = query.strip()
    tokens = _tokenise(query)

    results = []
    for doc in _tf_docs:
        # Optional type filter
        if node_type and doc["type"] != node_type:
            continue

        tfidf = _tfidf_score(tokens, doc)
        exact  = _exact_score(query, doc)
        score  = 0.6 * tfidf + 0.4 * exact   # hybrid weighted blend

        if score > 0.0:
            results.append({
                "node_id":  doc["node_id"],
                "label":    doc["label"],
                "type":     doc["type"],
                "ref_id":   doc["node"]["ref_id"],
                "score":    round(score, 4),
                "data":     doc["node"]["data"],
            })

    # Sort by score desc, then label alpha for ties
    results.sort(key=lambda r: (-r["score"], r["label"] or ""))
    return results[:limit]


def rebuild_index():
    """Force a full index rebuild (call after ETL re-run)."""
    global _index_built
    _index_built = False
    _build_index()
    return {"nodes_indexed": len(_tf_docs)}
