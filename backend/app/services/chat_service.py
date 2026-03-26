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

# ── Expanded domain keywords — include all natural ways users ask ─────────────
DOMAIN_KEYWORDS = {
    # Core O2C entities
    "sales", "order", "delivery", "billing", "invoice", "payment", "customer",
    "product", "material", "plant", "journal", "accounting", "document", "shipment",
    "quantity", "amount", "currency", "inr", "flow", "trace", "status",
    "cancelled", "billed", "delivered", "shipped", "o2c", "partner", "business",
    "fiscal", "clearing", "transaction", "revenue", "average", "total", "count",
    "list", "show", "find", "top", "most", "highest", "lowest", "broken",
    "incomplete",
    # Additional natural query words users commonly use
    "all", "get", "give", "fetch", "what", "which", "how", "many", "where",
    "who", "when", "value", "price", "cost", "data", "info", "summary",
    "report", "detail", "details", "overview", "stats", "statistics", "metrics",
    "number", "numbers", "record", "records", "entry", "entries", "item", "items",
    "pending", "open", "closed", "complete", "completed", "partial", "full",
    "recent", "latest", "new", "old", "first", "last", "between", "date",
    "month", "year", "quarter", "week", "today", "paid", "unpaid", "due",
    "outstanding", "overdue", "purchase", "sale", "sell", "buy", "vendor",
    "supplier", "buyer", "seller", "invoice", "receipt", "dispatch", "ship",
    "country", "city", "region", "address", "currency", "rate", "price",
    "margin", "profit", "loss", "net", "gross", "tax", "discount", "credit",
    "debit", "balance", "ledger", "account", "stock", "inventory", "sku",
    "category", "type", "group", "class", "code", "id", "number", "no",
    "document", "doc", "ref", "reference", "linked", "associated", "related",
    "compare", "comparison", "rank", "sort", "filter", "search",
}

# ─────────────────────────────────────────────────────────────────────────────
# Rule-based SQL matcher — works with zero LLM calls
# ─────────────────────────────────────────────────────────────────────────────

