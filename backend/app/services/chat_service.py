"""
Chat Service — NL→SQL with LLM + full rule-based fallback.

Priority order:
  1. Fast keyword guardrail (no LLM)
  2. LLM translates NL→SQL  (if available)
  3. Rule-based regex→SQL   (if LLM fails/rate-limited)
  4. Local formatter builds answer from raw rows (no LLM for summarisation)

The system ALWAYS returns data-backed answers even when rate-limited.
"""

import os, re, json
import urllib.request, urllib.error
from app.db.connection import get_conn

LLM_PROVIDER   = os.getenv("LLM_PROVIDER", "gemini").lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent?key={key}"
)
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama3-70b-8192"

DOMAIN_KEYWORDS = {
    "sales","order","delivery","billing","invoice","payment","customer",
    "product","material","plant","journal","accounting","document","shipment",
    "quantity","amount","currency","inr","flow","trace","status","cancelled",
    "billed","delivered","shipped","o2c","partner","business","fiscal",
    "clearing","transaction","revenue","average","total","count","list",
    "show","find","top","most","highest","lowest","broken","incomplete",
}

# ─────────────────────────────────────────────────────────────────────────────
# Rule-based SQL matcher — works with zero LLM calls
# ─────────────────────────────────────────────────────────────────────────────

