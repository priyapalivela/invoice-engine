"""
TrackBook — Invoice Intelligence Engine
NxtWave · nxtwave.ca

Features:
  - TrackBook-styled UI (matches Figma reference)
  - Per-field confidence scores with colour bars
  - Logo extraction: images via Pillow crop, PDFs via pdf2image
  - Concurrent batch (ThreadPoolExecutor, 3 workers, unlimited files)
  - Canadian tax detection (HST/GST/PST per province)
  - Enhanced fraud detection + Claude fraud_flags merged
  - Duplicate detection with override
  - Input validation (reject non-invoices)
  - Edit-before-save mode
  - History with filters + CSV export
  - Vendor spend summary chart
  - Camera/receipt scan
  - Simple session-based auth
"""

import json
import os
import io
import csv
import re
import tempfile
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

from extractor import extract_invoice
from database import (
    init_db, save_invoice, get_all_invoices, get_invoice_by_id,
    check_duplicate, get_vendor_summary, get_all_invoices_for_export
)

# ── DB Init ───────────────────────────────────────────────────────────────────
try:
    init_db()
    db_ok = True
except Exception as e:
    db_ok = False
    db_error = str(e)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="TrackBook", page_icon="📒", layout="wide")

# ── TrackBook CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Reset and base */
  * { margin: 0; padding: 0; box-sizing: border-box; }
  
  /* Main container */
  .stApp {
    background: #F4F5F7 !important;
  }
  
  /* Hide Streamlit branding */
  #MainMenu { visibility: hidden !important; }
  footer { visibility: hidden !important; }
  header { visibility: hidden !important; }
  [data-testid="stToolbar"] { display: none !important; }
  [data-testid="stDecoration"] { display: none !important; }
  
  /* Sidebar styling */
  [data-testid="stSidebar"] {
    background: #FFFFFF !important;
    border-right: 1px solid #E5E7EB !important;
  }
  
  [data-testid="stSidebar"] .stButton > button {
    background: #F9FAFB !important;
    color: #374151 !important;
    border: 1px solid #E5E7EB !important;
    border-radius: 8px !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    padding: 8px 12px !important;
  }
  
  [data-testid="stSidebar"] .stButton > button:hover {
    background: #EEF2FF !important;
    color: #1A56E8 !important;
    border-color: #C7D2FE !important;
  }
  
  /* Tab styling */
  [data-testid="stTabs"] [role="tablist"] {
    background: #FFFFFF !important;
    border-bottom: 1px solid #E5E7EB !important;
    border-radius: 12px 12px 0 0 !important;
    padding: 0 1rem !important;
  }
  
  [data-testid="stTabs"] [role="tab"] {
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    color: #6B7280 !important;
    padding: 0.75rem 1.25rem !important;
    border-bottom: 2px solid transparent !important;
  }
  
  [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #1A56E8 !important;
    border-bottom: 2px solid #1A56E8 !important;
    font-weight: 600 !important;
  }
  
  [data-testid="stTabs"] [role="tabpanel"] {
    background: #FFFFFF !important;
    border: 1px solid #E5E7EB !important;
    border-top: none !important;
    border-radius: 0 0 12px 12px !important;
    padding: 1.5rem !important;
  }
  
  /* Custom components */
  .tb-brand {
    padding: 1rem 1.25rem 0.875rem;
    font-size: 1.2rem;
    font-weight: 700;
    color: #111827;
    border-bottom: 1px solid #E5E7EB;
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 1rem;
  }
  
  .tb-brand-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: #1A56E8;
  }
  
  .tb-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 9px;
    border-radius: 99px;
    font-size: 0.72rem;
    font-weight: 600;
  }
  
  .tb-badge-green { background: #DCFCE7; color: #15803D; }
  .tb-badge-red { background: #FEE2E2; color: #B91C1C; }
  .tb-badge-blue { background: #EEF2FF; color: #1A56E8; }
  .tb-badge-amber { background: #FEF3C7; color: #B45309; }
  
  .tb-section-head {
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #9CA3AF;
    margin: 1rem 0 0.5rem;
  }
  
  .tb-field {
    background: #F9FAFB;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 0.6rem 0.85rem;
    margin-bottom: 0.5rem;
  }
  
  .tb-field-label {
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    color: #9CA3AF;
    margin-bottom: 3px;
  }
  
  .tb-field-value {
    font-size: 0.875rem;
    color: #111827;
    font-weight: 500;
  }
  
  .tb-queue-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0.6rem 0.85rem;
    border-radius: 8px;
    background: #F9FAFB;
    border: 1px solid #E5E7EB;
    margin-bottom: 6px;
    font-size: 0.82rem;
  }
  
  .status-pending { color: #9CA3AF; }
  .status-running { color: #1A56E8; }
  .status-done { color: #16a34a; }
  .status-error { color: #dc2626; }
  
  .tb-fraud-box {
    background: #FFF1F2;
    border: 1px solid #FECDD3;
    border-radius: 10px;
    padding: 0.85rem 1rem;
    margin-bottom: 0.75rem;
  }
  
  .tb-dup-box {
    background: #FFFBEB;
    border: 1px solid #FDE68A;
    border-radius: 10px;
    padding: 0.85rem 1rem;
    margin-bottom: 0.75rem;
  }
  
  .tb-ok-box {
    background: #F0FDF4;
    border: 1px solid #BBF7D0;
    border-radius: 10px;
    padding: 0.7rem 1rem;
    font-size: 0.82rem;
    color: #15803D;
  }
  
  .tb-metric-strip {
    display: flex;
    gap: 0.75rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
  }
  
  .tb-metric {
    flex: 1;
    min-width: 120px;
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 0.85rem 1rem;
  }
  
  .tb-metric-label {
    font-size: 0.7rem;
    color: #6B7280;
    font-weight: 500;
    text-transform: uppercase;
  }
  
  .tb-metric-value {
    font-size: 1.25rem;
    font-weight: 700;
    color: #111827;
    margin-top: 4px;
  }
</style>
""", unsafe_allow_html=True)

# ── Auth ──────────────────────────────────────────────────────────────────────
USERS = {os.getenv("AUTH_USER", "admin"): os.getenv("AUTH_PASS", "invoice123")}

def check_auth():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if not st.session_state.authenticated:
        col = st.columns([1, 2, 1])[1]
        with col:
            st.markdown("""
            <div style="text-align:center;padding:2rem 0 1.5rem">
              <div style="font-size:1.8rem;font-weight:800;color:#111827">
                <span style="display:inline-block;width:10px;height:10px;background:#1A56E8;border-radius:50%;margin-right:8px;"></span>
                TrackBook
              </div>
              <div style="font-size:0.85rem;color:#6B7280;margin-top:8px">Invoice Intelligence · NxtWave</div>
            </div>
            """, unsafe_allow_html=True)
            with st.form("login"):
                username = st.text_input("Username", placeholder="admin")
                password = st.text_input("Password", type="password", placeholder="••••••••")
                if st.form_submit_button("Sign in", type="primary", use_container_width=True):
                    if USERS.get(username) == password:
                        st.session_state.authenticated = True
                        st.session_state.username = username
                        st.rerun()
                    else:
                        st.error("Invalid credentials")
        st.stop()

check_auth()

# ── Initialize ALL session state variables ────────────────────────────────────
if 'active_tab' not in st.session_state:
    st.session_state.active_tab = "Extract"
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False
if "auto_save" not in st.session_state:
    st.session_state.auto_save = True
if "scan_edit" not in st.session_state:
    st.session_state.scan_edit = False
if "scan_save" not in st.session_state:
    st.session_state.scan_save = True

# ── Sidebar Navigation ────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div class="tb-brand">
      <span class="tb-brand-dot"></span> TrackBook
    </div>
    """, unsafe_allow_html=True)
    st.caption(f"Signed in as **{st.session_state.get('username', 'user')}**")
    
    if st.button("Sign out", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()
    
    st.divider()
    st.markdown("### Navigation")
    
    # Navigation buttons
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📤 Extract", use_container_width=True,
                    type="primary" if st.session_state.active_tab == "Extract" else "secondary"):
            st.session_state.active_tab = "Extract"
            st.rerun()
        
        if st.button("📋 History", use_container_width=True,
                    type="primary" if st.session_state.active_tab == "History" else "secondary"):
            st.session_state.active_tab = "History"
            st.rerun()
    
    with col2:
        if st.button("📷 Scan", use_container_width=True,
                    type="primary" if st.session_state.active_tab == "Scan" else "secondary"):
            st.session_state.active_tab = "Scan"
            st.rerun()
        
        if st.button("📊 Summary", use_container_width=True,
                    type="primary" if st.session_state.active_tab == "Summary" else "secondary"):
            st.session_state.active_tab = "Summary"
            st.rerun()
    
    st.divider()
    
    if db_ok:
        st.markdown('<span class="tb-badge tb-badge-green">● DB connected</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="tb-badge tb-badge-red">● DB offline</span>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _badge(text: str, kind: str) -> str:
    return f'<span class="tb-badge tb-badge-{kind}">{text}</span>'

def conf_badge(level: str) -> str:
    m = {"high": ("green", "✓ High"), "medium": ("amber", "~ Medium"), "low": ("red", "! Low")}
    kind, label = m.get(level, ("gray", level or "?"))
    return _badge(label, kind)

def risk_badge(level: str) -> str:
    m = {"low": ("green", "▲ Low risk"), "medium": ("amber", "▲ Medium risk"), "high": ("red", "▲ High risk")}
    kind, label = m.get(level, ("gray", level or "?"))
    return _badge(label, kind)

def field_card(label: str, value, score: str = None) -> str:
    v_html = (f'<div class="tb-field-value">{value}</div>'
              if (value is not None and value != "")
              else '<div class="tb-field-null">—</div>')
    return (f'<div class="tb-field">'
            f'<div class="tb-field-label">{label}</div>'
            f'{v_html}'
            f'</div>')

# ── Logo extraction ───────────────────────────────────────────────────────────
def extract_logo(file_bytes: bytes, media_type: str) -> bytes | None:
    import base64 as _b64
    import anthropic

    if media_type == "application/pdf":
        try:
            from pdf2image import convert_from_bytes
            pages = convert_from_bytes(file_bytes, first_page=1, last_page=1, dpi=150)
            if not pages:
                return None
            buf = io.BytesIO()
            pages[0].save(buf, format="PNG")
            file_bytes = buf.getvalue()
            media_type = "image/png"
        except Exception:
            return None

    try:
        b64 = _b64.standard_b64encode(file_bytes).decode("utf-8")
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": (
                        "Does this invoice have a vendor/company logo? "
                        "Reply ONLY with valid JSON:\n"
                        '{"has_logo":true,"x1_pct":5,"y1_pct":2,"x2_pct":28,"y2_pct":18}\n'
                        'No logo: {"has_logo":false}'
                    )}
                ]
            }]
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        info = json.loads(raw)
        if not info.get("has_logo"):
            return None

        from PIL import Image
        img = Image.open(io.BytesIO(file_bytes)).convert("RGBA")
        w, h = img.size
        x1 = max(0, int(info["x1_pct"] / 100 * w) - 10)
        y1 = max(0, int(info["y1_pct"] / 100 * h) - 10)
        x2 = min(w, int(info["x2_pct"] / 100 * w) + 10)
        y2 = min(h, int(info["y2_pct"] / 100 * h) + 10)
        if x2 > x1 and y2 > y1:
            logo = img.crop((x1, y1, x2, y2))
            buf = io.BytesIO()
            logo.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        pass
    return None

def render_logo_header(vendor_name: str, logo_bytes: bytes | None):
    if logo_bytes:
        c1, c2 = st.columns([1, 8])
        with c1:
            st.image(logo_bytes, width=52)
        with c2:
            st.markdown(f'<div class="tb-field-value" style="font-size:1.2rem;margin-top:12px">{vendor_name or "—"}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="tb-field-value" style="font-size:1.2rem">{vendor_name or "—"}</div>', unsafe_allow_html=True)

# ── Canadian Tax ──────────────────────────────────────────────────────────────
_CA_TAX = {
    "AB": (5.0, 0.0, 0.0, "GST only"), "BC": (5.0, 7.0, 0.0, "GST+PST"),
    "MB": (5.0, 7.0, 0.0, "GST+RST"), "NB": (0.0, 0.0, 15.0, "HST"),
    "NL": (0.0, 0.0, 15.0, "HST"), "NS": (0.0, 0.0, 15.0, "HST"),
    "NT": (5.0, 0.0, 0.0, "GST only"), "NU": (5.0, 0.0, 0.0, "GST only"),
    "ON": (0.0, 0.0, 13.0, "HST"), "PE": (0.0, 0.0, 15.0, "HST"),
    "QC": (5.0, 9.975, 0.0, "GST+QST"), "SK": (5.0, 6.0, 0.0, "GST+PST"),
    "YT": (5.0, 0.0, 0.0, "GST only"),
}

def _detect_province(text: str) -> str | None:
    if not text:
        return None
    u = text.upper()
    for code in _CA_TAX:
        if re.search(r'\b' + code + r'\b', u):
            return code
    return None

def canadian_tax_flags(data: dict) -> list[str]:
    flags = []
    v_addr = (data.get("vendor", {}).get("address") or "")
    currency = (data.get("invoice_meta", {}).get("currency") or "").upper()
    is_ca = (currency == "CAD" or "CANADA" in v_addr.upper() or _detect_province(v_addr))
    if not is_ca:
        return flags
    subtotal = float(data.get("totals", {}).get("subtotal") or 0)
    tax_total = float(data.get("totals", {}).get("tax_total") or 0)
    province = _detect_province(v_addr)
    if subtotal > 0 and tax_total > 0 and province:
        eff = tax_total / subtotal * 100
        gst, pst, hst, label = _CA_TAX[province]
        expected = hst if hst else (gst + pst)
        if abs(eff - expected) > 0.6:
            flags.append(f"Tax mismatch: expected {expected:.1f}%, got {eff:.1f}%")
    return flags

def enhanced_fraud_flags(data: dict) -> list[str]:
    flags = []
    m = data.get("invoice_meta", {})
    t = data.get("totals", {})
    items = data.get("line_items", [])
    
    inv_d = m.get("invoice_date")
    due_d = m.get("due_date")
    if inv_d and due_d and due_d < inv_d:
        flags.append(f"Due date ({due_d}) before invoice date ({inv_d})")
    
    amounts = [float(i.get("amount") or 0) for i in items if i.get("amount")]
    if amounts:
        items_sum = sum(amounts)
        grand = float(t.get("grand_total") or 0)
        if grand > 0 and abs(items_sum - grand) > 1.0:
            flags.append(f"Line items sum ({items_sum:,.2f}) ≠ grand total ({grand:,.2f})")
    
    if not m.get("invoice_number"):
        flags.append("Invoice number missing")
    
    return flags

def is_valid_invoice(data: dict) -> tuple[bool, str]:
    doc_type = data.get("document_type", "invoice")
    if doc_type not in ("invoice", "receipt", "bill"):
        return False, f"Document type '{doc_type}' not recognized"
    
    m = data.get("invoice_meta", {})
    v = data.get("vendor", {})
    t = data.get("totals", {})
    null_critical = sum([
        m.get("invoice_number") is None,
        m.get("invoice_date") is None,
        v.get("name") is None,
        t.get("grand_total") is None,
    ])
    
    if null_critical == 4:
        return False, "No invoice fields found"
    return True, ""

def render_fraud_section(fraud: dict, extra_flags: list[str] | None = None):
    fraud = fraud or {}
    risk = fraud.get("risk_level", "low")
    flags = list(fraud.get("flags", [])) + (extra_flags or [])
    
    if flags:
        st.markdown('<div class="tb-fraud-box">🚨 Fraud flags detected</div>', unsafe_allow_html=True)
        for f in flags:
            st.warning(f)
    else:
        st.markdown('<div class="tb-ok-box">✓ No fraud indicators detected</div>', unsafe_allow_html=True)

def render_invoice(data: dict, invoice_id: int = None, editable: bool = False,
                   logo_bytes: bytes | None = None, key_prefix: str = "") -> dict:
    m = data.get("invoice_meta", {})
    v = data.get("vendor", {})
    b = data.get("buyer", {})
    t = data.get("totals", {})
    conf = data.get("confidence", {})
    fraud = data.get("fraud_flags", {})
    cur = m.get("currency") or "USD"
    
    render_logo_header(v.get("name"), logo_bytes)
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Confidence", conf.get('overall', 'low').upper())
    col2.metric("Type", data.get('document_type', 'invoice'))
    col3.metric("Fraud Risk", fraud.get('risk_level', 'low').upper())
    if invoice_id:
        col4.metric("ID", f"#{invoice_id}")
    
    st.divider()
    
    extra = enhanced_fraud_flags(data) + canadian_tax_flags(data)
    render_fraud_section(fraud, extra_flags=extra or None)
    
    if editable:
        st.markdown("**✏️ Edit fields**")
        col1, col2 = st.columns(2)
        with col1:
            v["name"] = st.text_input("Vendor", v.get("name") or "", key=f"{key_prefix}_vendor")
            m["invoice_number"] = st.text_input("Invoice #", m.get("invoice_number") or "", key=f"{key_prefix}_inv_num")
            m["invoice_date"] = st.text_input("Date", m.get("invoice_date") or "", key=f"{key_prefix}_date")
        with col2:
            b["name"] = st.text_input("Buyer", b.get("name") or "", key=f"{key_prefix}_buyer")
            m["currency"] = st.text_input("Currency", m.get("currency") or "", key=f"{key_prefix}_cur")
            raw_total = st.text_input("Total", str(t.get("grand_total") or ""), key=f"{key_prefix}_total")
            try:
                t["grand_total"] = float(raw_total) if raw_total else None
            except ValueError:
                pass
        data["vendor"] = v
        data["buyer"] = b
        data["invoice_meta"] = m
        data["totals"] = t
    else:
        st.markdown('<div class="tb-section-head">Invoice Details</div>', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(field_card("Invoice #", m.get("invoice_number")), unsafe_allow_html=True)
            st.markdown(field_card("Date", m.get("invoice_date")), unsafe_allow_html=True)
        with col2:
            st.markdown(field_card("Vendor", v.get("name")), unsafe_allow_html=True)
            st.markdown(field_card("Tax ID", v.get("tax_id")), unsafe_allow_html=True)
        with col3:
            st.markdown(field_card("Buyer", b.get("name")), unsafe_allow_html=True)
            st.markdown(field_card("Currency", m.get("currency")), unsafe_allow_html=True)
    
    st.divider()
    
    items = data.get("line_items", [])
    if items:
        st.markdown('<div class="tb-section-head">Line Items</div>', unsafe_allow_html=True)
        st.dataframe(items, use_container_width=True, hide_index=True)
    
    st.divider()
    st.markdown('<div class="tb-section-head">Totals</div>', unsafe_allow_html=True)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Subtotal", f"{cur} {t.get('subtotal', 0):,.2f}")
    col2.metric("Tax", f"{cur} {t.get('tax_total', 0):,.2f}")
    col3.metric("Grand Total", f"{cur} {t.get('grand_total', 0):,.2f}")
    
    return data

# ══════════════════════════════════════════════════════════════════════════════
# BATCH PROCESSOR
# ══════════════════════════════════════════════════════════════════════════════
BATCH_WORKERS = 3

def _process_single(uploaded_file, do_logo: bool, do_save: bool) -> dict:
    result = {"name": uploaded_file.name, "status": "error",
              "data": None, "logo_bytes": None, "invoice_id": None,
              "error": None, "dup": None, "rejected": None}
    suffix = os.path.splitext(uploaded_file.name)[1].lower()
    file_bytes = uploaded_file.getvalue()
    
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        data = extract_invoice(tmp_path)
        os.unlink(tmp_path)
    except Exception as e:
        result["error"] = str(e)
        return result
    
    valid, reason = is_valid_invoice(data)
    if not valid:
        result["status"] = "rejected"
        result["rejected"] = reason
        return result
    
    inv_num = data.get("invoice_meta", {}).get("invoice_number")
    dup = check_duplicate(inv_num) if inv_num else None
    result["dup"] = dup
    
    if do_logo:
        mt_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".webp": "image/webp", ".pdf": "application/pdf"}
        media_type = mt_map.get(suffix, "image/png")
        try:
            result["logo_bytes"] = extract_logo(file_bytes, media_type)
        except Exception:
            pass
    
    result["data"] = data
    result["status"] = "extracted"
    
    if do_save and not dup:
        try:
            iid = save_invoice(data)
            result["invoice_id"] = iid
            result["status"] = "saved"
        except Exception as e:
            result["error"] = f"Save failed: {e}"
    
    return result

def render_batch_results(results: list[dict], edit_mode: bool):
    for r in results:
        icon = {"saved": "✅", "extracted": "📄", "rejected": "🚫", "error": "❌"}.get(r["status"], "❓")
        with st.expander(f"{icon} {r['name']}"):
            if r["status"] == "rejected":
                st.error(f"Rejected: {r['rejected']}")
                continue
            if r["status"] == "error":
                st.error(f"Error: {r['error']}")
                continue
            
            data = r["data"]
            
            if r["dup"]:
                dup = r["dup"]
                st.warning(f"⚠️ Duplicate: Already exists as #{dup['id']} - {dup['vendor_name']}")
                if st.button(f"Save anyway", key=f"force_{r['name']}"):
                    if db_ok:
                        iid = save_invoice(data)
                        st.success(f"✓ Saved as #{iid}")
            
            if edit_mode:
                data = render_invoice(data, editable=True, logo_bytes=r["logo_bytes"], key_prefix=r["name"])
                if st.button(f"💾 Save", key=f"save_{r['name']}"):
                    if db_ok:
                        iid = save_invoice(data)
                        st.success(f"✓ Saved #{iid}")
            else:
                render_invoice(data, invoice_id=r.get("invoice_id"), logo_bytes=r["logo_bytes"])

# ══════════════════════════════════════════════════════════════════════════════
# MAIN TABS - ONLY CONTENT GOES INSIDE THESE
# ══════════════════════════════════════════════════════════════════════════════

if not db_ok:
    st.error(f"⚠️ Database not connected: {db_error}")

# Create tabs
tab_extract, tab_scan, tab_history, tab_summary = st.tabs(
    ["📤 Extract", "📷 Scan Receipt", "📋 History", "📊 Spend Summary"]
)

# ============================================
# TAB 1: EXTRACT
# ============================================
with tab_extract:
    st.markdown("""
    <div style="margin-bottom:1.25rem">
      <div style="font-size:1.25rem;font-weight:700;color:#111827">Extract invoices</div>
      <div style="font-size:0.82rem;color:#6B7280;margin-top:2px">
        Upload any number of invoices — processed 3 at a time with full fraud &amp; tax analysis.
      </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Settings row
    col1, col2 = st.columns(2)
    with col1:
        edit_label = "✏️ Edit mode: ON" if st.session_state.edit_mode else "✏️ Edit mode: OFF"
        st.markdown(f'<div style="background:#F3F4F6;padding:8px 14px;border-radius:8px;margin-bottom:8px">{edit_label}</div>', unsafe_allow_html=True)
        if st.button("Toggle edit mode", key="toggle_edit", use_container_width=True):
            st.session_state.edit_mode = not st.session_state.edit_mode
            st.rerun()
    with col2:
        save_label = "💾 Auto-save: ON" if st.session_state.auto_save else "💾 Auto-save: OFF"
        st.markdown(f'<div style="background:#F3F4F6;padding:8px 14px;border-radius:8px;margin-bottom:8px">{save_label}</div>', unsafe_allow_html=True)
        if st.button("Toggle auto-save", key="toggle_save", use_container_width=True):
            st.session_state.auto_save = not st.session_state.auto_save
            st.rerun()
    
    # File uploader
    uploaded_files = st.file_uploader(
        "Upload invoices",
        type=["pdf", "png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        label_visibility="collapsed"
    )
    
    if uploaded_files:
        n = len(uploaded_files)
        workers = min(BATCH_WORKERS, n)
        est = max(1, n // workers) * 12
        
        st.info(f"📁 {n} file(s) selected | {workers} parallel workers | ~{est}s estimated")
        
        if st.button("⚡ Process all", type="primary", use_container_width=True):
            all_results = []
            progress_bar = st.progress(0)
            
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(_process_single, f, True, st.session_state.auto_save and not st.session_state.edit_mode): f 
                          for f in uploaded_files}
                
                for i, future in enumerate(as_completed(futures)):
                    result = future.result()
                    all_results.append(result)
                    progress_bar.progress((i + 1) / n)
            
            progress_bar.empty()
            
            # Summary
            saved = sum(1 for r in all_results if r["status"] == "saved")
            errors = sum(1 for r in all_results if r["status"] == "error")
            st.success(f"✅ {saved} saved | ❌ {errors} errors")
            
            st.divider()
            render_batch_results(all_results, st.session_state.edit_mode)

# ============================================
# TAB 2: SCAN RECEIPT
# ============================================
with tab_scan:
    st.markdown("""
    <div style="margin-bottom:1.25rem">
      <div style="font-size:1.25rem;font-weight:700;color:#111827">Scan a receipt</div>
      <div style="font-size:0.82rem;color:#6B7280;margin-top:2px">
        Point your camera at any receipt or invoice
      </div>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2 = st.columns([1, 1])
    with col1:
        camera_image = st.camera_input("Take a photo", help="Works on mobile and desktop webcam")
    with col2:
        st.markdown("""
        **Tips for best results**
        - Good lighting, no shadows
        - Keep document in frame
        - Avoid glare
        """)
        
        if camera_image:
            col2a, col2b = st.columns(2)
            with col2a:
                scan_edit_label = "✏️ Edit: ON" if st.session_state.scan_edit else "✏️ Edit: OFF"
                st.markdown(f'<div style="background:#F3F4F6;padding:6px 10px;border-radius:6px;font-size:0.8rem;text-align:center">{scan_edit_label}</div>', unsafe_allow_html=True)
                if st.button("Toggle edit", key="scan_edit_btn", use_container_width=True):
                    st.session_state.scan_edit = not st.session_state.scan_edit
                    st.rerun()
            with col2b:
                scan_save_label = "💾 Save: ON" if st.session_state.scan_save else "💾 Save: OFF"
                st.markdown(f'<div style="background:#F3F4F6;padding:6px 10px;border-radius:6px;font-size:0.8rem;text-align:center">{scan_save_label}</div>', unsafe_allow_html=True)
                if st.button("Toggle save", key="scan_save_btn", use_container_width=True):
                    st.session_state.scan_save = not st.session_state.scan_save
                    st.rerun()
            
            do_extract = st.button("⚡ Extract from photo", type="primary", use_container_width=True, key="scan_btn")
    
    if camera_image and do_extract:
        with st.spinner("Reading receipt..."):
            file_bytes = camera_image.getvalue()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            try:
                data = extract_invoice(tmp_path)
            except Exception as e:
                st.error(f"Extraction failed: {e}")
                data = None
            finally:
                os.unlink(tmp_path)
        
        if data:
            valid, reason = is_valid_invoice(data)
            if not valid:
                st.error(f"❌ Rejected: {reason}")
            else:
                st.divider()
                if st.session_state.scan_edit:
                    data = render_invoice(data, editable=True, key_prefix="scan")
                    if st.button("💾 Save scan", key="scan_confirm", type="primary"):
                        if db_ok and st.session_state.scan_save:
                            try:
                                iid = save_invoice(data)
                                st.success(f"✓ Saved as #{iid}")
                            except Exception as e:
                                st.error(f"Save failed: {e}")
                else:
                    render_invoice(data)
                    if db_ok and st.session_state.scan_save:
                        try:
                            iid = save_invoice(data)
                            st.success(f"✓ Saved as #{iid}")
                        except Exception as e:
                            st.error(f"Save failed: {e}")

# ============================================
# TAB 3: HISTORY
# ============================================
with tab_history:
    st.markdown("""
    <div style="margin-bottom:1.25rem">
      <div style="font-size:1.25rem;font-weight:700;color:#111827">Invoice history</div>
    </div>
    """, unsafe_allow_html=True)
    
    if not db_ok:
        st.error("Database not connected.")
        st.stop()
    
    # Filters
    with st.expander("🔍 Filter invoices", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            f_vendor = st.text_input("Vendor name", placeholder="Contains...")
            f_conf = st.selectbox("Confidence", ["All", "high", "medium", "low"])
        with col2:
            f_date_from = st.date_input("Date from", value=None)
            f_date_to = st.date_input("Date to", value=None)
        with col3:
            f_min = st.number_input("Min amount", value=0.0, step=100.0)
            f_max = st.number_input("Max amount", value=0.0, step=100.0)
            f_risk = st.selectbox("Fraud risk", ["All", "low", "medium", "high"])
    
    col_refresh, col_export = st.columns([1, 1])
    with col_refresh:
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()
    
    try:
        rows = get_all_invoices(
            vendor=f_vendor if f_vendor else None,
            date_from=str(f_date_from) if f_date_from else None,
            date_to=str(f_date_to) if f_date_to else None,
            min_amount=f_min if f_min > 0 else None,
            max_amount=f_max if f_max > 0 else None,
            confidence=f_conf if f_conf != "All" else None,
            risk=f_risk if f_risk != "All" else None,
        )
    except Exception as e:
        st.error(f"Could not load history: {e}")
        st.stop()
    
    with col_export:
        if rows:
            export_rows = get_all_invoices_for_export()
            if export_rows:
                out = io.StringIO()
                writer = csv.DictWriter(out, fieldnames=export_rows[0].keys())
                writer.writeheader()
                writer.writerows([{k: str(v) if v is not None else "" for k, v in r.items()} for r in export_rows])
                st.download_button("⬇ Export CSV", data=out.getvalue(),
                    file_name="trackbook_export.csv", mime="text/csv", use_container_width=True)
    
    if not rows:
        st.info("No invoices found.")
    else:
        st.caption(f"{len(rows)} invoice(s)")
        st.dataframe(rows, use_container_width=True, hide_index=True,
            column_config={
                "id": st.column_config.NumberColumn("ID", width="small"),
                "created_at": st.column_config.DatetimeColumn("Saved", format="DD MMM YYYY"),
                "invoice_number": st.column_config.TextColumn("Invoice #"),
                "vendor_name": st.column_config.TextColumn("Vendor"),
                "buyer_name": st.column_config.TextColumn("Buyer"),
                "invoice_date": st.column_config.DateColumn("Date"),
                "due_date": st.column_config.DateColumn("Due"),
                "currency": st.column_config.TextColumn("Cur", width="small"),
                "grand_total": st.column_config.NumberColumn("Total", format="$%.2f"),
                "confidence": st.column_config.TextColumn("Conf", width="small"),
                "risk_level": st.column_config.TextColumn("Risk", width="small"),
            })
        
        st.divider()
        st.markdown("**View full invoice**")
        inv_id = st.number_input("Invoice ID", min_value=1, step=1, value=rows[0]["id"] if rows else 1)
        if st.button("Load invoice", type="primary"):
            record = get_invoice_by_id(int(inv_id))
            if record:
                raw = record.get("raw_json")
                display_data = raw if isinstance(raw, dict) else json.loads(raw)
                import base64 as _b64
                logo_b64 = display_data.get("_logo_b64")
                logo_bytes = _b64.b64decode(logo_b64) if logo_b64 else None
                render_invoice(display_data, inv_id, logo_bytes=logo_bytes)
            else:
                st.error(f"No invoice found with ID {inv_id}")

# ============================================
# TAB 4: SPEND SUMMARY
# ============================================
with tab_summary:
    st.markdown("""
    <div style="margin-bottom:1.25rem">
      <div style="font-size:1.25rem;font-weight:700;color:#111827">Vendor spend summary</div>
    </div>
    """, unsafe_allow_html=True)
    
    if not db_ok:
        st.error("Database not connected.")
        st.stop()
    
    try:
        summary = get_vendor_summary()
    except Exception as e:
        st.error(f"Could not load summary: {e}")
        st.stop()
    
    if not summary:
        st.info("No data yet — extract some invoices first.")
    else:
        total_invoices = sum(r["invoice_count"] for r in summary)
        total_spend = sum(float(r["total_spend"] or 0) for r in summary)
        top_vendor = summary[0]["vendor_name"] if summary else "—"
        avg_invoice = total_spend / total_invoices if total_invoices else 0
        
        # Metrics row
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total invoices", total_invoices)
        col2.metric("Total spend", f"${total_spend:,.0f}")
        col3.metric("Top vendor", top_vendor)
        col4.metric("Avg per invoice", f"${avg_invoice:,.0f}")
        
        st.divider()
        
        # Chart
        import pandas as pd
        df = pd.DataFrame(summary)
        df["total_spend"] = df["total_spend"].astype(float)
        
        st.markdown("### Spend by vendor")
        chart_df = (df[["vendor_name", "total_spend"]]
                    .set_index("vendor_name")
                    .sort_values("total_spend", ascending=False)
                    .head(15))
        st.bar_chart(chart_df, use_container_width=True, height=300)
        
        st.divider()
        st.markdown("### Full breakdown")
        st.dataframe(summary, use_container_width=True, hide_index=True,
            column_config={
                "vendor_name": st.column_config.TextColumn("Vendor", width="large"),
                "invoice_count": st.column_config.NumberColumn("# Invoices"),
                "total_spend": st.column_config.NumberColumn("Total spend", format="$%.2f"),
                "largest_invoice": st.column_config.NumberColumn("Largest", format="$%.2f"),
                "first_invoice": st.column_config.DateColumn("First"),
                "last_invoice": st.column_config.DateColumn("Last"),
                "currency": st.column_config.TextColumn("Currency", width="small"),
            })
      
