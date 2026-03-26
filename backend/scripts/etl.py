"""
ETL Script — O2C Graph System
Reads raw JSONL files → loads into domain tables → builds graph_nodes + graph_edges
"""

import json
import glob
import os
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).resolve().parent.parent.parent
DATA_DIR  = BASE_DIR / "data" / "raw"
DB_PATH   = BASE_DIR / "data" / "o2c.db"   # SQLite for zero-infra local dev

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_jsonl(folder: str) -> list[dict]:
    """Load all JSONL part-files from a folder into a list of dicts."""
    rows = []
    pattern = str(DATA_DIR / folder / "*.jsonl")
    for fpath in sorted(glob.glob(pattern)):
        with open(fpath) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    log.info(f"  Loaded {len(rows):>5} rows from {folder}")
    return rows


def parse_date(val) -> Optional[str]:
    """Convert ISO datetime string → 'YYYY-MM-DD' or None."""
    if not val:
        return None
    try:
        return val[:10]  # take 'YYYY-MM-DD' from 'YYYY-MM-DDT...'
    except Exception:
        return None


def safe_numeric(val) -> Optional[float]:
    try:
        return float(val) if val not in (None, "", "null") else None
    except (ValueError, TypeError):
        return None


def node_id(node_type: str, ref_id: str) -> str:
    return f"{node_type}:{ref_id}"