_RULES = [

    # total billing (short query)
    (r"^total.{0,15}bill|^bill.{0,15}total|total.{0,10}invoic",
     """SELECT SUM(total_net_amount) AS total_billing_amount,
               COUNT(*) AS total_docs,
               SUM(CASE WHEN is_cancelled=1 THEN 1 ELSE 0 END) AS cancelled,
               transaction_currency
        FROM billing_document_headers GROUP BY transaction_currency""",
     lambda r: f"Total billing: {r[0]['transaction_currency']} {r[0]['total_billing_amount']:,.2f} across {r[0]['total_docs']} documents ({r[0]['cancelled']} cancelled)." if r else "No data."),

    # list/show products
    (r"(list|show|get|all|what).{0,20}(product|material|item)",
     """SELECT p.product, COALESCE(pd.product_description, p.product) AS description,
               p.product_type, p.product_group
        FROM products p
        LEFT JOIN product_descriptions pd ON p.product=pd.product AND pd.language='EN'
        ORDER BY p.product LIMIT 30""",
     lambda r: f"Found {len(r)} products. Examples: " + ", ".join(x.get('description', x['product']) for x in r[:5])),

    # list/show orders
    (r"(list|show|get|all).{0,20}(order|sales order)",
     """SELECT sales_order, sold_to_party, total_net_amount,
               transaction_currency, overall_delivery_status, creation_date
        FROM sales_order_headers ORDER BY creation_date DESC LIMIT 20""",
     lambda r: f"Found {len(r)} sales orders. Latest: " + ", ".join(x['sales_order'] for x in r[:5])),

    # list/show payments
    (r"(list|show|all|get).{0,20}(payment|paid)",
     """SELECT accounting_document, customer, amount_in_transaction_currency,
               transaction_currency, clearing_date, posting_date
        FROM payments_accounts_receivable ORDER BY posting_date DESC LIMIT 20""",
     lambda r: f"Found {len(r)} payments. Total: {sum(x['amount_in_transaction_currency'] or 0 for x in r):,.2f}."),

    # list deliveries
    (r"(list|show|all).{0,20}(deliver)",
     """SELECT delivery_document, overall_goods_movement_status,
               overall_picking_status, creation_date
        FROM outbound_delivery_headers ORDER BY creation_date DESC LIMIT 20""",
     lambda r: f"Found {len(r)} deliveries."),

    # all customers / list customers
    (r"(all|list|show).{0,15}customer",
     """SELECT bp.full_name, bp.business_partner,
               COUNT(so.sales_order) AS total_orders
        FROM business_partners bp
        LEFT JOIN sales_order_headers so ON bp.business_partner=so.sold_to_party
        GROUP BY bp.business_partner ORDER BY total_orders DESC""",
     lambda r: f"{len(r)} customers: " + ", ".join(f"{x['full_name']} ({x['total_orders']} orders)" for x in r)),
    # top products by billing docs
    (r"(top|highest|most).{0,30}(product|material).{0,30}(billing|invoice)",
     """SELECT COALESCE(pd.product_description,p.product) AS product_name,
               p.product,
               COUNT(DISTINCT bi.billing_document) AS billing_doc_count
        FROM billing_document_items bi
        JOIN products p ON bi.material=p.product
        LEFT JOIN product_descriptions pd ON p.product=pd.product AND pd.language='EN'
        GROUP BY p.product ORDER BY billing_doc_count DESC LIMIT 10""",
     lambda r: f"Top {len(r)} products by billing docs: " +
               ", ".join(f"{x.get('product_name',x['product'])} ({x['billing_doc_count']})" for x in r[:5])),

    # total revenue
    (r"(total|sum).{0,20}(revenue|payment|collected|received)",
     """SELECT SUM(amount_in_transaction_currency) AS total_revenue,
               COUNT(*) AS payment_count, transaction_currency
        FROM payments_accounts_receivable
        GROUP BY transaction_currency ORDER BY total_revenue DESC""",
     lambda r: "Total revenue: " +
               "; ".join(f"{x['transaction_currency']} {x['total_revenue']:,.2f} ({x['payment_count']} payments)" for x in r)),

    # cancelled billing docs
    (r"(cancelled|canceled).{0,20}(billing|invoice|document)",
     """SELECT COUNT(*) AS cancelled_count,
               SUM(total_net_amount) AS cancelled_amount, transaction_currency
        FROM billing_document_headers WHERE is_cancelled=1
        GROUP BY transaction_currency""",
     lambda r: f"There are {sum(x['cancelled_count'] for x in r)} cancelled billing documents." if r else "No cancelled docs."),

    # delivered not billed
    (r"(delivered|delivery).{0,20}(not|without|no).{0,20}(billed|billing|invoice)",
     """SELECT so.sales_order, so.total_net_amount, so.transaction_currency,
               bp.full_name AS customer
        FROM sales_order_headers so
        LEFT JOIN business_partners bp ON so.sold_to_party=bp.business_partner
        WHERE EXISTS(SELECT 1 FROM outbound_delivery_items di WHERE di.reference_sales_order=so.sales_order)
        AND NOT EXISTS(
            SELECT 1 FROM billing_document_items bi
            JOIN outbound_delivery_items di2 ON bi.reference_delivery_doc=di2.delivery_document
            WHERE di2.reference_sales_order=so.sales_order) LIMIT 50""",
     lambda r: f"Found {len(r)} orders delivered but not billed. " +
               ("Examples: " + ", ".join(x['sales_order'] for x in r[:5]) if r else "")),

    # orders no delivery
    (r"(order|sales).{0,20}(no|without|missing).{0,20}(delivery|shipped)",
     """SELECT so.sales_order, so.total_net_amount, bp.full_name AS customer,
               so.overall_delivery_status, so.creation_date
        FROM sales_order_headers so
        LEFT JOIN business_partners bp ON so.sold_to_party=bp.business_partner
        WHERE NOT EXISTS(SELECT 1 FROM outbound_delivery_items di WHERE di.reference_sales_order=so.sales_order)
        LIMIT 50""",
     lambda r: f"Found {len(r)} orders with no delivery. " +
               ("Examples: " + ", ".join(x['sales_order'] for x in r[:5]) if r else "")),

    # customer most orders
    (r"(customer|partner).{0,20}(most|top|highest).{0,20}(order|purchase)",
     """SELECT bp.full_name AS customer, bp.business_partner,
               COUNT(so.sales_order) AS order_count,
               SUM(so.total_net_amount) AS total_amount
        FROM sales_order_headers so
        JOIN business_partners bp ON so.sold_to_party=bp.business_partner
        GROUP BY bp.business_partner ORDER BY order_count DESC LIMIT 10""",
     lambda r: f"Top customer: {r[0]['customer']} with {r[0]['order_count']} orders "
               f"(total {r[0]['total_amount']:,.2f})." if r else "No data."),

    # average order value
    (r"average.{0,20}(order|sale).{0,20}(value|amount)",
     """SELECT bp.full_name AS customer, COUNT(so.sales_order) AS order_count,
               ROUND(AVG(so.total_net_amount),2) AS avg_value,
               so.transaction_currency
        FROM sales_order_headers so
        JOIN business_partners bp ON so.sold_to_party=bp.business_partner
        GROUP BY bp.business_partner ORDER BY avg_value DESC LIMIT 10""",
     lambda r: f"Average order value — top: {r[0]['customer']} at {r[0]['avg_value']:,.2f} {r[0]['transaction_currency']}." if r else "No data."),

    # how many sales orders
    (r"how many.{0,20}(sales order|order)",
     "SELECT COUNT(*) AS total FROM sales_order_headers",
     lambda r: f"There are {r[0]['total']} sales orders." if r else "No data."),

    # how many deliveries
    (r"how many.{0,20}(deliver)",
     "SELECT COUNT(*) AS total FROM outbound_delivery_headers",
     lambda r: f"There are {r[0]['total']} deliveries." if r else "No data."),

    # how many billing/invoice
    (r"how many.{0,20}(billing|invoice|bill)",
     """SELECT COUNT(*) AS total, SUM(is_cancelled) AS cancelled
        FROM billing_document_headers""",
     lambda r: f"There are {r[0]['total']} billing documents ({r[0]['cancelled']} cancelled)." if r else "No data."),

    # how many customers
    (r"how many.{0,20}(customer|partner)",
     "SELECT COUNT(*) AS total FROM business_partners",
     lambda r: f"There are {r[0]['total']} business partners." if r else "No data."),

    # how many products
    (r"how many.{0,20}(product|material)",
     "SELECT COUNT(*) AS total FROM products",
     lambda r: f"There are {r[0]['total']} products." if r else "No data."),

    # list customers
    (r"(list|show|get).{0,20}(customer|partner)",
     """SELECT bp.full_name, bp.business_partner, COUNT(so.sales_order) AS orders
        FROM business_partners bp
        LEFT JOIN sales_order_headers so ON bp.business_partner=so.sold_to_party
        GROUP BY bp.business_partner ORDER BY orders DESC LIMIT 20""",
     lambda r: f"Found {len(r)} customers. Top: " +
               ", ".join(f"{x['full_name']} ({x['orders']} orders)" for x in r[:5])),

    # broken flows
    (r"(broken|incomplete|missing|gap).{0,20}(flow|chain|process)",
     """SELECT 'Delivered not billed' AS issue, COUNT(*) AS count FROM sales_order_headers so
        WHERE EXISTS(SELECT 1 FROM outbound_delivery_items di WHERE di.reference_sales_order=so.sales_order)
        AND NOT EXISTS(SELECT 1 FROM billing_document_items bi
            JOIN outbound_delivery_items di2 ON bi.reference_delivery_doc=di2.delivery_document
            WHERE di2.reference_sales_order=so.sales_order)
        UNION ALL
        SELECT 'Orders not delivered', COUNT(*) FROM sales_order_headers so
        WHERE NOT EXISTS(SELECT 1 FROM outbound_delivery_items di WHERE di.reference_sales_order=so.sales_order)
        UNION ALL
        SELECT 'Cancelled billing docs', COUNT(*) FROM billing_document_headers WHERE is_cancelled=1""",
     lambda r: "Broken flow summary: " + "; ".join(f"{x['issue']}: {x['count']}" for x in r)),
]