_RULES = [

    # Overview / summary / dashboard — catch-all "what data", "show me data", "overview"
    (r"(overview|summary|dashboard|what.{0,10}(data|have|available)|show.{0,10}(me|data|all)|all data|data summary|whats in)",
     """SELECT
        (SELECT COUNT(*) FROM sales_order_headers) AS total_orders,
        (SELECT COUNT(*) FROM outbound_delivery_headers) AS total_deliveries,
        (SELECT COUNT(*) FROM billing_document_headers WHERE is_cancelled=0) AS total_billing_docs,
        (SELECT COUNT(*) FROM payments_accounts_receivable) AS total_payments,
        (SELECT COUNT(*) FROM business_partners) AS total_customers,
        (SELECT COUNT(*) FROM products) AS total_products""",
     lambda r: (f"Dataset overview: {r[0]['total_orders']} sales orders, "
                f"{r[0]['total_deliveries']} deliveries, "
                f"{r[0]['total_billing_docs']} billing documents, "
                f"{r[0]['total_payments']} payments, "
                f"{r[0]['total_customers']} customers, "
                f"{r[0]['total_products']} products.") if r else "No data."),

    # total billing (short query)
    (r"total.{0,15}bill|bill.{0,15}total|total.{0,10}invoic|billing amount|invoice total",
     """SELECT SUM(total_net_amount) AS total_billing_amount,
               COUNT(*) AS total_docs,
               SUM(CASE WHEN is_cancelled=1 THEN 1 ELSE 0 END) AS cancelled,
               transaction_currency
        FROM billing_document_headers GROUP BY transaction_currency""",
     lambda r: f"Total billing: {r[0]['transaction_currency']} {r[0]['total_billing_amount']:,.2f} across {r[0]['total_docs']} documents ({r[0]['cancelled']} cancelled)." if r else "No billing data found."),

    # list/show/get products — broader pattern
    (r"(list|show|get|all|what|fetch|give).{0,25}(product|material|item|sku|goods)|products\??$|materials\??$",
     """SELECT p.product, COALESCE(pd.product_description, p.product) AS description,
               p.product_type, p.product_group
        FROM products p
        LEFT JOIN product_descriptions pd ON p.product=pd.product AND pd.language='EN'
        ORDER BY p.product LIMIT 30""",
     lambda r: f"Found {len(r)} products. Examples: " + ", ".join(x.get('description', x['product']) for x in r[:8]) if r else "No products found."),

    # list/show/get orders — broader pattern
    (r"(list|show|get|all|fetch|give).{0,25}(order|sales order|so)|orders\??$|sales orders\??$",
     """SELECT sales_order, sold_to_party, total_net_amount,
               transaction_currency, overall_delivery_status, creation_date
        FROM sales_order_headers ORDER BY creation_date DESC LIMIT 20""",
     lambda r: f"Found {len(r)} sales orders. Latest: " + ", ".join(x['sales_order'] for x in r[:5]) if r else "No sales orders found."),

    # list/show/get payments
    (r"(list|show|all|get|fetch).{0,25}(payment|paid|receipt)|payments\??$",
     """SELECT accounting_document, customer, amount_in_transaction_currency,
               transaction_currency, clearing_date, posting_date
        FROM payments_accounts_receivable ORDER BY posting_date DESC LIMIT 20""",
     lambda r: f"Found {len(r)} payments. Total: {sum(x['amount_in_transaction_currency'] or 0 for x in r):,.2f}." if r else "No payments found."),

    # list deliveries
    (r"(list|show|all|get|fetch).{0,25}(deliver|shipment|dispatch)|deliveries\??$",
     """SELECT delivery_document, overall_goods_movement_status,
               overall_picking_status, creation_date
        FROM outbound_delivery_headers ORDER BY creation_date DESC LIMIT 20""",
     lambda r: f"Found {len(r)} deliveries." if r else "No deliveries found."),

    # list billing documents
    (r"(list|show|all|get|fetch).{0,25}(billing|invoice|billing doc)|invoices\??$|billing docs\??$",
     """SELECT billing_document, billing_document_type, total_net_amount,
               transaction_currency, billing_document_date,
               CASE is_cancelled WHEN 1 THEN 'Cancelled' ELSE 'Active' END AS status
        FROM billing_document_headers ORDER BY billing_document_date DESC LIMIT 20""",
     lambda r: f"Found {len(r)} billing documents. Latest: " + ", ".join(x['billing_document'] for x in r[:5]) if r else "No billing documents found."),

    # all customers / list customers
    (r"(all|list|show|get|fetch).{0,20}(customer|partner|client|buyer)|customers\??$",
     """SELECT bp.full_name, bp.business_partner,
               COUNT(so.sales_order) AS total_orders
        FROM business_partners bp
        LEFT JOIN sales_order_headers so ON bp.business_partner=so.sold_to_party
        GROUP BY bp.business_partner ORDER BY total_orders DESC""",
     lambda r: f"{len(r)} customers: " + ", ".join(f"{x['full_name']} ({x['total_orders']} orders)" for x in r) if r else "No customers found."),

    # top products by billing docs
    (r"(top|highest|most).{0,35}(product|material|item).{0,35}(billing|invoice|doc)|which.{0,20}product.{0,20}(most|highest|top)",
     """SELECT COALESCE(pd.product_description,p.product) AS product_name,
               p.product,
               COUNT(DISTINCT bi.billing_document) AS billing_doc_count
        FROM billing_document_items bi
        JOIN products p ON bi.material=p.product
        LEFT JOIN product_descriptions pd ON p.product=pd.product AND pd.language='EN'
        GROUP BY p.product ORDER BY billing_doc_count DESC LIMIT 10""",
     lambda r: f"Top {len(r)} products by billing docs: " +
               ", ".join(f"{x.get('product_name',x['product'])} ({x['billing_doc_count']})" for x in r[:5]) if r else "No data."),

    # total revenue / payments received
    (r"(total|sum|overall).{0,25}(revenue|payment|collected|received|income)|revenue\??$",
     """SELECT SUM(amount_in_transaction_currency) AS total_revenue,
               COUNT(*) AS payment_count, transaction_currency
        FROM payments_accounts_receivable
        GROUP BY transaction_currency ORDER BY total_revenue DESC""",
     lambda r: "Total revenue: " +
               "; ".join(f"{x['transaction_currency']} {x['total_revenue']:,.2f} ({x['payment_count']} payments)" for x in r) if r else "No revenue data."),

    # cancelled billing docs
    (r"(cancelled|canceled|void).{0,25}(billing|invoice|document|doc)",
     """SELECT COUNT(*) AS cancelled_count,
               SUM(total_net_amount) AS cancelled_amount, transaction_currency
        FROM billing_document_headers WHERE is_cancelled=1
        GROUP BY transaction_currency""",
     lambda r: f"There are {sum(x['cancelled_count'] for x in r)} cancelled billing documents." if r else "No cancelled docs."),

    # delivered not billed
    (r"(delivered|delivery).{0,25}(not|without|no|never|missing|but not).{0,25}(billed|billing|invoice)|delivered.{0,10}unbilled",
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
               ("Examples: " + ", ".join(x['sales_order'] for x in r[:5]) if r else "") if r else "No such orders found."),

    # billed not delivered / billed without delivery
    (r"(billed|billing|invoiced).{0,25}(not|without|no|never|missing|but not).{0,25}(deliver|shipment)|billed.{0,10}undelivered",
     """SELECT bh.billing_document, bh.total_net_amount, bh.transaction_currency,
               bh.billing_document_date
        FROM billing_document_headers bh
        WHERE NOT EXISTS(
            SELECT 1 FROM billing_document_items bi
            JOIN outbound_delivery_items di ON bi.reference_delivery_doc=di.delivery_document
            WHERE bi.billing_document=bh.billing_document)
        AND bh.is_cancelled=0 LIMIT 50""",
     lambda r: f"Found {len(r)} billing documents with no linked delivery." +
               (" Examples: " + ", ".join(x['billing_document'] for x in r[:5]) if r else "") if r else "No such documents found."),

    # orders no delivery
    (r"(order|sales).{0,25}(no|without|missing|never|not).{0,25}(delivery|shipped|dispatched)|orders.{0,10}undelivered",
     """SELECT so.sales_order, so.total_net_amount, bp.full_name AS customer,
               so.overall_delivery_status, so.creation_date
        FROM sales_order_headers so
        LEFT JOIN business_partners bp ON so.sold_to_party=bp.business_partner
        WHERE NOT EXISTS(SELECT 1 FROM outbound_delivery_items di WHERE di.reference_sales_order=so.sales_order)
        LIMIT 50""",
     lambda r: f"Found {len(r)} orders with no delivery. " +
               ("Examples: " + ", ".join(x['sales_order'] for x in r[:5]) if r else "") if r else "No such orders found."),

    # customer with most orders
    (r"(customer|partner|client).{0,25}(most|top|highest|max).{0,25}(order|purchase|buy)|top.{0,15}customer",
     """SELECT bp.full_name AS customer, bp.business_partner,
               COUNT(so.sales_order) AS order_count,
               SUM(so.total_net_amount) AS total_amount
        FROM sales_order_headers so
        JOIN business_partners bp ON so.sold_to_party=bp.business_partner
        GROUP BY bp.business_partner ORDER BY order_count DESC LIMIT 10""",
     lambda r: f"Top customer: {r[0]['customer']} with {r[0]['order_count']} orders "
               f"(total {r[0]['total_amount']:,.2f})." if r else "No data."),

    # average order value
    (r"average.{0,25}(order|sale).{0,25}(value|amount|worth)|avg.{0,15}order",
     """SELECT bp.full_name AS customer, COUNT(so.sales_order) AS order_count,
               ROUND(AVG(so.total_net_amount),2) AS avg_value,
               so.transaction_currency
        FROM sales_order_headers so
        JOIN business_partners bp ON so.sold_to_party=bp.business_partner
        GROUP BY bp.business_partner ORDER BY avg_value DESC LIMIT 10""",
     lambda r: f"Average order value — top: {r[0]['customer']} at {r[0]['avg_value']:,.2f} {r[0]['transaction_currency']}." if r else "No data."),

    # how many sales orders
    (r"how many.{0,25}(sales order|order|so\b)|count.{0,15}order",
     "SELECT COUNT(*) AS total FROM sales_order_headers",
     lambda r: f"There are {r[0]['total']} sales orders." if r else "No data."),

    # how many deliveries
    (r"how many.{0,25}(deliver|shipment)|count.{0,15}deliver",
     "SELECT COUNT(*) AS total FROM outbound_delivery_headers",
     lambda r: f"There are {r[0]['total']} deliveries." if r else "No data."),

    # how many billing/invoice
    (r"how many.{0,25}(billing|invoice|bill)|count.{0,15}(billing|invoice)",
     """SELECT COUNT(*) AS total, SUM(is_cancelled) AS cancelled
        FROM billing_document_headers""",
     lambda r: f"There are {r[0]['total']} billing documents ({r[0]['cancelled']} cancelled)." if r else "No data."),

    # how many customers
    (r"how many.{0,25}(customer|partner|client)|count.{0,15}customer",
     "SELECT COUNT(*) AS total FROM business_partners",
     lambda r: f"There are {r[0]['total']} business partners." if r else "No data."),

    # how many products
    (r"how many.{0,25}(product|material|item|sku)|count.{0,15}(product|material)",
     "SELECT COUNT(*) AS total FROM products",
     lambda r: f"There are {r[0]['total']} products." if r else "No data."),

    # how many payments
    (r"how many.{0,25}(payment|paid|receipt)|count.{0,15}payment",
     "SELECT COUNT(*) AS total FROM payments_accounts_receivable",
     lambda r: f"There are {r[0]['total']} payment records." if r else "No data."),

    # broken flows
    (r"(broken|incomplete|missing|gap|anomal|problem|issue|irregular).{0,25}(flow|chain|process|order|cycle)|flow.{0,15}(issue|problem|gap)",
     """SELECT 'Delivered not billed' AS issue, COUNT(*) AS count FROM sales_order_headers so
        WHERE EXISTS(SELECT 1 FROM outbound_delivery_items di WHERE di.reference_sales_order=so.sales_order)
        AND NOT EXISTS(SELECT 1 FROM billing_document_items bi
            JOIN outbound_delivery_items di2 ON bi.reference_delivery_doc=di2.delivery_document
            WHERE di2.reference_sales_order=so.sales_order)
        UNION ALL
        SELECT 'Orders not delivered', COUNT(*) FROM sales_order_headers so
        WHERE NOT EXISTS(SELECT 1 FROM outbound_delivery_items di WHERE di.reference_sales_order=so.sales_order)
        UNION ALL
        SELECT 'Cancelled billing docs', COUNT(*) FROM billing_document_headers WHERE is_cancelled=1
        UNION ALL
        SELECT 'Billed without delivery', COUNT(*) FROM billing_document_headers bh
        WHERE NOT EXISTS(SELECT 1 FROM billing_document_items bi
            JOIN outbound_delivery_items di ON bi.reference_delivery_doc=di.delivery_document
            WHERE bi.billing_document=bh.billing_document) AND bh.is_cancelled=0""",
     lambda r: "Broken flow summary: " + "; ".join(f"{x['issue']}: {x['count']}" for x in r) if r else "No broken flows found."),

    # plants / warehouses
    (r"(list|show|all|get|fetch|which).{0,20}(plant|warehouse|location|facility)|plants\??$",
     """SELECT p.plant, p.plant_name, p.country,
               COUNT(DISTINCT dh.delivery_document) AS deliveries
        FROM plants p
        LEFT JOIN outbound_delivery_headers dh ON dh.shipping_point=p.plant
        GROUP BY p.plant ORDER BY deliveries DESC""",
     lambda r: f"Found {len(r)} plants: " + ", ".join(f"{x['plant_name']} ({x['deliveries']} deliveries)" for x in r[:8]) if r else "No plants found."),

    # top plants by deliveries
    (r"(top|most|highest).{0,20}(plant|warehouse).{0,20}(deliver|shipment)|which.{0,20}plant.{0,20}(most|top|highest)",
     """SELECT p.plant, p.plant_name, COUNT(dh.delivery_document) AS delivery_count
        FROM plants p
        JOIN outbound_delivery_headers dh ON dh.shipping_point=p.plant
        GROUP BY p.plant ORDER BY delivery_count DESC LIMIT 10""",
     lambda r: f"Top plant: {r[0]['plant_name']} with {r[0]['delivery_count']} deliveries." if r else "No data."),

    # pending / open orders
    (r"(pending|open|not.{0,10}complete|in.progress|outstanding).{0,20}(order|sales)|open.{0,10}order",
     """SELECT so.sales_order, bp.full_name AS customer,
               so.total_net_amount, so.transaction_currency,
               so.overall_delivery_status, so.creation_date
        FROM sales_order_headers so
        LEFT JOIN business_partners bp ON so.sold_to_party=bp.business_partner
        WHERE so.overall_delivery_status NOT IN ('C','complete','COMPLETE')
        ORDER BY so.creation_date DESC LIMIT 20""",
     lambda r: f"Found {len(r)} open/pending orders." + (" Latest: " + ", ".join(x['sales_order'] for x in r[:5]) if r else "") if r else "No open orders found."),

    # order value / net value of orders
    (r"(total|sum|net).{0,20}(order value|sales value|order amount)|order.{0,10}(value|worth|amount).{0,10}(total|sum)",
     """SELECT SUM(total_net_amount) AS total_order_value,
               COUNT(*) AS order_count, transaction_currency
        FROM sales_order_headers GROUP BY transaction_currency""",
     lambda r: "Total order value: " + "; ".join(f"{x['transaction_currency']} {x['total_order_value']:,.2f} ({x['order_count']} orders)" for x in r) if r else "No data."),

    # journal entries
    (r"(list|show|all|get).{0,20}(journal|accounting entry|ledger)|journal entries\??$",
     """SELECT company_code, posting_date,
               SUM(amount_in_transaction_currency) AS total_amount,
               transaction_currency, COUNT(*) AS entry_count
        FROM journal_entry_items_ar
        GROUP BY company_code, transaction_currency, posting_date
        ORDER BY posting_date DESC LIMIT 20""",
     lambda r: f"Found {len(r)} journal entry groups." if r else "No journal entries found."),
]