# ── SQLite schema (mirrors schema.sql) ───────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS business_partners (
    business_partner TEXT PRIMARY KEY, customer TEXT, full_name TEXT,
    partner_name TEXT, partner_category TEXT, partner_grouping TEXT,
    is_blocked INTEGER DEFAULT 0, is_marked_for_archiving INTEGER DEFAULT 0,
    creation_date TEXT, created_by_user TEXT
);
CREATE TABLE IF NOT EXISTS business_partner_addresses (
    business_partner TEXT, address_id TEXT, city_name TEXT, street_name TEXT,
    postal_code TEXT, region TEXT, country TEXT, address_timezone TEXT,
    validity_start_date TEXT, validity_end_date TEXT,
    PRIMARY KEY (business_partner, address_id)
);
CREATE TABLE IF NOT EXISTS products (
    product TEXT PRIMARY KEY, product_type TEXT, product_old_id TEXT,
    product_group TEXT, base_unit TEXT, division TEXT, industry_sector TEXT,
    gross_weight REAL, net_weight REAL, weight_unit TEXT,
    is_marked_for_deletion INTEGER DEFAULT 0,
    creation_date TEXT, created_by_user TEXT
);
CREATE TABLE IF NOT EXISTS product_descriptions (
    product TEXT, language TEXT, product_description TEXT,
    PRIMARY KEY (product, language)
);
CREATE TABLE IF NOT EXISTS plants (
    plant TEXT PRIMARY KEY, plant_name TEXT, sales_organization TEXT,
    distribution_channel TEXT, division TEXT, factory_calendar TEXT,
    address_id TEXT, is_marked_for_archiving INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS customer_company_assignments (
    customer TEXT, company_code TEXT, payment_terms TEXT,
    reconciliation_account TEXT, customer_account_group TEXT,
    deletion_indicator INTEGER DEFAULT 0,
    PRIMARY KEY (customer, company_code)
);
CREATE TABLE IF NOT EXISTS customer_sales_area_assignments (
    customer TEXT, sales_organization TEXT, distribution_channel TEXT,
    division TEXT, currency TEXT, customer_payment_terms TEXT,
    incoterms_classification TEXT, incoterms_location TEXT, shipping_condition TEXT,
    PRIMARY KEY (customer, sales_organization, distribution_channel, division)
);
CREATE TABLE IF NOT EXISTS sales_order_headers (
    sales_order TEXT PRIMARY KEY, sales_order_type TEXT, sales_organization TEXT,
    distribution_channel TEXT, sold_to_party TEXT, total_net_amount REAL,
    transaction_currency TEXT, overall_delivery_status TEXT,
    overall_billing_status TEXT, pricing_date TEXT, creation_date TEXT,
    created_by_user TEXT, requested_delivery_date TEXT,
    header_billing_block_reason TEXT, delivery_block_reason TEXT,
    customer_payment_terms TEXT, incoterms_classification TEXT
);
CREATE TABLE IF NOT EXISTS sales_order_items (
    sales_order TEXT, sales_order_item TEXT, material TEXT,
    sales_order_item_category TEXT, requested_quantity REAL,
    requested_quantity_unit TEXT, net_amount REAL, transaction_currency TEXT,
    material_group TEXT, production_plant TEXT, storage_location TEXT,
    item_billing_block_reason TEXT, rejection_reason TEXT,
    PRIMARY KEY (sales_order, sales_order_item)
);
CREATE TABLE IF NOT EXISTS sales_order_schedule_lines (
    sales_order TEXT, sales_order_item TEXT, schedule_line TEXT,
    confirmed_delivery_date TEXT, order_quantity_unit TEXT, confirmed_order_qty REAL,
    PRIMARY KEY (sales_order, sales_order_item, schedule_line)
);
CREATE TABLE IF NOT EXISTS outbound_delivery_headers (
    delivery_document TEXT PRIMARY KEY, shipping_point TEXT,
    overall_goods_movement_status TEXT, overall_picking_status TEXT,
    hdr_general_incompletion_status TEXT, header_billing_block_reason TEXT,
    delivery_block_reason TEXT, actual_goods_movement_date TEXT, creation_date TEXT
);
CREATE TABLE IF NOT EXISTS outbound_delivery_items (
    delivery_document TEXT, delivery_document_item TEXT,
    reference_sales_order TEXT, reference_sales_order_item TEXT,
    plant TEXT, storage_location TEXT, actual_delivery_quantity REAL,
    delivery_quantity_unit TEXT, batch TEXT, item_billing_block_reason TEXT,
    PRIMARY KEY (delivery_document, delivery_document_item)
);
CREATE TABLE IF NOT EXISTS billing_document_headers (
    billing_document TEXT PRIMARY KEY, billing_document_type TEXT,
    accounting_document TEXT, sold_to_party TEXT, company_code TEXT,
    fiscal_year TEXT, total_net_amount REAL, transaction_currency TEXT,
    billing_document_date TEXT, creation_date TEXT,
    is_cancelled INTEGER DEFAULT 0, cancelled_billing_document TEXT
);
CREATE TABLE IF NOT EXISTS billing_document_items (
    billing_document TEXT, billing_document_item TEXT, material TEXT,
    reference_delivery_doc TEXT, reference_delivery_item TEXT,
    billing_quantity REAL, billing_quantity_unit TEXT, net_amount REAL,
    transaction_currency TEXT,
    PRIMARY KEY (billing_document, billing_document_item)
);
CREATE TABLE IF NOT EXISTS payments_accounts_receivable (
    company_code TEXT, fiscal_year TEXT, accounting_document TEXT,
    accounting_document_item TEXT, customer TEXT,
    amount_in_transaction_currency REAL, transaction_currency TEXT,
    amount_in_company_code_currency REAL, company_code_currency TEXT,
    clearing_date TEXT, clearing_accounting_document TEXT,
    posting_date TEXT, document_date TEXT,
    gl_account TEXT, profit_center TEXT, invoice_reference TEXT, sales_document TEXT,
    PRIMARY KEY (company_code, fiscal_year, accounting_document, accounting_document_item)
);
CREATE TABLE IF NOT EXISTS journal_entry_items_ar (
    company_code TEXT, fiscal_year TEXT, accounting_document TEXT,
    accounting_document_item TEXT, billing_document_ref TEXT, customer TEXT,
    gl_account TEXT, profit_center TEXT, cost_center TEXT,
    amount_in_transaction_currency REAL, transaction_currency TEXT,
    amount_in_company_code_currency REAL, company_code_currency TEXT,
    posting_date TEXT, document_date TEXT, accounting_document_type TEXT,
    clearing_date TEXT, clearing_accounting_document TEXT,
    PRIMARY KEY (company_code, fiscal_year, accounting_document, accounting_document_item)
);
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id TEXT PRIMARY KEY, node_type TEXT NOT NULL,
    ref_id TEXT NOT NULL, label TEXT, metadata TEXT
);
CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id TEXT PRIMARY KEY, src_node TEXT NOT NULL, dst_node TEXT NOT NULL,
    edge_type TEXT NOT NULL, metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_graph_edges_src  ON graph_edges(src_node);