def _match_rule(question: str):
    """Return (sql, answer_fn) for first matching rule, else (None, None)."""
    q = question.lower()

    # Special: trace billing doc number
    m = re.search(r"trace.{0,30}?(\d{6,12})", q)
    if m:
        doc_id = m.group(1)
        sql = f"""
            SELECT so.sales_order, dh.delivery_document,
                   bh.billing_document, bh.accounting_document,
                   bh.total_net_amount, bh.transaction_currency,
                   bh.billing_document_date,
                   CASE bh.is_cancelled WHEN 1 THEN 'Yes' ELSE 'No' END AS cancelled,
                   bh.billing_document_type
            FROM billing_document_headers bh
            LEFT JOIN billing_document_items bi ON bh.billing_document=bi.billing_document
            LEFT JOIN outbound_delivery_headers dh ON bi.reference_delivery_doc=dh.delivery_document
            LEFT JOIN outbound_delivery_items di ON dh.delivery_document=di.delivery_document
            LEFT JOIN sales_order_headers so ON di.reference_sales_order=so.sales_order
            WHERE bh.billing_document='{doc_id}' LIMIT 20"""

        def ans(rows, d=doc_id):
            if not rows:
                return f"No billing document found with ID {d}."
            r = rows[0]
            parts = [f"Billing doc {d}"]
            if r.get("sales_order"):       parts.append(f"SO: {r['sales_order']}")
            if r.get("delivery_document"): parts.append(f"Delivery: {r['delivery_document']}")
            if r.get("accounting_document"):parts.append(f"Acctg doc: {r['accounting_document']}")
            if r.get("total_net_amount"):  parts.append(f"Amount: {r['total_net_amount']:,.2f} {r.get('transaction_currency','')}")
            parts.append(f"Cancelled: {r.get('cancelled','No')}")
            return " → ".join(parts)
        return sql, ans

    for pattern, sql, ans_fn in _RULES:
        if re.search(pattern, q):
            return sql, ans_fn
    return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Local formatter — no LLM