def _match_rule(question: str):
    """Return (sql, answer_fn) for first matching rule, else (None, None)."""
    q = question.lower().strip()

    # ── Special: trace a specific document by ID ──────────────────────────────
    m = re.search(r"trace.{0,40}?(\d{6,12})", q)
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
            if r.get("sales_order"):        parts.append(f"SO: {r['sales_order']}")
            if r.get("delivery_document"):  parts.append(f"Delivery: {r['delivery_document']}")
            if r.get("accounting_document"):parts.append(f"Acctg doc: {r['accounting_document']}")
            if r.get("total_net_amount"):   parts.append(f"Amount: {r['total_net_amount']:,.2f} {r.get('transaction_currency','')}")
            parts.append(f"Cancelled: {r.get('cancelled','No')}")
            return " → ".join(parts)
        return sql, ans

    # ── Special: look up a specific sales order by ID ─────────────────────────
    m = re.search(r"(order|so).{0,10}(\d{7,12})", q)
    if m:
        order_id = m.group(2)
        sql = f"""
            SELECT so.sales_order, bp.full_name AS customer,
                   so.total_net_amount, so.transaction_currency,
                   so.overall_delivery_status, so.creation_date,
                   COUNT(DISTINCT dh.delivery_document) AS deliveries,
                   COUNT(DISTINCT bh.billing_document) AS billing_docs
            FROM sales_order_headers so
            LEFT JOIN business_partners bp ON so.sold_to_party=bp.business_partner
            LEFT JOIN outbound_delivery_items di ON di.reference_sales_order=so.sales_order
            LEFT JOIN outbound_delivery_headers dh ON di.delivery_document=dh.delivery_document
            LEFT JOIN billing_document_items bi ON bi.reference_delivery_doc=dh.delivery_document
            LEFT JOIN billing_document_headers bh ON bi.billing_document=bh.billing_document
            WHERE so.sales_order='{order_id}'
            GROUP BY so.sales_order"""

        def ans_order(rows, oid=order_id):
            if not rows:
                return f"No sales order found with ID {oid}."
            r = rows[0]
            return (f"Sales order {oid}: Customer {r.get('customer','?')}, "
                    f"Amount {r.get('total_net_amount',0):,.2f} {r.get('transaction_currency','')}, "
                    f"Delivery status: {r.get('overall_delivery_status','?')}, "
                    f"{r.get('deliveries',0)} delivery(ies), {r.get('billing_docs',0)} billing doc(s).")
        return sql, ans_order

    # ── Scan rules ────────────────────────────────────────────────────────────
    for pattern, sql, ans_fn in _RULES:
        if re.search(pattern, q):
            return sql, ans_fn
    return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Local formatter — no LLM needed
