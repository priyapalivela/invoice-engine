"""
database.py — PostgreSQL connection and invoice storage.
Tables created automatically on first run.
"""

import os
import json
import psycopg2
import psycopg2.extras
from pathlib import Path
from dotenv import load_dotenv
import streamlit as st

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)


def get_connection():
    try:
        cfg      = st.secrets
        host     = cfg["PG_HOST"]
        port     = cfg["PG_PORT"]
        dbname   = cfg["PG_DB"]
        user     = cfg["PG_USER"]
        password = cfg["PG_PASSWORD"]
    except Exception:
        host     = os.getenv("PG_HOST", "localhost")
        port     = os.getenv("PG_PORT", 5432)
        dbname   = os.getenv("PG_DB", "invoices_db")
        user     = os.getenv("PG_USER", "postgres")
        password = os.getenv("PG_PASSWORD", "")

    return psycopg2.connect(
        host=host, port=port, dbname=dbname, user=user, password=password,
        sslmode="require" if host != "localhost" else "prefer",
    )


# ── Schema ────────────────────────────────────────────────────────────────────

CREATE_INVOICES = """
CREATE TABLE IF NOT EXISTS invoices (
    id                  SERIAL PRIMARY KEY,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    vendor_name         TEXT,
    vendor_address      TEXT,
    vendor_email        TEXT,
    vendor_phone        TEXT,
    vendor_tax_id       TEXT,
    buyer_name          TEXT,
    buyer_address       TEXT,
    invoice_number      TEXT,
    po_number           TEXT,
    invoice_date        DATE,
    due_date            DATE,
    terms               TEXT,
    currency            TEXT,
    subtotal            NUMERIC(14,2),
    discount            NUMERIC(14,2),
    tax_total           NUMERIC(14,2),
    grand_total         NUMERIC(14,2),
    notes               TEXT,
    confidence          TEXT,
    flagged_fields      TEXT[],
    field_scores        JSONB,
    fraud_flags         JSONB,
    document_type       TEXT,
    raw_json            JSONB
);
"""

CREATE_LINE_ITEMS = """
CREATE TABLE IF NOT EXISTS invoice_line_items (
    id              SERIAL PRIMARY KEY,
    invoice_id      INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
    description     TEXT,
    quantity        NUMERIC(10,3),
    unit_price      NUMERIC(14,2),
    tax             NUMERIC(14,2),
    amount          NUMERIC(14,2)
);
"""

MIGRATIONS = [
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS field_scores JSONB;",
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS fraud_flags JSONB;",
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS document_type TEXT;",
    "ALTER TABLE invoice_line_items ALTER COLUMN tax TYPE NUMERIC(14,2);",
]


def init_db():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_INVOICES)
            cur.execute(CREATE_LINE_ITEMS)
            for migration in MIGRATIONS:
                try:
                    cur.execute(migration)
                except Exception:
                    pass
        conn.commit()


# ── check_duplicate ───────────────────────────────────────────────────────────

def check_duplicate(invoice_number: str) -> dict | None:
    """Return existing record if invoice_number already exists, else None."""
    if not invoice_number:
        return None
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, vendor_name, invoice_date, grand_total "
                "FROM invoices WHERE invoice_number = %s;",
                (invoice_number,)
            )
            row = cur.fetchone()
            return dict(row) if row else None


# ── save_invoice ──────────────────────────────────────────────────────────────