CREATE INDEX IF NOT EXISTS idx_graph_edges_dst  ON graph_edges(dst_node);
CREATE INDEX IF NOT EXISTS idx_graph_edges_type ON graph_edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_type ON graph_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_ref  ON graph_nodes(ref_id);
CREATE INDEX IF NOT EXISTS idx_so_sold_to        ON sales_order_headers(sold_to_party);
CREATE INDEX IF NOT EXISTS idx_soi_material      ON sales_order_items(material);
CREATE INDEX IF NOT EXISTS idx_del_items_ref_so  ON outbound_delivery_items(reference_sales_order);
CREATE INDEX IF NOT EXISTS idx_bill_acct_doc     ON billing_document_headers(accounting_document);
CREATE INDEX IF NOT EXISTS idx_pay_acct_doc      ON payments_accounts_receivable(accounting_document);
CREATE INDEX IF NOT EXISTS idx_journal_bill_ref  ON journal_entry_items_ar(billing_document_ref);
"""

# ── Domain table loaders ──────────────────────────────────────────────────────

def load_business_partners(conn):
    rows = load_jsonl("business_partners")
    conn.executemany("""
        INSERT OR REPLACE INTO business_partners VALUES (?,?,?,?,?,?,?,?,?,?)
    """, [(
        r["businessPartner"], r.get("customer"), r.get("businessPartnerFullName"),
        r.get("businessPartnerName"), r.get("businessPartnerCategory"),
        r.get("businessPartnerGrouping"),
        int(r.get("businessPartnerIsBlocked", False)),
        int(r.get("isMarkedForArchiving", False)),
        parse_date(r.get("creationDate")), r.get("createdByUser")
    ) for r in rows])
    log.info(f"  → business_partners: {len(rows)} rows inserted")


def load_business_partner_addresses(conn):
    rows = load_jsonl("business_partner_addresses")
    conn.executemany("""
        INSERT OR REPLACE INTO business_partner_addresses VALUES (?,?,?,?,?,?,?,?,?,?)
    """, [(
        r["businessPartner"], r.get("addressId"), r.get("cityName"),
        r.get("streetName"), r.get("postalCode"), r.get("region"), r.get("country"),
        r.get("addressTimeZone"),
        parse_date(r.get("validityStartDate")), parse_date(r.get("validityEndDate"))
    ) for r in rows])


def load_products(conn):
    rows = load_jsonl("products")
    conn.executemany("""
        INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [(
        r["product"], r.get("productType"), r.get("productOldId"),
        r.get("productGroup"), r.get("baseUnit"), r.get("division"),
        r.get("industrySector"),
        safe_numeric(r.get("grossWeight")), safe_numeric(r.get("netWeight")),
        r.get("weightUnit"), int(r.get("isMarkedForDeletion", False)),
        parse_date(r.get("creationDate")), r.get("createdByUser")
    ) for r in rows])

    desc_rows = load_jsonl("product_descriptions")
    conn.executemany("""
        INSERT OR REPLACE INTO product_descriptions VALUES (?,?,?)
    """, [(r["product"], r.get("language"), r.get("productDescription")) for r in desc_rows])


def load_plants(conn):
    rows = load_jsonl("plants")
    conn.executemany("""
        INSERT OR REPLACE INTO plants VALUES (?,?,?,?,?,?,?,?)
    """, [(
        r["plant"], r.get("plantName"), r.get("salesOrganization"),
        r.get("distributionChannel"), r.get("division"), r.get("factoryCalendar"),
        r.get("addressId"), int(r.get("isMarkedForArchiving", False))
    ) for r in rows])


def load_customer_assignments(conn):
    rows = load_jsonl("customer_company_assignments")
    conn.executemany("""
        INSERT OR REPLACE INTO customer_company_assignments VALUES (?,?,?,?,?,?)
    """, [(
        r["customer"], r.get("companyCode"), r.get("paymentTerms"),
        r.get("reconciliationAccount"), r.get("customerAccountGroup"),
        int(r.get("deletionIndicator", False))
    ) for r in rows])

    rows2 = load_jsonl("customer_sales_area_assignments")
    conn.executemany("""
        INSERT OR REPLACE INTO customer_sales_area_assignments VALUES (?,?,?,?,?,?,?,?,?)
    """, [(
        r["customer"], r.get("salesOrganization"), r.get("distributionChannel"),
        r.get("division"), r.get("currency"), r.get("customerPaymentTerms"),
        r.get("incotermsClassification"), r.get("incotermsLocation1"),
        r.get("shippingCondition")
    ) for r in rows2])