# ─────────────────────────────────────────────────────────────────────────────

def _local_format(question: str, rows: list[dict]) -> str:
    if not rows:
        return "No matching records found in the dataset."
    count = len(rows)
    cols  = list(rows[0].keys())
    # Single aggregate value
    if count == 1 and len(cols) == 1:
        k, v = next(iter(rows[0].items()))
        return f"{k.replace('_',' ').title()}: {v}."
    # Build readable lines (up to 6)
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


SYSTEM_PROMPT = """You are an O2C (Order-to-Cash) data analyst assistant.
Your job is to convert the user's question into a valid SQLite SELECT query.

IMPORTANT RULES:
- Be GENEROUS: if the question could possibly relate to orders, billing, products,
  customers, payments, deliveries, plants, or any business data, generate SQL for it.
- Only return out_of_domain for completely unrelated topics like weather, sports,
  cooking recipes, general trivia, creative writing, or personal questions.
- Short or vague queries like "show me data", "list all", "what do you have"
  should return an overview query — never reject them.
- Always return ONLY valid JSON, no explanation text.

RETURN FORMAT (choose one):
{"intent":"query","sql":"SELECT ...","answer_template":""}
{"intent":"out_of_domain","sql":"","answer_template":""}

SCHEMA (SQLite):
- sales_order_headers(sales_order PK, sold_to_party, total_net_amount, transaction_currency,
    overall_delivery_status, creation_date)
- sales_order_items(sales_order, sales_order_item, material, order_quantity, net_price)
- outbound_delivery_headers(delivery_document PK, overall_goods_movement_status,
    overall_picking_status, shipping_point, creation_date)
- outbound_delivery_items(delivery_document, reference_sales_order, material, actual_delivery_quantity)
- billing_document_headers(billing_document PK, billing_document_type, total_net_amount,
    transaction_currency, billing_document_date, accounting_document, is_cancelled)
- billing_document_items(billing_document, billing_document_item, material,
    reference_delivery_doc, billed_quantity, net_value)
- payments_accounts_receivable(accounting_document PK, customer,
    amount_in_transaction_currency, transaction_currency, posting_date, clearing_date)
- journal_entry_items_ar(company_code, accounting_document, posting_date,
    amount_in_transaction_currency, transaction_currency)
- business_partners(business_partner PK, full_name, city, country)
- products(product PK, product_type, product_group)
- product_descriptions(product, language, product_description)
- plants(plant PK, plant_name, country)

KEY JOINS:
- sales_order_items.sales_order → sales_order_headers.sales_order
- outbound_delivery_items.reference_sales_order → sales_order_headers.sales_order
- outbound_delivery_items.delivery_document → outbound_delivery_headers.delivery_document
- billing_document_items.billing_document → billing_document_headers.billing_document
- billing_document_items.reference_delivery_doc → outbound_delivery_headers.delivery_document
- billing_document_headers.accounting_document = payments_accounts_receivable.accounting_document
- sales_order_headers.sold_to_party → business_partners.business_partner
- products.product = product_descriptions.product (+ language='EN')
- outbound_delivery_headers.shipping_point → plants.plant

EXAMPLE Q&A:
Q: "which products appear in the most billing documents?"
A: {"intent":"query","sql":"SELECT COALESCE(pd.product_description,p.product) AS name, COUNT(DISTINCT bi.billing_document) AS cnt FROM billing_document_items bi JOIN products p ON bi.material=p.product LEFT JOIN product_descriptions pd ON p.product=pd.product AND pd.language='EN' GROUP BY p.product ORDER BY cnt DESC LIMIT 10","answer_template":""}

Q: "trace billing document 9000000001"
A: {"intent":"query","sql":"SELECT so.sales_order, dh.delivery_document, bh.billing_document, bh.accounting_document, bh.total_net_amount FROM billing_document_headers bh LEFT JOIN billing_document_items bi ON bh.billing_document=bi.billing_document LEFT JOIN outbound_delivery_headers dh ON bi.reference_delivery_doc=dh.delivery_document LEFT JOIN outbound_delivery_items di ON dh.delivery_document=di.delivery_document LEFT JOIN sales_order_headers so ON di.reference_sales_order=so.sales_order WHERE bh.billing_document='9000000001' LIMIT 10","answer_template":""}

Q: "show me the data"
A: {"intent":"query","sql":"SELECT (SELECT COUNT(*) FROM sales_order_headers) AS orders, (SELECT COUNT(*) FROM billing_document_headers) AS billing_docs, (SELECT COUNT(*) FROM payments_accounts_receivable) AS payments, (SELECT COUNT(*) FROM business_partners) AS customers","answer_template":""}

Q: "write me a poem"
A: {"intent":"out_of_domain","sql":"","answer_template":""}
"""


