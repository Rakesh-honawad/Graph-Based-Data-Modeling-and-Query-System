-- ============================================================
-- O2C Graph System — SQLite Schema (TEXT used in place of JSONB for SQLite compatibility)
-- Order-to-Cash: Sales Order → Delivery → Billing → Payment
-- ============================================================

-- ─────────────────────────────────────────────
-- DOMAIN TABLES (business entities)
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS business_partners (
    business_partner        TEXT PRIMARY KEY,
    customer                TEXT,
    full_name               TEXT,
    partner_name            TEXT,
    partner_category        TEXT,
    partner_grouping        TEXT,
    is_blocked              BOOLEAN DEFAULT FALSE,
    is_marked_for_archiving BOOLEAN DEFAULT FALSE,
    creation_date           DATE,
    created_by_user         TEXT
);

CREATE TABLE IF NOT EXISTS business_partner_addresses (
    business_partner    TEXT REFERENCES business_partners(business_partner),
    address_id          TEXT,
    city_name           TEXT,
    street_name         TEXT,
    postal_code         TEXT,
    region              TEXT,
    country             TEXT,
    address_timezone    TEXT,
    validity_start_date DATE,
    validity_end_date   DATE,
    PRIMARY KEY (business_partner, address_id)
);

CREATE TABLE IF NOT EXISTS products (
    product                 TEXT PRIMARY KEY,
    product_type            TEXT,
    product_old_id          TEXT,
    product_group           TEXT,
    base_unit               TEXT,
    division                TEXT,
    industry_sector         TEXT,
    gross_weight            NUMERIC,
    net_weight              NUMERIC,
    weight_unit             TEXT,
    is_marked_for_deletion  BOOLEAN DEFAULT FALSE,
    creation_date           DATE,
    created_by_user         TEXT
);

CREATE TABLE IF NOT EXISTS product_descriptions (
    product             TEXT REFERENCES products(product),
    language            TEXT,
    product_description TEXT,
    PRIMARY KEY (product, language)
);