def load_sales_orders(conn):
    headers = load_jsonl("sales_order_headers")
    conn.executemany("""
        INSERT OR REPLACE INTO sales_order_headers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [(
        r["salesOrder"], r.get("salesOrderType"), r.get("salesOrganization"),
        r.get("distributionChannel"), r.get("soldToParty"),
        safe_numeric(r.get("totalNetAmount")), r.get("transactionCurrency"),
        r.get("overallDeliveryStatus"), r.get("overallOrdReltdBillgStatus"),
        parse_date(r.get("pricingDate")), parse_date(r.get("creationDate")),
        r.get("createdByUser"), parse_date(r.get("requestedDeliveryDate")),
        r.get("headerBillingBlockReason"), r.get("deliveryBlockReason"),
        r.get("customerPaymentTerms"), r.get("incotermsClassification")
    ) for r in headers])

    items = load_jsonl("sales_order_items")
    conn.executemany("""
        INSERT OR REPLACE INTO sales_order_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [(
        r["salesOrder"], r["salesOrderItem"], r.get("material"),
        r.get("salesOrderItemCategory"), safe_numeric(r.get("requestedQuantity")),
        r.get("requestedQuantityUnit"), safe_numeric(r.get("netAmount")),
        r.get("transactionCurrency"), r.get("materialGroup"),
        r.get("productionPlant"), r.get("storageLocation"),
        r.get("itemBillingBlockReason"), r.get("salesDocumentRjcnReason")
    ) for r in items])

    schedules = load_jsonl("sales_order_schedule_lines")
    conn.executemany("""
        INSERT OR REPLACE INTO sales_order_schedule_lines VALUES (?,?,?,?,?,?)
    """, [(
        r["salesOrder"], r["salesOrderItem"], r["scheduleLine"],
        parse_date(r.get("confirmedDeliveryDate")), r.get("orderQuantityUnit"),
        safe_numeric(r.get("confdOrderQtyByMatlAvailCheck"))
    ) for r in schedules])


def load_deliveries(conn):
    headers = load_jsonl("outbound_delivery_headers")
    conn.executemany("""
        INSERT OR REPLACE INTO outbound_delivery_headers VALUES (?,?,?,?,?,?,?,?,?)
    """, [(
        r["deliveryDocument"], r.get("shippingPoint"),
        r.get("overallGoodsMovementStatus"), r.get("overallPickingStatus"),
        r.get("hdrGeneralIncompletionStatus"), r.get("headerBillingBlockReason"),
        r.get("deliveryBlockReason"),
        parse_date(r.get("actualGoodsMovementDate")),
        parse_date(r.get("creationDate"))
    ) for r in headers])

    items = load_jsonl("outbound_delivery_items")
    conn.executemany("""
        INSERT OR REPLACE INTO outbound_delivery_items VALUES (?,?,?,?,?,?,?,?,?,?)
    """, [(
        r["deliveryDocument"], r["deliveryDocumentItem"],
        r.get("referenceSdDocument"), r.get("referenceSdDocumentItem"),
        r.get("plant"), r.get("storageLocation"),
        safe_numeric(r.get("actualDeliveryQuantity")),
        r.get("deliveryQuantityUnit"), r.get("batch"),
        r.get("itemBillingBlockReason")
    ) for r in items])