def _call_llm_sql(question: str, history: list) -> dict:
    ctx = ""
    if history:
        lines = []
        for t in history[-3:]:
            lines.append(f"Q: {t['question']}\nSQL: {t.get('sql','')}")
        ctx = "\n\nPrior conversation context:\n" + "\n".join(lines)
    prompt = f"{ctx}\n\nQuestion: {question}"

    if LLM_PROVIDER == "groq":
        payload = {
            "model": GROQ_MODEL, "temperature": 0.1, "max_tokens": 800,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt}
            ]
        }
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(GROQ_URL, data=data,
               headers={"Content-Type": "application/json",
                        "Authorization": f"Bearer {GROQ_API_KEY}"}, method="POST")
    else:
        full_prompt = SYSTEM_PROMPT + prompt
        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 800}
        }
        data = json.dumps(payload).encode()
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
        f'The user asked: "{question}"\n'
        f"SQL executed: {sql}\n"
        f"Result ({len(rows)} rows, showing first {len(preview)}): "
        f"{json.dumps(preview, default=str)}\n\n"
        "Write a clear 2–3 sentence answer grounded in this data. "
        "Use specific numbers and names from the results. No markdown, no bullet points."
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
# Guardrail — FIXED: single clean implementation, no dead code
# ─────────────────────────────────────────────────────────────────────────────

