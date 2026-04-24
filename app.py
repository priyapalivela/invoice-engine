"""
Invoice Extraction Engine — Streamlit UI
Run with: streamlit run app.py
"""

import json
import os
import tempfile

import streamlit as st
from dotenv import load_dotenv

from extractor import extract_invoice
from database import init_db, save_invoice, get_all_invoices, get_invoice_by_id

load_dotenv()

# ── Init DB tables on startup ─────────────────────────────────────────────────
try:
    init_db()
    db_ok = True
except Exception as e:
    db_ok = False
    db_error = str(e)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Invoice Extractor", page_icon="🧾", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 2rem; }
    .metric-card {
        background: #f8f9fa; border-radius: 10px;
        padding: 1rem 1.25rem; border: 1px solid #e9ecef; margin-bottom: 0.5rem;
    }
    .metric-label { font-size: 0.75rem; color: #6c757d; text-transform: uppercase; letter-spacing: 0.05em; }
    .metric-value { font-size: 1rem; font-weight: 500; color: #212529; margin-top: 2px; }
    .null-value   { color: #adb5bd; font-style: italic; }
    .conf-high    { background:#d1fae5; color:#065f46; padding:3px 10px; border-radius:99px; font-size:0.8rem; font-weight:600; }
    .conf-medium  { background:#fef3c7; color:#92400e; padding:3px 10px; border-radius:99px; font-size:0.8rem; font-weight:600; }
    .conf-low     { background:#fee2e2; color:#991b1b; padding:3px 10px; border-radius:99px; font-size:0.8rem; font-weight:600; }
    .section-head { font-size:0.7rem; font-weight:600; text-transform:uppercase; letter-spacing:0.08em; color:#9ca3af; margin-bottom:0.5rem; }
    .saved-badge  { background:#dbeafe; color:#1e40af; padding:3px 10px; border-radius:99px; font-size:0.8rem; font-weight:600; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def field_card(label, value, prefix="", suffix=""):
    v = '<span class="null-value">—</span>' if (value is None or value == "") else f"{prefix}{value}{suffix}"
    return f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{v}</div></div>'

def conf_badge(level):
    cls = {"high": "conf-high", "medium": "conf-medium", "low": "conf-low"}.get(level, "conf-low")
    return f'<span class="{cls}">{(level or "unknown").upper()}</span>'

def render_invoice(data: dict, invoice_id: int | None = None):
    """Render extracted invoice data — shared by Extract and History tabs."""
    m    = data.get("invoice_meta", {})
    v    = data.get("vendor", {})
    b    = data.get("buyer", {})
    t    = data.get("totals", {})
    conf = data.get("confidence", {})
    cur  = m.get("currency") or ""

    level   = conf.get("overall", "low")
    flagged = conf.get("flagged_fields", [])

    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        st.markdown(f"**Confidence:** {conf_badge(level)}", unsafe_allow_html=True)
    with c2:
        if flagged:
            st.warning(f"Flagged: {', '.join(flagged)}")
    with c3:
        if invoice_id:
            st.markdown(f'<span class="saved-badge">✓ Saved — DB ID #{invoice_id}</span>', unsafe_allow_html=True)

    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown('<div class="section-head">Invoice details</div>', unsafe_allow_html=True)
        for label, key in [("Invoice #","invoice_number"),("PO #","po_number"),
                            ("Invoice date","invoice_date"),("Due date","due_date"),
                            ("Terms","terms"),("Currency","currency")]:
            st.markdown(field_card(label, m.get(key)), unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="section-head">Vendor</div>', unsafe_allow_html=True)
        for label, key in [("Name","name"),("Address","address"),
                            ("Email","email"),("Phone","phone"),("Tax ID","tax_id")]:
            st.markdown(field_card(label, v.get(key)), unsafe_allow_html=True)

    with col3:
        st.markdown('<div class="section-head">Bill to</div>', unsafe_allow_html=True)
        for label, key in [("Name","name"),("Address","address")]:
            st.markdown(field_card(label, b.get(key)), unsafe_allow_html=True)

    st.divider()
    st.markdown('<div class="section-head">Line items</div>', unsafe_allow_html=True)
    items = data.get("line_items", [])
    if items:
        st.dataframe(
            items,
            use_container_width=True,
            column_config={
                "description": st.column_config.TextColumn("Description", width="large"),
                "quantity":    st.column_config.NumberColumn("Qty"),
                "unit_price":  st.column_config.NumberColumn("Unit price", format=f"{cur} %.2f"),
                "tax":         st.column_config.NumberColumn("Tax %"),
                "amount":      st.column_config.NumberColumn("Amount",     format=f"{cur} %.2f"),
            },
            hide_index=True,
        )

    st.divider()
    st.markdown('<div class="section-head">Totals</div>', unsafe_allow_html=True)
    tc1, tc2, tc3, tc4 = st.columns(4)
    for col, label, key in [(tc1,"Subtotal","subtotal"),(tc2,"Discount","discount"),
                             (tc3,"Tax total","tax_total"),(tc4,"Grand total","grand_total")]:
        amt = t.get(key)
        col.metric(label, f"{cur} {amt:,.2f}" if amt is not None else "—")

    if data.get("notes"):
        st.divider()
        st.markdown('<div class="section-head">Notes</div>', unsafe_allow_html=True)
        st.info(data["notes"])

    st.divider()
    with st.expander("View raw JSON"):
        st.json(data)
    st.download_button(
        "⬇ Download JSON",
        data=json.dumps(data, indent=2),
        file_name=f"invoice_{invoice_id or 'extracted'}.json",
        mime="application/json",
    )


# ── DB warning banner ─────────────────────────────────────────────────────────
if not db_ok:
    st.error(f"⚠️ Database not connected: {db_error} — check your .env PG_* settings.")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_extract, tab_history = st.tabs(["⚡ Extract", "📋 History"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — EXTRACT
# ══════════════════════════════════════════════════════════════════════════════
with tab_extract:
    st.title("🧾 Invoice Extractor")
    st.caption("Upload an invoice — Claude extracts the data and saves it to the database automatically.")

    uploaded = st.file_uploader(
        "Upload invoice",
        type=["pdf", "png", "jpg", "jpeg", "webp"],
        label_visibility="collapsed",
    )

    if uploaded:
        size_kb = len(uploaded.getvalue()) / 1024
        st.info(f"📄 **{uploaded.name}** — {size_kb:.1f} KB")

        if st.button("⚡ Extract & Save", type="primary"):

            # Step 1 — Extract with Claude
            with st.spinner("Extracting with Claude..."):
                suffix = os.path.splitext(uploaded.name)[1]
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(uploaded.getvalue())
                    tmp_path = tmp.name
                try:
                    data = extract_invoice(tmp_path)
                except Exception as e:
                    st.error(f"Extraction failed: {e}")
                    st.stop()
                finally:
                    os.unlink(tmp_path)

            st.success("✓ Extraction complete")

            # Step 2 — Auto-save to PostgreSQL
            invoice_id = None
            if db_ok:
                with st.spinner("Saving to database..."):
                    try:
                        invoice_id = save_invoice(data)
                        st.success(f"✓ Saved to PostgreSQL — ID #{invoice_id}")
                    except Exception as e:
                        st.warning(f"Extraction succeeded but DB save failed: {e}")
            else:
                st.warning("DB not connected — results shown but not saved.")

            # Step 3 — Render results
            render_invoice(data, invoice_id)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — HISTORY
# ══════════════════════════════════════════════════════════════════════════════
with tab_history:
    st.title("📋 Invoice History")
    st.caption("All previously extracted invoices from the database.")

    if not db_ok:
        st.error("Database not connected. Fix your .env to see history.")
        st.stop()

    if st.button("🔄 Refresh"):
        st.rerun()

    try:
        rows = get_all_invoices()
    except Exception as e:
        st.error(f"Could not load history: {e}")
        st.stop()

    if not rows:
        st.info("No invoices saved yet. Upload one in the Extract tab.")
    else:
        st.caption(f"{len(rows)} invoice(s) on record.")
        st.dataframe(
            rows,
            use_container_width=True,
            column_config={
                "id":             st.column_config.NumberColumn("ID",       width="small"),
                "created_at":     st.column_config.DatetimeColumn("Saved",  format="DD MMM YYYY, HH:mm"),
                "invoice_number": st.column_config.TextColumn("Invoice #"),
                "vendor_name":    st.column_config.TextColumn("Vendor"),
                "buyer_name":     st.column_config.TextColumn("Buyer"),
                "invoice_date":   st.column_config.DateColumn("Date"),
                "due_date":       st.column_config.DateColumn("Due"),
                "currency":       st.column_config.TextColumn("Cur",        width="small"),
                "grand_total":    st.column_config.NumberColumn("Total",    format="%.2f"),
                "confidence":     st.column_config.TextColumn("Conf"),
            },
            hide_index=True,
        )

        st.divider()
        st.markdown("**View full invoice details**")
        inv_id = st.number_input("Enter invoice ID", min_value=1, step=1, value=rows[0]["id"])
        if st.button("Load invoice"):
            record = get_invoice_by_id(int(inv_id))
            if record:
                raw = record.get("raw_json")
                display_data = raw if isinstance(raw, dict) else json.loads(raw)
                render_invoice(display_data, inv_id)
            else:
                st.error(f"No invoice found with ID {inv_id}")