# ─────────────────────────────────────────────────────────────────────────────

def _local_format(question: str, rows: list[dict]) -> str:
    if not rows:
        return "No matching records found in the dataset."
    count = len(rows)
    cols  = list(rows[0].keys())
    # Single aggregate
    if count == 1 and len(cols) == 1:
        k, v = next(iter(rows[0].items()))
        return f"{k.replace('_',' ').title()}: {v}."
    # Build readable lines
    lines = []
    for r in rows[:6]:
        parts = [f"{k.replace('_',' ')}: {v}" for k, v in r.items()
                 if v is not None and v != ""]
        lines.append("• " + " | ".join(str(p) for p in parts[:5]))
    tail = f"\n(+ {count-6} more rows)" if count > 6 else ""
    return f"Found {count} result(s):\n" + "\n".join(lines) + tail


# ─────────────────────────────────────────────────────────────────────────────
# LLM helpers
# ─────────────────────────────────────────────────────────────────────────────

def _llm_available():
    if LLM_PROVIDER == "groq"   and GROQ_API_KEY:  return True
    if LLM_PROVIDER == "gemini" and GEMINI_API_KEY: return True
    return False


def _strip_fences(text):
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    return re.sub(r"\s*```$", "", text).strip()


SYSTEM_PROMPT = """You are an O2C data analyst. Convert ANY question about business data into SQLite SELECT queries.
Be GENEROUS — if the question could relate to orders, billing, products, customers, payments, or deliveries, generate SQL for it.
Only return out_of_domain for completely unrelated topics like weather, sports, cooking, or general knowledge.

RETURN ONLY JSON: {"intent":"query","sql":"SELECT ...","answer_template":""}
If truly out-of-domain: {"intent":"out_of_domain","sql":"","answer_template":""}

TABLES: sales_order_headers, sales_order_items, outbound_delivery_headers, outbound_delivery_items,
billing_document_headers (is_cancelled=0/1), billing_document_items, payments_accounts_receivable,
journal_entry_items_ar, business_partners, products, product_descriptions, plants

KEY JOINS:
- sales_order_items.sales_order → sales_order_headers.sales_order
- outbound_delivery_items.reference_sales_order → sales_order_headers.sales_order
- billing_document_items.reference_delivery_doc → outbound_delivery_headers.delivery_document
- billing_document_headers.accounting_document = payments_accounts_receivable.accounting_document
- sales_order_headers.sold_to_party → business_partners.business_partner
- product_descriptions: JOIN on product + language='EN'

EXAMPLES OF SHORT QUERIES YOU MUST HANDLE:
- "total billing" → SELECT SUM(total_net_amount) AS total_billing, COUNT(*) AS count FROM billing_document_headers WHERE is_cancelled=0
- "list products" → SELECT p.product, pd.product_description FROM products p LEFT JOIN product_descriptions pd ON p.product=pd.product AND pd.language='EN' LIMIT 50
- "show orders" → SELECT sales_order, sold_to_party, total_net_amount, overall_delivery_status FROM sales_order_headers LIMIT 20
- "all customers" → SELECT business_partner, full_name FROM business_partners
- "payments" → SELECT accounting_document, customer, amount_in_transaction_currency, clearing_date FROM payments_accounts_receivable LIMIT 20
"""