# Topics with nothing to do with O2C business data — block these explicitly
_HARD_BLOCKED = [
    "weather", "recipe", "how to cook", "sport", "football", "cricket",
    "basketball", "baseball", "tennis", "golf", "movie", "film", "song",
    "music", "poem", "write a story", "capital of", "who is the president",
    "prime minister", "translate this", "tell me a joke", "joke", "story about",
    "horoscope", "astrology", "stock market tips", "lottery",
]

def _is_domain(q: str) -> bool:
    q_lower = q.lower().strip()

    # Always block clearly unrelated topics
    if any(b in q_lower for b in _HARD_BLOCKED):
        return False

    # Always allow if it contains any domain keyword
    if any(kw in q_lower for kw in DOMAIN_KEYWORDS):
        return True

    # Always allow short queries (user is exploring — let the LLM/rules figure it out)
    if len(q.split()) <= 6:
        return True

    # Always allow if it contains a document-like number (order IDs, billing IDs, etc.)
    if re.search(r"\b\d{6,12}\b", q):
        return True

    # Allow common analytical/reporting question patterns
    analytics_patterns = [
        r"how many", r"how much", r"what is the", r"what are the",
        r"which (one|ones|is|are)", r"can you (show|give|tell|list|find)",
        r"(show|give|tell|list|find) me", r"compare", r"breakdown",
        r"distribution", r"trend", r"over time", r"by (month|year|quarter)",
    ]
    if any(re.search(p, q_lower) for p in analytics_patterns):
        return True

    return False


