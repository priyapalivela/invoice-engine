"""
database.py — PostgreSQL connection and invoice storage.

Tables created automatically on first run:
  - invoices        (one row per invoice, all scalar fields)
  - invoice_line_items  (child rows, foreign key → invoices)
"""

import os
import json
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    """Return a new psycopg2 connection using env vars."""
    return psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=os.getenv("PG_PORT", 5432),
        dbname=os.getenv("PG_DB", "invoices_db"),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", ""),
    )


# ── Schema setup ──────────────────────────────────────────────────────────────

CREATE_INVOICES = """
CREATE TABLE IF NOT EXISTS invoices (
    id                  SERIAL PRIMARY KEY,
    created_at          TIMESTAMPTZ DEFAULT NOW(),

    -- vendor
    vendor_name         TEXT,
    vendor_address      TEXT,
    vendor_email        TEXT,
    vendor_phone        TEXT,
    vendor_tax_id       TEXT,

    -- buyer
    buyer_name          TEXT,
    buyer_address       TEXT,

    -- invoice meta
    invoice_number      TEXT,
    po_number           TEXT,
    invoice_date        DATE,
    due_date            DATE,
    terms               TEXT,
    currency            TEXT,

    -- totals
    subtotal            NUMERIC(14,2),
    discount            NUMERIC(14,2),
    tax_total           NUMERIC(14,2),
    grand_total         NUMERIC(14,2),

    -- extras
    notes               TEXT,
    confidence          TEXT,
    flagged_fields      TEXT[],

    -- raw payload (always useful to keep)
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
    tax             NUMERIC(6,2),
    amount          NUMERIC(14,2)
);
"""


def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_INVOICES)
            cur.execute(CREATE_LINE_ITEMS)
        conn.commit()


# ── Save invoice ──────────────────────────────────────────────────────────────

def save_invoice(data: dict) -> int:
    """
    Insert an extracted invoice dict into the database.

    Args:
        data: The dict returned by extractor.extract_invoice()

    Returns:
        The new invoice row's id (integer).
    """
    v    = data.get("vendor", {})
    b    = data.get("buyer", {})
    m    = data.get("invoice_meta", {})
    t    = data.get("totals", {})
    conf = data.get("confidence", {})

    with get_connection() as conn:
        with conn.cursor() as cur:

            # 1. Insert main invoice row
            cur.execute("""
                INSERT INTO invoices (
                    vendor_name, vendor_address, vendor_email, vendor_phone, vendor_tax_id,
                    buyer_name, buyer_address,
                    invoice_number, po_number, invoice_date, due_date, terms, currency,
                    subtotal, discount, tax_total, grand_total,
                    notes, confidence, flagged_fields, raw_json
                ) VALUES (
                    %(vendor_name)s, %(vendor_address)s, %(vendor_email)s,
                    %(vendor_phone)s, %(vendor_tax_id)s,
                    %(buyer_name)s, %(buyer_address)s,
                    %(invoice_number)s, %(po_number)s,
                    %(invoice_date)s, %(due_date)s, %(terms)s, %(currency)s,
                    %(subtotal)s, %(discount)s, %(tax_total)s, %(grand_total)s,
                    %(notes)s, %(confidence)s, %(flagged_fields)s, %(raw_json)s
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
                "raw_json":       json.dumps(data),
            })

            invoice_id = cur.fetchone()[0]

            # 2. Insert line items
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


# ── Fetch all invoices (for history view) ────────────────────────────────────

def get_all_invoices() -> list[dict]:
    """Return all invoices ordered by newest first (no line items)."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, created_at, invoice_number, vendor_name, buyer_name,
                       invoice_date, due_date, currency, grand_total, confidence
                FROM invoices
                ORDER BY created_at DESC;
            """)
            return [dict(r) for r in cur.fetchall()]


def get_invoice_by_id(invoice_id: int) -> dict | None:
    """Return a single invoice with its line items."""
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