def _call_llm_sql(question: str, history: list) -> dict:
    ctx = ""
    if history:
        lines = []
        for t in history[-3:]:
            lines.append(f"Q: {t['question']}\nSQL: {t.get('sql','')}")
        ctx = "\n\nPrior context:\n" + "\n".join(lines)
    prompt = f"{SYSTEM_PROMPT}{ctx}\n\nQuestion: {question}"

    payload_dict = {"temperature": 0.1, "max_tokens": 800}
    if LLM_PROVIDER == "groq":
        payload_dict.update({"model": GROQ_MODEL,
                              "messages": [{"role": "user", "content": prompt}]})
        data = json.dumps(payload_dict).encode()
        req  = urllib.request.Request(GROQ_URL, data=data,
               headers={"Content-Type": "application/json",
                        "Authorization": f"Bearer {GROQ_API_KEY}"}, method="POST")
    else:
        payload_dict = {"contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 800}}
        data = json.dumps(payload_dict).encode()
        req  = urllib.request.Request(GEMINI_URL.format(key=GEMINI_API_KEY),
               data=data, headers={"Content-Type": "application/json"}, method="POST")

    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    if LLM_PROVIDER == "groq":
        text = result["choices"][0]["message"]["content"].strip()
    else:
        text = result["candidates"][0]["content"]["parts"][0]["text"].strip()

    return json.loads(_strip_fences(text))


def _call_llm_summary(question: str, sql: str, rows: list) -> str:
    preview = rows[:10]
    prompt = (
        f'User asked: "{question}"\n'
        f"SQL: {sql}\n"
        f"Results ({len(rows)} rows, first {len(preview)}): {json.dumps(preview, default=str)}\n\n"
        "Write a clear 2-3 sentence answer. Use specific numbers/names from the data. No markdown."
    )
    try:
        if LLM_PROVIDER == "groq":
            data = json.dumps({"model": GROQ_MODEL, "temperature": 0.2, "max_tokens": 400,
                               "messages": [{"role": "user", "content": prompt}]}).encode()
            req  = urllib.request.Request(GROQ_URL, data=data,
                   headers={"Content-Type": "application/json",
                            "Authorization": f"Bearer {GROQ_API_KEY}"}, method="POST")
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())["choices"][0]["message"]["content"].strip()
        else:
            data = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                               "generationConfig": {"temperature": 0.2, "maxOutputTokens": 400}}).encode()
            req  = urllib.request.Request(GEMINI_URL.format(key=GEMINI_API_KEY),
                   data=data, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return _local_format(question, rows)


# ─────────────────────────────────────────────────────────────────────────────
# Safety
# ─────────────────────────────────────────────────────────────────────────────

def _is_domain(q: str) -> bool:
    q_lower = q.lower()
    # Block obvious non-domain topics
    blocked = ["weather","recipe","cook","sport","football","cricket","movie",
               "song","poem","write a","capital of","who is the president",
               "translate","joke","story"]
    if any(b in q_lower for b in blocked):
        return False
    # Allow if it has any domain keyword OR is a short query (user exploring)
    if any(kw in q_lower for kw in DOMAIN_KEYWORDS):
        return True
    # Allow very short queries — user is probably exploring the dataset
    if len(q.split()) <= 4:
        return True
    return False


def _safe_sql(sql: str) -> bool:
    c = sql.strip().upper()
    if not c.startswith("SELECT"): return False
    return not any(k in c for k in ["DROP","DELETE","UPDATE","INSERT","ALTER","CREATE","TRUNCATE"])


def _run_sql(sql: str) -> list:
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql).fetchall()]
    except Exception as e:
        raise ValueError(f"SQL error: {e}")
    finally:
        conn.close()