def _safe_sql(sql: str) -> bool:
    c = sql.strip().upper()
    if not c.startswith("SELECT"):
        return False
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
    ids  = []
    col_map = {
        "sales_order":        "SalesOrder",
        "delivery_document":  "Delivery",
        "billing_document":   "BillingDoc",
        "accounting_document":"Payment",
        "business_partner":   "Customer",
        "customer":           "Customer",
        "product":            "Product",
        "material":           "Product",
        "plant":              "Plant",
    }
    for row in rows[:20]:
        for col, ntype in col_map.items():
            val = row.get(col)
            if val:
                ids.append(f"{ntype}:{val}")
    return list(set(ids))


# ─────────────────────────────────────────────────────────────────────────────
# Session memory (last 20 turns, uses last 3 for context)
# ─────────────────────────────────────────────────────────────────────────────
_sessions: dict[str, list] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def answer_question(question: str, session_id: str = "default") -> dict:
    question = question.strip()
    if not question:
        return _r("Please ask a question about the O2C dataset.")

    # ── Layer 1: Domain guardrail ─────────────────────────────────────────────
    if not _is_domain(question):
        return _r(
            "This system is designed to answer questions about the SAP Order-to-Cash "
            "dataset only — including sales orders, deliveries, billing documents, "
            "payments, customers, products, and plants. Please ask a related question.",
            out_of_domain=True
        )

    history = _sessions.get(session_id, [])
    sql, ans_fn, mode = None, None, "rule"

    # ── Layer 2: LLM for SQL generation ──────────────────────────────────────
    if _llm_available():
        try:
            res = _call_llm_sql(question, history)
            if res.get("intent") == "out_of_domain":
                return _r(
                    "This system is designed to answer questions about the O2C dataset only.",
                    out_of_domain=True
                )
            candidate = res.get("sql", "").strip()
            if candidate and _safe_sql(candidate):
                sql  = candidate
                mode = "llm"
        except Exception:
            pass  # fall through to rule-based

    # ── Layer 3: Rule-based fallback ──────────────────────────────────────────
    if sql is None:
        rule_sql, ans_fn = _match_rule(question)
        if rule_sql and _safe_sql(rule_sql):
            sql  = rule_sql
            mode = "rule"

    # ── No SQL generated at all ───────────────────────────────────────────────
    if sql is None:
        return _r(
            "I couldn't find a matching query for that question. "
            "Try asking about sales orders, deliveries, billing documents, "
            "payments, customers, products, revenue, or broken flows.",
            error="no_sql"
        )

    # ── Layer 4: Execute SQL ──────────────────────────────────────────────────
    try:
        rows = _run_sql(sql)
    except ValueError as e:
        return _r(str(e), sql=sql, error="sql_error")

    # ── Layer 5: Format answer ────────────────────────────────────────────────
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

    # ── Save to session ───────────────────────────────────────────────────────
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


def clear_session(session_id: str) -> None:
    _sessions.pop(session_id, None)


def _r(answer, sql="", rows=None, out_of_domain=False, error=None):
    return {
        "answer":            answer,
        "sql":               sql,
        "rows":              rows or [],
        "highlighted_nodes": [],
        "out_of_domain":     out_of_domain,
        "error":             error,
        "provider":          LLM_PROVIDER,
        "mode":              "guardrail",
    }