def save_invoice(data: dict) -> int:
    v     = data.get("vendor", {})
    b     = data.get("buyer", {})
    m     = data.get("invoice_meta", {})
    t     = data.get("totals", {})
    conf  = data.get("confidence", {})
    fraud = data.get("fraud_flags", {})

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO invoices (
                    vendor_name, vendor_address, vendor_email, vendor_phone, vendor_tax_id,
                    buyer_name, buyer_address,
                    invoice_number, po_number, invoice_date, due_date, terms, currency,
                    subtotal, discount, tax_total, grand_total,
                    notes, confidence, flagged_fields, field_scores,
                    fraud_flags, document_type, raw_json
                ) VALUES (
                    %(vendor_name)s, %(vendor_address)s, %(vendor_email)s,
                    %(vendor_phone)s, %(vendor_tax_id)s,
                    %(buyer_name)s, %(buyer_address)s,
                    %(invoice_number)s, %(po_number)s,
                    %(invoice_date)s, %(due_date)s, %(terms)s, %(currency)s,
                    %(subtotal)s, %(discount)s, %(tax_total)s, %(grand_total)s,
                    %(notes)s, %(confidence)s, %(flagged_fields)s, %(field_scores)s,
                    %(fraud_flags)s, %(document_type)s, %(raw_json)s
                )
                RETURNING id;
            """, {
                "vendor_name":    v.get("name"),
                "vendor_address": v.get("address"),
                "vendor_email":   v.get("email"),
                "vendor_phone":   v.get("phone"),
                "vendor_tax_id":  v.get("tax_id"),
                "buyer_name":     b.get("name"),
                "buyer_address":  b.get("address"),
                "invoice_number": m.get("invoice_number"),
                "po_number":      m.get("po_number"),
                "invoice_date":   m.get("invoice_date") or None,
                "due_date":       m.get("due_date") or None,
                "terms":          m.get("terms"),
                "currency":       m.get("currency"),
                "subtotal":       t.get("subtotal"),
                "discount":       t.get("discount"),
                "tax_total":      t.get("tax_total"),
                "grand_total":    t.get("grand_total"),
                "notes":          data.get("notes"),
                "confidence":     conf.get("overall"),
                "flagged_fields": conf.get("flagged_fields") or [],
                "field_scores":   json.dumps(conf.get("field_scores") or {}),
                "fraud_flags":    json.dumps(fraud),
                "document_type":  data.get("document_type", "invoice"),
                "raw_json":       json.dumps(data),
            })

            invoice_id = cur.fetchone()[0]

            for item in data.get("line_items", []):
                cur.execute("""
                    INSERT INTO invoice_line_items
                        (invoice_id, description, quantity, unit_price, tax, amount)
                    VALUES (%s, %s, %s, %s, %s, %s);
                """, (
                    invoice_id,
                    item.get("description"),
                    item.get("quantity"),
                    item.get("unit_price"),
                    item.get("tax"),
                    item.get("amount"),
                ))

        conn.commit()
    return invoice_id


# ── get_all_invoices ──────────────────────────────────────────────────────────

def get_all_invoices(
    vendor: str = "",
    date_from: str = "",
    date_to: str = "",
    min_amount: float = None,
    max_amount: float = None,
    confidence: str = "",
    risk: str = "",
) -> list[dict]:
    conditions = []
    params = []

    if vendor:
        conditions.append("LOWER(vendor_name) LIKE LOWER(%s)")
        params.append(f"%{vendor}%")
    if date_from:
        conditions.append("invoice_date >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("invoice_date <= %s")
        params.append(date_to)
    if min_amount is not None:
        conditions.append("grand_total >= %s")
        params.append(min_amount)
    if max_amount is not None:
        conditions.append("grand_total <= %s")
        params.append(max_amount)
    if confidence:
        conditions.append("confidence = %s")
        params.append(confidence)
    if risk:
        conditions.append("fraud_flags->>'risk_level' = %s")
        params.append(risk)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                SELECT id, created_at, invoice_number, vendor_name, buyer_name,
                       invoice_date, due_date, currency, grand_total, confidence,
                       document_type,
                       fraud_flags->>'risk_level' as risk_level,
                       fraud_flags->>'is_suspicious' as is_suspicious
                FROM invoices
                {where}
                ORDER BY created_at DESC;
            """, params)
            return [dict(r) for r in cur.fetchall()]


# ── get_invoice_by_id ─────────────────────────────────────────────────────────

def get_invoice_by_id(invoice_id: int) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM invoices WHERE id = %s;", (invoice_id,))
            row = cur.fetchone()
            if not row:
                return None
            result = dict(row)
            cur.execute(
                "SELECT * FROM invoice_line_items WHERE invoice_id = %s;",
                (invoice_id,)
            )
            result["line_items"] = [dict(r) for r in cur.fetchall()]
            return result


# ── get_vendor_summary ────────────────────────────────────────────────────────

def get_vendor_summary() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    vendor_name,
                    COUNT(*) as invoice_count,
                    SUM(grand_total) as total_spend,
                    MAX(grand_total) as largest_invoice,
                    MIN(invoice_date) as first_invoice,
                    MAX(invoice_date) as last_invoice,
                    currency
                FROM invoices
                WHERE vendor_name IS NOT NULL
                GROUP BY vendor_name, currency
                ORDER BY total_spend DESC NULLS LAST;
            """)
            return [dict(r) for r in cur.fetchall()]


# ── get_all_invoices_for_export ───────────────────────────────────────────────

def get_all_invoices_for_export() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, created_at, invoice_number, po_number,
                       vendor_name, vendor_email, vendor_phone, vendor_tax_id,
                       buyer_name, invoice_date, due_date, terms, currency,
                       subtotal, discount, tax_total, grand_total,
                       confidence, document_type,
                       fraud_flags->>'risk_level' as risk_level,
                       notes
                FROM invoices ORDER BY created_at DESC;
            """)
            return [dict(r) for r in cur.fetchall()]