def _extract_nodes(rows: list) -> list:
    ids, map_ = [], {
        "sales_order":"SalesOrder", "delivery_document":"Delivery",
        "billing_document":"BillingDoc", "accounting_document":"Payment",
        "business_partner":"Customer", "product":"Product", "plant":"Plant",
    }
    for row in rows[:20]:
        for col, ntype in map_.items():
            val = row.get(col)
            if val: ids.append(f"{ntype}:{val}")
    return list(set(ids))


# ─────────────────────────────────────────────────────────────────────────────
# Session memory
# ─────────────────────────────────────────────────────────────────────────────
_sessions: dict[str, list] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def answer_question(question: str, session_id: str = "default") -> dict:
    question = question.strip()
    if not question:
        return _r("Please ask a question.")

    # Guardrail
    if not _is_domain(question):
        return _r("This system answers questions about the O2C dataset only — "
                  "orders, deliveries, billing, payments, customers, and products.",
                  out_of_domain=True)

    history = _sessions.get(session_id, [])
    sql, ans_fn, mode = None, None, "rule"

    # ── Try LLM for SQL generation ────────────────────────────────────────────
    if _llm_available():
        try:
            res = _call_llm_sql(question, history)
            if res.get("intent") == "out_of_domain":
                return _r("This system answers questions about the O2C dataset only.",
                          out_of_domain=True)
            candidate = res.get("sql", "").strip()
            if candidate and _safe_sql(candidate):
                sql  = candidate
                mode = "llm"
        except Exception:
            pass  # fall through to rule-based

    # ── Rule-based fallback ───────────────────────────────────────────────────
    if sql is None:
        rule_sql, ans_fn = _match_rule(question)
        if rule_sql and _safe_sql(rule_sql):
            sql  = rule_sql
            mode = "rule"

    if sql is None:
        return _r("I couldn't generate a query. Try asking about products, "
                  "orders, deliveries, billing, payments, customers, or revenue.",
                  error="no_sql")

    # ── Execute SQL ───────────────────────────────────────────────────────────
    try:
        rows = _run_sql(sql)
    except ValueError as e:
        return _r(str(e), sql=sql, error="sql_error")

    # ── Format answer ─────────────────────────────────────────────────────────
    if mode == "llm" and _llm_available():
        try:
            answer = _call_llm_summary(question, sql, rows)
        except Exception:
            answer = _local_format(question, rows)
            mode   = "fallback"
    elif ans_fn is not None:
        try:
            answer = ans_fn(rows)
        except Exception:
            answer = _local_format(question, rows)
    else:
        answer = _local_format(question, rows)
        mode   = "fallback"

    # ── Save session ──────────────────────────────────────────────────────────
    _sessions.setdefault(session_id, []).append(
        {"question": question, "sql": sql, "answer": answer}
    )
    if len(_sessions[session_id]) > 20:
        _sessions[session_id] = _sessions[session_id][-20:]

    prov = f"{LLM_PROVIDER} ({mode})" if mode == "llm" else f"SQL ({mode})"
    return {
        "answer":            answer,
        "sql":               sql,
        "rows":              rows[:50],
        "highlighted_nodes": _extract_nodes(rows),
        "out_of_domain":     False,
        "error":             None,
        "provider":          prov,
        "mode":              mode,
    }


def _r(answer, sql="", rows=None, out_of_domain=False, error=None):
    return {"answer": answer, "sql": sql, "rows": rows or [],
            "highlighted_nodes": [], "out_of_domain": out_of_domain,
            "error": error, "provider": LLM_PROVIDER, "mode": "guardrail"}