def load_billing(conn):
    # Combine headers + cancellations (cancellations are a subset with is_cancelled=True)
    headers   = load_jsonl("billing_document_headers")
    cancels   = load_jsonl("billing_document_cancellations")

    all_docs = {r["billingDocument"]: r for r in headers}
    # Cancellations override/update headers
    for r in cancels:
        all_docs[r["billingDocument"]] = r

    rows = list(all_docs.values())
    conn.executemany("""
        INSERT OR REPLACE INTO billing_document_headers VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, [(
        r["billingDocument"], r.get("billingDocumentType"),
        r.get("accountingDocument"), r.get("soldToParty"),
        r.get("companyCode"), r.get("fiscalYear"),
        safe_numeric(r.get("totalNetAmount")), r.get("transactionCurrency"),
        parse_date(r.get("billingDocumentDate")), parse_date(r.get("creationDate")),
        int(r.get("billingDocumentIsCancelled", False)),
        r.get("cancelledBillingDocument")
    ) for r in rows])
    log.info(f"  → billing_document_headers: {len(rows)} rows (headers + cancellations merged)")

    items = load_jsonl("billing_document_items")
    conn.executemany("""
        INSERT OR REPLACE INTO billing_document_items VALUES (?,?,?,?,?,?,?,?,?)
    """, [(
        r["billingDocument"], r["billingDocumentItem"], r.get("material"),
        r.get("referenceSdDocument"), r.get("referenceSdDocumentItem"),
        safe_numeric(r.get("billingQuantity")), r.get("billingQuantityUnit"),
        safe_numeric(r.get("netAmount")), r.get("transactionCurrency")
    ) for r in items])


def load_payments_and_journal(conn):
    payments = load_jsonl("payments_accounts_receivable")
    conn.executemany("""
        INSERT OR REPLACE INTO payments_accounts_receivable VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [(
        r["companyCode"], r["fiscalYear"], r["accountingDocument"],
        r["accountingDocumentItem"], r.get("customer"),
        safe_numeric(r.get("amountInTransactionCurrency")), r.get("transactionCurrency"),
        safe_numeric(r.get("amountInCompanyCodeCurrency")), r.get("companyCodeCurrency"),
        parse_date(r.get("clearingDate")), r.get("clearingAccountingDocument"),
        parse_date(r.get("postingDate")), parse_date(r.get("documentDate")),
        r.get("glAccount"), r.get("profitCenter"),
        r.get("invoiceReference"), r.get("salesDocument")
    ) for r in payments])

    journal = load_jsonl("journal_entry_items_accounts_receivable")
    conn.executemany("""
        INSERT OR REPLACE INTO journal_entry_items_ar VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [(
        r["companyCode"], r["fiscalYear"], r["accountingDocument"],
        r["accountingDocumentItem"], r.get("referenceDocument"),
        r.get("customer"), r.get("glAccount"), r.get("profitCenter"),
        r.get("costCenter"),
        safe_numeric(r.get("amountInTransactionCurrency")), r.get("transactionCurrency"),
        safe_numeric(r.get("amountInCompanyCodeCurrency")), r.get("companyCodeCurrency"),
        parse_date(r.get("postingDate")), parse_date(r.get("documentDate")),
        r.get("accountingDocumentType"),
        parse_date(r.get("clearingDate")), r.get("clearingAccountingDocument")
    ) for r in journal])


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_graph(conn):
    """
    Derive graph_nodes and graph_edges from the loaded domain tables.
    Node types: Customer, Product, Plant, SalesOrder, Delivery, BillingDoc, Payment, JournalEntry
    Edge types: ORDERED_BY, HAS_ITEM, HAS_DELIVERY, HAS_BILLING, HAS_PAYMENT,
                HAS_JOURNAL_ENTRY, REFERENCES_PRODUCT, SHIPS_FROM_PLANT
    """
    log.info("Building graph nodes...")

    nodes = []  # (node_id, node_type, ref_id, label, metadata_json)
    edges = []  # (edge_id, src, dst, edge_type, metadata_json)

    def add_node(ntype, ref, label, meta=None):
        nid = node_id(ntype, ref)
        nodes.append((nid, ntype, ref, label, json.dumps(meta or {})))
        return nid

    def add_edge(etype, src, dst, meta=None):
        eid = f"{etype}:{src}:{dst}"
        edges.append((eid, src, dst, etype, json.dumps(meta or {})))

    # ── Customer nodes
    for row in conn.execute("SELECT business_partner, full_name FROM business_partners"):
        add_node("Customer", row[0], row[1] or row[0], {"customer_id": row[0]})

    # ── Product nodes (with description)
    for row in conn.execute("""
        SELECT p.product, COALESCE(pd.product_description, p.product) as desc,
               p.product_type, p.product_group
        FROM products p
        LEFT JOIN product_descriptions pd ON p.product = pd.product AND pd.language = 'EN'
    """):
        add_node("Product", row[0], row[1],
                 {"product_id": row[0], "type": row[2], "group": row[3]})

    # ── Plant nodes
    for row in conn.execute("SELECT plant, plant_name FROM plants"):
        add_node("Plant", row[0], row[1] or row[0], {"plant_id": row[0]})

    # ── Sales Order nodes + edges
    for row in conn.execute("""
        SELECT sales_order, sold_to_party, total_net_amount,
               transaction_currency, overall_delivery_status,
               overall_billing_status, creation_date
        FROM sales_order_headers
    """):
        so_id = row[0]
        nid = add_node("SalesOrder", so_id,
                       f"SO {so_id}",
                       {"sales_order": so_id, "amount": row[2],
                        "currency": row[3], "delivery_status": row[4],
                        "billing_status": row[5], "date": row[6]})
        # Edge: SalesOrder → Customer
        if row[1]:
            add_edge("ORDERED_BY", nid, node_id("Customer", row[1]),
                     {"sold_to_party": row[1]})

    # ── SalesOrder → Product edges (via items)
    for row in conn.execute("""
        SELECT DISTINCT sales_order, material, net_amount,
                        requested_quantity, requested_quantity_unit
        FROM sales_order_items WHERE material IS NOT NULL
    """):
        so_nid  = node_id("SalesOrder", row[0])
        prd_nid = node_id("Product", row[1])
        add_edge("CONTAINS_PRODUCT", so_nid, prd_nid,
                 {"amount": row[2], "qty": row[3], "unit": row[4]})

    # ── Delivery nodes + edges
    for row in conn.execute("""
        SELECT delivery_document, overall_goods_movement_status,
               overall_picking_status, actual_goods_movement_date, creation_date
        FROM outbound_delivery_headers
    """):
        del_id = row[0]
        add_node("Delivery", del_id, f"Delivery {del_id}",
                 {"delivery_doc": del_id, "goods_movement_status": row[1],
                  "picking_status": row[2], "movement_date": row[3],
                  "creation_date": row[4]})

    # Delivery → SalesOrder edges (via delivery items)
    for row in conn.execute("""
        SELECT DISTINCT delivery_document, reference_sales_order
        FROM outbound_delivery_items
        WHERE reference_sales_order IS NOT NULL
    """):
        del_nid = node_id("Delivery", row[0])
        so_nid  = node_id("SalesOrder", row[1])
        add_edge("FULFILLS_ORDER", del_nid, so_nid)

    # Delivery → Plant edges
    for row in conn.execute("""
        SELECT DISTINCT delivery_document, plant
        FROM outbound_delivery_items
        WHERE plant IS NOT NULL AND plant != ''
    """):
        del_nid   = node_id("Delivery", row[0])
        plant_nid = node_id("Plant", row[1])
        add_edge("SHIPS_FROM", del_nid, plant_nid)

    # ── Billing Document nodes + edges
    for row in conn.execute("""
        SELECT billing_document, sold_to_party, total_net_amount,
               transaction_currency, billing_document_date,
               is_cancelled, accounting_document
        FROM billing_document_headers
    """):
        bill_id = row[0]
        add_node("BillingDoc", bill_id, f"Bill {bill_id}",
                 {"billing_doc": bill_id, "amount": row[2],
                  "currency": row[3], "date": row[4],
                  "is_cancelled": bool(row[5]),
                  "accounting_doc": row[6]})
        # BillingDoc → Customer
        if row[1]:
            add_edge("BILLED_TO", node_id("BillingDoc", bill_id),
                     node_id("Customer", row[1]))

    # BillingDoc → Delivery edges (via billing items)
    for row in conn.execute("""
        SELECT DISTINCT billing_document, reference_delivery_doc
        FROM billing_document_items
        WHERE reference_delivery_doc IS NOT NULL AND reference_delivery_doc != ''
    """):
        bill_nid = node_id("BillingDoc", row[0])
        del_nid  = node_id("Delivery", row[1])
        add_edge("BILLS_DELIVERY", bill_nid, del_nid)

    # BillingDoc → Product edges (via billing items)
    for row in conn.execute("""
        SELECT DISTINCT billing_document, material
        FROM billing_document_items
        WHERE material IS NOT NULL AND material != ''
    """):
        bill_nid = node_id("BillingDoc", row[0])
        prd_nid  = node_id("Product", row[1])
        add_edge("BILLS_PRODUCT", bill_nid, prd_nid)

    # ── Payment nodes + edges
    # Group by accounting_document (one payment per accounting doc)
    for row in conn.execute("""
        SELECT accounting_document, customer,
               SUM(amount_in_transaction_currency), transaction_currency,
               clearing_date, posting_date
        FROM payments_accounts_receivable
        GROUP BY accounting_document, customer, transaction_currency, clearing_date, posting_date
    """):
        acct_doc = row[0]
        pay_nid = add_node("Payment", acct_doc, f"Payment {acct_doc}",
                           {"accounting_doc": acct_doc, "customer": row[1],
                            "amount": row[2], "currency": row[3],
                            "clearing_date": row[4], "posting_date": row[5]})
        # Payment → Customer
        if row[1]:
            add_edge("PAID_BY", pay_nid, node_id("Customer", row[1]))

        # Payment → BillingDoc (via shared accounting_document)
        for bill_row in conn.execute("""
            SELECT billing_document FROM billing_document_headers
            WHERE accounting_document = ?
        """, (acct_doc,)):
            add_edge("PAYMENT_FOR", pay_nid, node_id("BillingDoc", bill_row[0]))

    # ── Journal Entry nodes + edges
    for row in conn.execute("""
        SELECT accounting_document, billing_document_ref, customer,
               SUM(amount_in_transaction_currency), transaction_currency,
               posting_date, accounting_document_type
        FROM journal_entry_items_ar
        GROUP BY accounting_document, billing_document_ref, customer,
                 transaction_currency, posting_date, accounting_document_type
    """):
        acct_doc = row[0]
        je_nid = add_node("JournalEntry", acct_doc, f"JE {acct_doc}",
                          {"accounting_doc": acct_doc, "billing_ref": row[1],
                           "customer": row[2], "amount": row[3],
                           "currency": row[4], "posting_date": row[5],
                           "doc_type": row[6]})
        # JournalEntry → BillingDoc
        if row[1]:
            add_edge("RECORDS_BILLING", je_nid, node_id("BillingDoc", row[1]))

    # ── Persist nodes and edges
    log.info(f"  Inserting {len(nodes)} graph nodes...")
    conn.executemany("""
        INSERT OR REPLACE INTO graph_nodes VALUES (?,?,?,?,?)
    """, nodes)

    log.info(f"  Inserting {len(edges)} graph edges...")
    conn.executemany("""
        INSERT OR REPLACE INTO graph_edges VALUES (?,?,?,?,?)
    """, edges)

    # Summary
    log.info("Graph summary:")
    for row in conn.execute("SELECT node_type, COUNT(*) FROM graph_nodes GROUP BY node_type ORDER BY COUNT(*) DESC"):
        log.info(f"  {row[0]:<20} {row[1]} nodes")
    log.info("Edge type summary:")
    for row in conn.execute("SELECT edge_type, COUNT(*) FROM graph_edges GROUP BY edge_type ORDER BY COUNT(*) DESC"):
        log.info(f"  {row[0]:<25} {row[1]} edges")


# ── Main ─────────────────────────────────────────────────────────────────────

def run():
    log.info(f"Starting ETL — DB: {DB_PATH}")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")   # OFF during bulk load, ON after

    log.info("Creating schema...")
    conn.executescript(SCHEMA_SQL)

    log.info("Loading domain tables...")
    load_business_partners(conn)
    load_business_partner_addresses(conn)
    load_products(conn)
    load_plants(conn)
    load_customer_assignments(conn)
    load_sales_orders(conn)
    load_deliveries(conn)
    load_billing(conn)
    load_payments_and_journal(conn)

    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()

    log.info("Building graph layer...")
    build_graph(conn)
    conn.commit()

    conn.close()
    log.info(f"ETL complete ✓  DB written to: {DB_PATH}")


if __name__ == "__main__":
    run()