CREATE TABLE IF NOT EXISTS plants (
    plant                           TEXT PRIMARY KEY,
    plant_name                      TEXT,
    sales_organization              TEXT,
    distribution_channel            TEXT,
    division                        TEXT,
    factory_calendar                TEXT,
    address_id                      TEXT,
    is_marked_for_archiving         BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS customer_company_assignments (
    customer                TEXT REFERENCES business_partners(business_partner),
    company_code            TEXT,
    payment_terms           TEXT,
    reconciliation_account  TEXT,
    customer_account_group  TEXT,
    deletion_indicator      BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (customer, company_code)
);

CREATE TABLE IF NOT EXISTS customer_sales_area_assignments (
    customer                    TEXT REFERENCES business_partners(business_partner),
    sales_organization          TEXT,
    distribution_channel        TEXT,
    division                    TEXT,
    currency                    TEXT,
    customer_payment_terms      TEXT,
    incoterms_classification    TEXT,
    incoterms_location          TEXT,
    shipping_condition          TEXT,
    PRIMARY KEY (customer, sales_organization, distribution_channel, division)
);

-- ─────────────────────────────────────────────
-- CORE O2C FLOW TABLES
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sales_order_headers (
    sales_order                     TEXT PRIMARY KEY,
    sales_order_type                TEXT,
    sales_organization              TEXT,
    distribution_channel            TEXT,
    sold_to_party                   TEXT REFERENCES business_partners(business_partner),
    total_net_amount                NUMERIC,
    transaction_currency            TEXT,
    overall_delivery_status         TEXT,  -- A=not started, B=partial, C=complete
    overall_billing_status          TEXT,
    pricing_date                    DATE,
    creation_date                   DATE,
    created_by_user                 TEXT,
    requested_delivery_date         DATE,
    header_billing_block_reason     TEXT,
    delivery_block_reason           TEXT,
    customer_payment_terms          TEXT,
    incoterms_classification        TEXT
);

CREATE TABLE IF NOT EXISTS sales_order_items (
    sales_order                     TEXT REFERENCES sales_order_headers(sales_order),
    sales_order_item                TEXT,
    material                        TEXT REFERENCES products(product),
    sales_order_item_category       TEXT,
    requested_quantity              NUMERIC,
    requested_quantity_unit         TEXT,
    net_amount                      NUMERIC,
    transaction_currency            TEXT,
    material_group                  TEXT,
    production_plant                TEXT,
    storage_location                TEXT,
    item_billing_block_reason       TEXT,
    rejection_reason                TEXT,
    PRIMARY KEY (sales_order, sales_order_item)
);

CREATE TABLE IF NOT EXISTS sales_order_schedule_lines (
    sales_order                         TEXT,
    sales_order_item                     TEXT,
    schedule_line                        TEXT,
    confirmed_delivery_date             DATE,
    order_quantity_unit                 TEXT,
    confirmed_order_qty                 NUMERIC,
    PRIMARY KEY (sales_order, sales_order_item, schedule_line),
    FOREIGN KEY (sales_order, sales_order_item)
        REFERENCES sales_order_items(sales_order, sales_order_item)
);

CREATE TABLE IF NOT EXISTS outbound_delivery_headers (
    delivery_document               TEXT PRIMARY KEY,
    shipping_point                  TEXT,
    overall_goods_movement_status   TEXT,  -- A=not started, B=partial, C=complete
    overall_picking_status          TEXT,
    hdr_general_incompletion_status TEXT,
    header_billing_block_reason     TEXT,
    delivery_block_reason           TEXT,
    actual_goods_movement_date      DATE,
    creation_date                   DATE
);

CREATE TABLE IF NOT EXISTS outbound_delivery_items (
    delivery_document           TEXT REFERENCES outbound_delivery_headers(delivery_document),
    delivery_document_item      TEXT,
    -- FK back to sales order
    reference_sales_order       TEXT,
    reference_sales_order_item  TEXT,
    plant                       TEXT REFERENCES plants(plant),
    storage_location            TEXT,
    actual_delivery_quantity    NUMERIC,
    delivery_quantity_unit      TEXT,
    batch                       TEXT,
    item_billing_block_reason   TEXT,
    PRIMARY KEY (delivery_document, delivery_document_item)
);

CREATE TABLE IF NOT EXISTS billing_document_headers (
    billing_document            TEXT PRIMARY KEY,
    billing_document_type       TEXT,
    accounting_document         TEXT,      -- links to payments & journal entries
    sold_to_party               TEXT REFERENCES business_partners(business_partner),
    company_code                TEXT,
    fiscal_year                 TEXT,
    total_net_amount            NUMERIC,
    transaction_currency        TEXT,
    billing_document_date       DATE,
    creation_date               DATE,
    is_cancelled                BOOLEAN DEFAULT FALSE,
    cancelled_billing_document  TEXT
);

CREATE TABLE IF NOT EXISTS billing_document_items (
    billing_document        TEXT REFERENCES billing_document_headers(billing_document),
    billing_document_item   TEXT,
    material                TEXT REFERENCES products(product),
    -- reference_sd_document is the DELIVERY document
    reference_delivery_doc  TEXT REFERENCES outbound_delivery_headers(delivery_document),
    reference_delivery_item TEXT,
    billing_quantity        NUMERIC,
    billing_quantity_unit   TEXT,
    net_amount              NUMERIC,
    transaction_currency    TEXT,
    PRIMARY KEY (billing_document, billing_document_item)
);

CREATE TABLE IF NOT EXISTS payments_accounts_receivable (
    company_code                TEXT,
    fiscal_year                 TEXT,
    accounting_document         TEXT,      -- links to billing_document_headers.accounting_document
    accounting_document_item    TEXT,
    customer                    TEXT REFERENCES business_partners(business_partner),
    amount_in_transaction_currency  NUMERIC,
    transaction_currency            TEXT,
    amount_in_company_code_currency NUMERIC,
    company_code_currency           TEXT,
    clearing_date               DATE,
    clearing_accounting_document TEXT,
    posting_date                DATE,
    document_date               DATE,
    gl_account                  TEXT,
    profit_center               TEXT,
    invoice_reference           TEXT,
    sales_document              TEXT,
    PRIMARY KEY (company_code, fiscal_year, accounting_document, accounting_document_item)
);

CREATE TABLE IF NOT EXISTS journal_entry_items_ar (
    company_code                TEXT,
    fiscal_year                 TEXT,
    accounting_document         TEXT,
    accounting_document_item    TEXT,
    -- reference_document is the BILLING document
    billing_document_ref        TEXT REFERENCES billing_document_headers(billing_document),
    customer                    TEXT REFERENCES business_partners(business_partner),
    gl_account                  TEXT,
    profit_center               TEXT,
    cost_center                 TEXT,
    amount_in_transaction_currency  NUMERIC,
    transaction_currency            TEXT,
    amount_in_company_code_currency NUMERIC,
    company_code_currency           TEXT,
    posting_date                DATE,
    document_date               DATE,
    accounting_document_type    TEXT,
    clearing_date               DATE,
    clearing_accounting_document TEXT,
    PRIMARY KEY (company_code, fiscal_year, accounting_document, accounting_document_item)
);

-- ─────────────────────────────────────────────
-- GRAPH TABLES (virtual graph layer)
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id     TEXT PRIMARY KEY,   -- e.g. "SalesOrder:740506"
    node_type   TEXT NOT NULL,      -- SalesOrder, Delivery, BillingDoc, Payment, Customer, Product, Plant
    ref_id      TEXT NOT NULL,      -- the domain PK
    label       TEXT,               -- human-readable label
    metadata    TEXT               -- key attributes for display
);

CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id     TEXT PRIMARY KEY,   -- e.g. "HAS_DELIVERY:740506:80737721"
    src_node    TEXT NOT NULL REFERENCES graph_nodes(node_id),
    dst_node    TEXT NOT NULL REFERENCES graph_nodes(node_id),
    edge_type   TEXT NOT NULL,      -- ORDERED_BY, HAS_DELIVERY, HAS_BILLING, PAID_BY, etc.
    metadata    TEXT
);

-- Indexes for fast graph traversal
CREATE INDEX IF NOT EXISTS idx_graph_edges_src  ON graph_edges(src_node);
CREATE INDEX IF NOT EXISTS idx_graph_edges_dst  ON graph_edges(dst_node);
CREATE INDEX IF NOT EXISTS idx_graph_edges_type ON graph_edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_type ON graph_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_ref  ON graph_nodes(ref_id);

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_so_sold_to        ON sales_order_headers(sold_to_party);
CREATE INDEX IF NOT EXISTS idx_soi_material      ON sales_order_items(material);
CREATE INDEX IF NOT EXISTS idx_del_items_ref_so  ON outbound_delivery_items(reference_sales_order);
CREATE INDEX IF NOT EXISTS idx_bill_acct_doc     ON billing_document_headers(accounting_document);
CREATE INDEX IF NOT EXISTS idx_pay_acct_doc      ON payments_accounts_receivable(accounting_document);
CREATE INDEX IF NOT EXISTS idx_journal_acct_doc  ON journal_entry_items_ar(accounting_document);
CREATE INDEX IF NOT EXISTS idx_journal_bill_ref  ON journal_entry_items_ar(billing_document_ref);
