"""
TrackBook — Invoice Intelligence Engine
NxtWave · nxtwave.ca

FIXES APPLIED (v2.1):
  FIX 1 — Fraud risk discrepancy: upgraded risk level (Claude + rules) now saved to DB
  FIX 2 — Retry fallback: no longer silently re-calls same function; shows proper error
  FIX 3 — Logo extraction: tested path + clearer status feedback
  FIX 4 — Batch workers: configurable via sidebar slider (1–6), default 3
"""

import json, os, io, csv, re, time, tempfile, threading, queue, hashlib, zipfile, shutil
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

# ── Optional heavy imports ────────────────────────────────────────────────────
try:
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
    import anthropic as _anthropic
    HAS_TENACITY = True
except ImportError:
    HAS_TENACITY = False

from extractor import extract_invoice
from database import (
    init_db, save_invoice, get_all_invoices, get_invoice_by_id,
    check_duplicate, get_vendor_summary, get_all_invoices_for_export,
    #update_invoice_risk_level,   # ← FIX 1: new DB function needed (see note below)
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

# ── Dark mode via query param ─────────────────────────────────────────────────
params = st.query_params
dark_mode = params.get("dark", "0") == "1"

import streamlit.components.v1 as _st_comp

# ══════════════════════════════════════════════════════════════════════════════
# CSS — unchanged from v2.0
# ══════════════════════════════════════════════════════════════════════════════
LIGHT = {
    "bg_app":      "#F4F5F7",
    "bg_white":    "#FFFFFF",
    "bg_soft":     "#F9FAFB",
    "border":      "#E5E7EB",
    "border2":     "#D1D5DB",
    "text":        "#111827",
    "text2":       "#374151",
    "text3":       "#6B7280",
    "text4":       "#9CA3AF",
    "primary":     "#1A56E8",
    "primary_dk":  "#1347C8",
    "primary_bg":  "#EEF2FF",
    "primary_bd":  "#C7D2FE",
}
DARK = {
    "bg_app":      "#0F1117",
    "bg_white":    "#1E2130",
    "bg_soft":     "#161925",
    "border":      "#2D3148",
    "border2":     "#3A3F5C",
    "text":        "#F3F4F6",
    "text2":       "#D1D5DB",
    "text3":       "#9CA3AF",
    "text4":       "#6B7280",
    "primary":     "#4F7EF7",
    "primary_dk":  "#3B6AE8",
    "primary_bg":  "#1A2040",
    "primary_bd":  "#2D3F7A",
}
T = DARK if dark_mode else LIGHT

st.markdown(f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;0,9..40,800&display=swap');

  :root {{
    --bg-app:     {T['bg_app']};
    --bg-white:   {T['bg_white']};
    --bg-soft:    {T['bg_soft']};
    --border:     {T['border']};
    --border2:    {T['border2']};
    --text:       {T['text']};
    --text2:      {T['text2']};
    --text3:      {T['text3']};
    --text4:      {T['text4']};
    --primary:    {T['primary']};
    --primary-dk: {T['primary_dk']};
    --primary-bg: {T['primary_bg']};
    --primary-bd: {T['primary_bd']};
  }}

  *, *::before, *::after {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}

  html, body, [class*="css"], .stApp, .main,
  section[data-testid="stSidebar"],
  [data-testid="stAppViewContainer"] {{
    font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
    transition: background 0.25s, color 0.25s;
  }}

  [data-testid="stAppViewContainer"], .stApp {{
    background: var(--bg-app) !important;
  }}

  #MainMenu, footer, header,
  [data-testid="stToolbar"],
  [data-testid="stDecoration"],
  [data-testid="stStatusWidget"],
  .viewerBadge_container__r5tak {{ display: none !important; visibility: hidden !important; }}

  [data-testid="stSidebar"] {{
    background: var(--bg-white) !important;
    border-right: 1px solid var(--border) !important;
  }}
  [data-testid="stSidebar"] > div {{ background: var(--bg-white) !important; }}
  [data-testid="stSidebar"] .stButton > button {{
    background: var(--bg-soft) !important; color: var(--text2) !important;
    border: 1px solid var(--border) !important; border-radius: 8px !important;
    font-size: 0.82rem !important; width: 100% !important;
    padding: 6px 12px !important; font-weight: 500 !important;
  }}
  [data-testid="stSidebar"] .stButton > button:hover {{
    background: var(--primary-bg) !important; color: var(--primary) !important;
    border-color: var(--primary-bd) !important;
  }}

  .block-container {{ padding: 1.5rem 2rem 3rem !important; max-width: 1300px !important; }}

  [data-testid="stFileUploader"] > div,
  [data-testid="stFileUploaderDropzone"],
  [data-testid="stFileUploaderDropzone"] > div {{
    background: var(--bg-white) !important;
    border-color: var(--border2) !important;
  }}
  [data-testid="stFileUploader"] button,
  [data-testid="stFileUploaderDropzone"] button {{
    background: var(--primary) !important; color: #FFFFFF !important;
    border: none !important; border-radius: 8px !important;
    font-size: 0.82rem !important; font-weight: 600 !important;
  }}
  [data-testid="stFileUploaderDropzoneInstructions"],
  [data-testid="stFileUploaderDropzoneInstructions"] *,
  [data-testid="stFileUploader"] span,
  [data-testid="stFileUploader"] small,
  [data-testid="stFileUploader"] p {{ color: var(--text3) !important; background: transparent !important; }}

  [data-baseweb="input"], [data-baseweb="base-input"] {{
    background: var(--bg-white) !important;
    border: 1px solid var(--border2) !important;
    border-radius: 8px !important;
    overflow: hidden !important;
  }}
  [data-baseweb="input"]:focus-within {{
    border-color: var(--primary) !important;
    box-shadow: 0 0 0 3px rgba(26,86,232,0.12) !important;
  }}
  input[type="text"], input[type="password"], input[type="number"],
  .stTextInput input, .stNumberInput input {{
    background: var(--bg-white) !important;
    color: var(--text) !important;
    border: 1px solid var(--border2) !important;
    border-radius: 8px !important;
    font-size: 0.875rem !important;
    -webkit-text-fill-color: var(--text) !important;
  }}
  textarea, .stTextArea textarea {{
    background: var(--bg-white) !important; color: var(--text) !important;
    border: 1px solid var(--border2) !important; border-radius: 8px !important;
  }}

  [data-baseweb="select"] > div, [data-baseweb="select"] [data-baseweb="control"] {{
    background: var(--bg-white) !important;
    border-color: var(--border2) !important;
    border-radius: 8px !important;
    color: var(--text) !important;
  }}
  [data-baseweb="popover"] {{ background: var(--bg-white) !important; border: 1px solid var(--border) !important; border-radius: 8px !important; }}
  [data-baseweb="menu"] {{ background: var(--bg-white) !important; }}
  [data-baseweb="menu"] li {{ color: var(--text) !important; }}
  [data-baseweb="menu"] li:hover {{ background: var(--primary-bg) !important; }}

  .stButton > button[kind="primary"], [data-testid="baseButton-primary"] {{
    background: var(--primary) !important; color: #FFFFFF !important;
    border: none !important; border-radius: 8px !important;
    font-size: 0.875rem !important; font-weight: 600 !important;
    padding: 10px 22px !important;
    box-shadow: 0 1px 3px rgba(26,86,232,0.3) !important;
    transition: background 0.15s ease, transform 0.1s ease !important;
  }}
  .stButton > button[kind="primary"]:hover {{ background: var(--primary-dk) !important; transform: translateY(-1px) !important; }}
  .stButton > button[kind="primary"]:active {{ transform: translateY(0) !important; }}

  .stButton > button:not([kind="primary"]),
  .stButton > button[kind="secondary"] {{
    background: var(--bg-white) !important; color: var(--text2) !important;
    border: 1px solid var(--border2) !important; border-radius: 8px !important;
    font-size: 0.875rem !important; font-weight: 500 !important; padding: 9px 18px !important;
  }}
  .stButton > button:not([kind="primary"]):hover {{
    background: var(--bg-soft) !important; border-color: var(--text4) !important;
  }}

  button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible,
  [role="tab"]:focus-visible {{
    outline: 2px solid var(--primary) !important;
    outline-offset: 2px !important;
    box-shadow: 0 0 0 4px rgba(26,86,232,0.18) !important;
  }}

  [data-testid="stForm"] {{
    background: var(--bg-white) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important; padding: 1.5rem !important;
  }}
  [data-testid="baseButton-primaryFormSubmit"],
  .stFormSubmitButton > button {{
    background: var(--primary) !important; color: #FFFFFF !important;
    border: none !important; border-radius: 8px !important;
    font-size: 0.9rem !important; font-weight: 600 !important;
    padding: 12px 22px !important; width: 100% !important;
  }}

  [data-testid="stTabs"] [role="tablist"] {{
    background: var(--bg-white) !important;
    border-bottom: 1px solid var(--border) !important;
    padding: 0 1rem !important; border-radius: 12px 12px 0 0 !important;
  }}
  [data-testid="stTabs"] [role="tab"] {{
    font-size: 0.875rem !important; font-weight: 500 !important;
    color: var(--text3) !important; padding: 0.75rem 1.25rem !important;
    border-bottom: 2px solid transparent !important; background: transparent !important;
    transition: color 0.15s !important;
  }}
  [data-testid="stTabs"] [role="tab"]:hover {{ color: var(--text) !important; }}
  [data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
    color: var(--primary) !important;
    border-bottom: 2px solid var(--primary) !important; font-weight: 600 !important;
  }}
  [data-testid="stTabs"] [role="tabpanel"] {{
    background: var(--bg-white) !important;
    border: 1px solid var(--border) !important; border-top: none !important;
    border-radius: 0 0 12px 12px !important; padding: 1.5rem !important;
  }}

  [data-testid="stExpander"], .streamlit-expanderHeader, details > summary {{
    background: var(--bg-soft) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important; font-size: 0.875rem !important;
    font-weight: 500 !important; color: var(--text2) !important;
  }}
  .streamlit-expanderContent, details[open] > div {{
    background: var(--bg-white) !important;
    border: 1px solid var(--border) !important; border-top: none !important;
    border-radius: 0 0 8px 8px !important; padding: 1rem !important;
  }}

  [data-testid="stDataFrame"] {{
    border-radius: 10px !important; overflow: hidden !important;
    border: 1px solid var(--border) !important;
  }}
  [data-testid="stDataFrame"] table {{ background: var(--bg-white) !important; }}
  [data-testid="stDataFrame"] thead tr th {{
    background: var(--bg-soft) !important; color: var(--text3) !important;
    font-size: 0.72rem !important; font-weight: 600 !important;
    text-transform: uppercase !important; letter-spacing: 0.06em !important;
  }}
  [data-testid="stDataFrame"] tbody td {{ color: var(--text) !important; font-size: 0.875rem !important; }}
  [data-testid="stDataFrame"] tbody tr:hover {{ background: var(--bg-soft) !important; }}

  [data-testid="stMetric"] {{
    background: var(--bg-white) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important; padding: 1rem !important;
  }}
  [data-testid="stMetricLabel"] {{
    font-size: 0.72rem !important; color: var(--text3) !important;
    text-transform: uppercase !important; letter-spacing: 0.06em !important;
  }}
  [data-testid="stMetricValue"] {{
    font-size: 1.35rem !important; font-weight: 700 !important; color: var(--text) !important;
  }}

  [data-testid="stAlert"] {{
    border-radius: 8px !important; font-size: 0.875rem !important;
    background: var(--bg-soft) !important;
  }}

  [data-testid="stProgressBar"] {{ background: var(--border) !important; border-radius: 4px !important; }}
  [data-testid="stProgressBar"] > div > div {{ background: var(--primary) !important; border-radius: 4px !important; }}

  [data-testid="stCameraInput"] > div {{
    border: 1.5px dashed var(--border2) !important;
    border-radius: 10px !important; background: var(--bg-soft) !important;
  }}
  [data-testid="stCameraInput"] button {{
    background: var(--primary) !important; color: white !important;
    border-radius: 8px !important; border: none !important; font-weight: 600 !important;
  }}

  label, .stTextInput label, .stNumberInput label, .stSelectbox label,
  [data-testid="stWidgetLabel"] {{
    color: var(--text2) !important; font-size: 0.875rem !important; font-weight: 500 !important;
  }}
  small, .stCaption {{ color: var(--text3) !important; }}

  hr {{ border: none !important; border-top: 1px solid var(--border) !important; margin: 1rem 0 !important; }}

  [data-testid="stSidebarNavItems"],
  [data-testid="stSidebarNavSeparator"],
  [data-testid="stSearchBox"],
  [data-testid="stSidebar"] nav button {{ display: none !important; }}

  @keyframes pulse-soft {{
    0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }}
  }}
  @keyframes spin {{
    to {{ transform: rotate(360deg); }}
  }}
  .tb-loading {{ animation: pulse-soft 1.5s ease-in-out infinite; }}
  .tb-spinner {{
    width: 16px; height: 16px; border: 2px solid var(--border);
    border-top-color: var(--primary); border-radius: 50%;
    animation: spin 0.7s linear infinite; display: inline-block;
  }}

  .tb-brand {{
    padding: 1rem 1.25rem 0.875rem;
    font-size: 1.05rem; font-weight: 700; letter-spacing: -0.3px;
    color: var(--text); border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 8px; margin-bottom: 0.5rem;
  }}
  .tb-brand-dot {{ width: 9px; height: 9px; border-radius: 50%; background: var(--primary); }}
  .tb-page-title {{ font-size: 1.2rem; font-weight: 700; color: var(--text); margin-bottom: 2px; }}
  .tb-page-sub   {{ font-size: 0.82rem; color: var(--text3); margin-bottom: 1.25rem; }}

  .tb-field {{
    background: var(--bg-soft); border: 1px solid var(--border);
    border-radius: 8px; padding: 0.6rem 0.85rem; margin-bottom: 0.5rem;
    transition: border-color 0.15s;
  }}
  .tb-field:hover {{ border-color: var(--border2); }}
  .tb-field-label {{
    font-size: 0.65rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.07em; color: var(--text4);
    display: flex; align-items: center; gap: 5px; margin-bottom: 3px;
  }}
  .tb-field-value {{ font-size: 0.875rem; color: var(--text); font-weight: 500; }}
  .tb-field-null  {{ font-size: 0.875rem; color: var(--border2); font-style: italic; }}
  .tb-conf-bar    {{ height: 2px; border-radius: 1px; margin-top: 5px; }}
  .tb-conf-bar-high   {{ background: #16a34a; width: 100%; }}
  .tb-conf-bar-medium {{ background: #d97706; width: 60%; }}
  .tb-conf-bar-low    {{ background: #dc2626; width: 25%; }}

  .tb-badge {{
    display: inline-flex; align-items: center; gap: 4px;
    padding: 2px 9px; border-radius: 99px;
    font-size: 0.72rem; font-weight: 600; letter-spacing: 0.02em;
  }}
  .tb-badge-green  {{ background: #DCFCE7; color: #15803D; }}
  .tb-badge-amber  {{ background: #FEF3C7; color: #B45309; }}
  .tb-badge-red    {{ background: #FEE2E2; color: #B91C1C; }}
  .tb-badge-blue   {{ background: var(--primary-bg); color: var(--primary); }}
  .tb-badge-gray   {{ background: var(--bg-soft); color: var(--text3); }}

  .tb-logo-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 1rem; }}
  .tb-monogram {{
    width: 48px; height: 48px; border-radius: 10px; background: var(--primary-bg);
    display: flex; align-items: center; justify-content: center;
    font-size: 1rem; font-weight: 800; color: var(--primary); flex-shrink: 0;
  }}
  .tb-vendor-name {{ font-size: 1rem; font-weight: 700; color: var(--text); }}
  .tb-vendor-sub  {{ font-size: 0.78rem; color: var(--text3); margin-top: 2px; }}

  .tb-fraud-box {{
    background: #FFF1F2; border: 1px solid #FECDD3;
    border-radius: 10px; padding: 0.85rem 1rem; margin-bottom: 0.75rem;
  }}
  .tb-fraud-title {{ font-size: 0.8rem; font-weight: 600; color: #B91C1C; margin-bottom: 6px; }}
  .tb-fraud-item  {{ font-size: 0.8rem; color: #7F1D1D; margin-bottom: 3px; }}

  .tb-dup-box {{
    background: #FFFBEB; border: 1px solid #FDE68A;
    border-radius: 10px; padding: 0.85rem 1rem; margin-bottom: 0.75rem;
  }}

  .tb-queue-row {{
    display: flex; align-items: center; gap: 10px;
    padding: 0.6rem 0.85rem; border-radius: 8px;
    background: var(--bg-soft); border: 1px solid var(--border);
    margin-bottom: 6px; font-size: 0.82rem; color: var(--text2);
    transition: background 0.2s;
  }}
  .tb-queue-name {{ flex: 1; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .status-pending  {{ color: var(--text4); }}
  .status-running  {{ color: var(--primary); }}
  .status-done     {{ color: #16a34a; }}
  .status-error    {{ color: #dc2626; }}
  .status-skipped  {{ color: #d97706; }}

  .tb-metric-strip {{ display: flex; gap: 0.75rem; margin-bottom: 1rem; flex-wrap: wrap; }}
  .tb-metric {{
    flex: 1; min-width: 120px; background: var(--bg-white);
    border: 1px solid var(--border); border-radius: 10px; padding: 0.85rem 1rem;
  }}
  .tb-metric-label {{ font-size: 0.7rem; color: var(--text3); font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; }}
  .tb-metric-value {{ font-size: 1.25rem; font-weight: 700; color: var(--text); margin-top: 4px; }}

  .tb-section-head {{
    font-size: 0.65rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--text4); margin: 1rem 0 0.5rem;
  }}
  .tb-ok-box {{
    background: #F0FDF4; border: 1px solid #BBF7D0;
    border-radius: 10px; padding: 0.7rem 1rem;
    font-size: 0.82rem; color: #15803D; margin-bottom: 0.75rem;
  }}

  .tb-thumb-grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 0.75rem; margin-bottom: 1rem;
  }}
  .tb-thumb-card {{
    background: var(--bg-soft); border: 1px solid var(--border);
    border-radius: 8px; overflow: hidden; cursor: pointer;
    transition: box-shadow 0.15s, transform 0.15s;
  }}
  .tb-thumb-card:hover {{ box-shadow: 0 4px 12px rgba(0,0,0,0.1); transform: translateY(-2px); }}
  .tb-thumb-label {{
    padding: 6px 8px; font-size: 0.7rem; font-weight: 500;
    color: var(--text3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}

  .tb-progress-dash {{
    background: var(--bg-soft); border: 1px solid var(--border);
    border-radius: 10px; padding: 1rem; margin-bottom: 1rem;
  }}
  .tb-progress-file {{
    display: flex; align-items: center; gap: 10px;
    padding: 6px 0; border-bottom: 1px solid var(--border);
    font-size: 0.82rem;
  }}
  .tb-progress-file:last-child {{ border-bottom: none; }}
  .tb-progress-bar-wrap {{
    flex: 1; height: 4px; background: var(--border);
    border-radius: 2px; overflow: hidden;
  }}
  .tb-progress-bar-fill {{
    height: 100%; background: var(--primary); border-radius: 2px;
    transition: width 0.3s ease;
  }}

  .tb-footer {{
    position: fixed; bottom: 0; left: 0; right: 0;
    background: var(--bg-white); border-top: 1px solid var(--border);
    padding: 6px 16px; font-size: 0.7rem; color: var(--text4);
    display: flex; align-items: center; justify-content: space-between;
    z-index: 999;
  }}

  @media (max-width: 768px) {{
    .block-container {{ padding: 0.75rem 0.75rem 4rem !important; }}
    .tb-metric-strip {{ gap: 0.5rem; }}
    .tb-metric {{ min-width: 100px; padding: 0.65rem 0.75rem; }}
    .tb-metric-value {{ font-size: 1rem; }}
    [data-testid="stTabs"] [role="tab"] {{ padding: 0.6rem 0.75rem !important; font-size: 0.78rem !important; }}
    .stButton > button {{ font-size: 0.82rem !important; padding: 8px 14px !important; }}
    [data-testid="stCameraInput"] {{ width: 100% !important; }}
    .tb-thumb-grid {{ grid-template-columns: repeat(auto-fill, minmax(100px,1fr)); }}
  }}

  @media print {{
    [data-testid="stSidebar"],
    [data-testid="stToolbar"],
    .stButton, .tb-footer,
    [data-testid="stFileUploader"],
    [data-testid="stTabs"] [role="tablist"] {{ display: none !important; }}
    [data-testid="stTabs"] [role="tabpanel"] {{
      border: none !important; padding: 0 !important;
    }}
    .tb-field {{ break-inside: avoid; }}
  }}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# CLAUDE API ERROR + RETRY
# ══════════════════════════════════════════════════════════════════════════════
class ClaudeAPIError(Exception):
    def __init__(self, message: str, error_type: str = "unknown", retryable: bool = False):
        super().__init__(message)
        self.error_type = error_type
        self.retryable  = retryable

def _wrap_api_call(fn, *args, **kwargs):
    """Call fn with tenacity retry if available, else plain call."""
    if not HAS_TENACITY:
        return fn(*args, **kwargs)
    import anthropic as _a
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((_a.RateLimitError, _a.APIConnectionError)),
        reraise=True,
    )
    def _inner():
        try:
            return fn(*args, **kwargs)
        except _a.RateLimitError as e:
            raise ClaudeAPIError(str(e), "rate_limit", retryable=True) from e
        except _a.APITimeoutError as e:
            raise ClaudeAPIError(str(e), "timeout", retryable=True) from e
        except _a.APIConnectionError as e:
            raise ClaudeAPIError(str(e), "connection", retryable=True) from e
        except _a.APIError as e:
            raise ClaudeAPIError(str(e), "api_error", retryable=False) from e
    return _inner()

# ══════════════════════════════════════════════════════════════════════════════
# LOGO CACHE
# ══════════════════════════════════════════════════════════════════════════════
_CACHE_DIR = Path(tempfile.gettempdir()) / "trackbook_logo_cache"
_CACHE_DIR.mkdir(exist_ok=True)
_CACHE_TTL_DAYS = 7

def _file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()[:16]

def _cache_path(h: str) -> Path:
    return _CACHE_DIR / f"{h}.png"

def _load_logo_from_cache(h: str) -> bytes | None:
    p = _cache_path(h)
    if p.exists():
        age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
        if age < timedelta(days=_CACHE_TTL_DAYS):
            return p.read_bytes()
        p.unlink(missing_ok=True)
    return None

def _save_logo_to_cache(h: str, data: bytes):
    try:
        _cache_path(h).write_bytes(data)
    except Exception:
        pass

def clean_logo_cache():
    removed = 0
    for p in _CACHE_DIR.glob("*.png"):
        age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
        if age >= timedelta(days=_CACHE_TTL_DAYS):
            p.unlink(missing_ok=True)
            removed += 1
    return removed

# ══════════════════════════════════════════════════════════════════════════════
# PDF THUMBNAIL
# ══════════════════════════════════════════════════════════════════════════════
_thumb_mem: dict[str, bytes] = {}

def get_pdf_thumbnail(file_bytes: bytes) -> bytes | None:
    h = _file_hash(file_bytes)
    if h in _thumb_mem:
        return _thumb_mem[h]
    thumb_p = _CACHE_DIR / f"thumb_{h}.png"
    if thumb_p.exists():
        data = thumb_p.read_bytes()
        _thumb_mem[h] = data
        return data
    try:
        from pdf2image import convert_from_bytes
        pages = convert_from_bytes(file_bytes, first_page=1, last_page=1, dpi=100)
        if not pages:
            return None
        buf = io.BytesIO()
        pages[0].save(buf, format="PNG")
        data = buf.getvalue()
        _thumb_mem[h] = data
        try:
            thumb_p.write_bytes(data)
        except Exception:
            pass
        return data
    except Exception:
        return None

# ══════════════════════════════════════════════════════════════════════════════
# PROGRESS TRACKER
# ══════════════════════════════════════════════════════════════════════════════
class ProgressTracker:
    def __init__(self, file_names: list[str]):
        self._lock   = threading.Lock()
        self._files  = {n: {"pct": 0, "status": "pending", "msg": ""} for n in file_names}

    def update(self, name: str, pct: int, status: str = "processing", msg: str = ""):
        with self._lock:
            if name in self._files:
                self._files[name] = {"pct": pct, "status": status, "msg": msg}

    def snapshot(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._files.items()}

    def render_html(self) -> str:
        snap = self.snapshot()
        rows = []
        for name, info in snap.items():
            pct    = info["pct"]
            status = info["status"]
            colour_map = {
                "pending":    "#9CA3AF",
                "processing": "#1A56E8",
                "completed":  "#16a34a",
                "error":      "#dc2626",
            }
            col = colour_map.get(status, "#9CA3AF")
            badge_map = {
                "pending":    ("gray",  "Pending"),
                "processing": ("blue",  "Processing"),
                "completed":  ("green", "Done"),
                "error":      ("red",   "Error"),
            }
            bk, bl = badge_map.get(status, ("gray", status))
            rows.append(
                f'<div class="tb-progress-file">'
                f'<span style="width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text2)">{name}</span>'
                f'<div class="tb-progress-bar-wrap"><div class="tb-progress-bar-fill" style="width:{pct}%;background:{col}"></div></div>'
                f'<span style="width:40px;text-align:right;font-size:0.72rem;color:{col}">{pct}%</span>'
                f'<span class="tb-badge tb-badge-{bk}" style="min-width:80px;justify-content:center">{bl}</span>'
                f'</div>'
            )
        return f'<div class="tb-progress-dash">{"".join(rows)}</div>'

# ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════
USERS = {os.getenv("AUTH_USER", "admin"): os.getenv("AUTH_PASS", "invoice123")}

def check_auth():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if not st.session_state.authenticated:
        col = st.columns([1, 2, 1])[1]
        with col:
            st.markdown(f"""
            <div style="text-align:center;padding:2rem 0 1.5rem">
              <div style="font-size:1.5rem;font-weight:800;letter-spacing:-0.5px;color:var(--text)">
                <span style="display:inline-block;width:10px;height:10px;background:var(--primary);
                  border-radius:50%;margin-right:6px;vertical-align:middle"></span>
                TrackBook
              </div>
              <div style="font-size:0.82rem;color:var(--text3);margin-top:4px">Invoice Intelligence · NxtWave</div>
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

# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════
for k, v in {
    "edit_mode":     False,
    "auto_save":     True,
    "scan_edit":     False,
    "scan_save":     True,
    "authenticated": False,
    "username":      None,
    "zip_selected":  [],
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════════════════════════════
# ▶▶ FIX 4 — SIDEBAR with configurable workers slider
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""
    <div class="tb-brand">
      <span class="tb-brand-dot"></span> TrackBook
    </div>
    """, unsafe_allow_html=True)
    st.caption(f"Signed in as **{st.session_state.get('username','user')}**")

    dm_label = "☀️ Light mode" if dark_mode else "🌙 Dark mode"
    if st.button(dm_label, use_container_width=True):
        new_val = "0" if dark_mode else "1"
        st.query_params["dark"] = new_val
        st.rerun()

    if st.button("Sign out", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()

    st.divider()

    # ── FIX 4: Configurable batch workers ────────────────────────────────
    st.markdown('<div style="font-size:0.78rem;font-weight:600;color:var(--text3);margin-bottom:4px">⚙️ Batch processing</div>', unsafe_allow_html=True)
    BATCH_WORKERS = st.slider(
        "Parallel workers",
        min_value=1, max_value=6, value=3,
        help="How many invoices to process simultaneously. Higher = faster but uses more API quota."
    )
    st.caption(f"Processing {BATCH_WORKERS} file(s) at a time")

    st.divider()

    with st.expander("🗂 Cache"):
        cache_files = list(_CACHE_DIR.glob("*.png"))
        st.caption(f"{len(cache_files)} cached items")
        if st.button("🧹 Clean cache", use_container_width=True):
            removed = clean_logo_cache()
            st.success(f"Removed {removed} expired items")

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
    m = {"high": ("green","✓ High"), "medium": ("amber","~ Medium"), "low": ("red","! Low")}
    kind, label = m.get(level, ("gray", level or "?"))
    return _badge(label, kind)

def risk_badge(level: str) -> str:
    m = {"low": ("green","▲ Low risk"), "medium": ("amber","▲ Medium risk"), "high": ("red","▲ High risk")}
    kind, label = m.get(level, ("gray", level or "?"))
    return _badge(label, kind)

def field_card(label: str, value, score: str = None) -> str:
    v_html = (f'<div class="tb-field-value">{value}</div>'
              if (value is not None and value != "")
              else '<div class="tb-field-null">—</div>')
    conf_dot = bar_html = ""
    if score:
        colours = {"high": "#16a34a", "medium": "#d97706", "low": "#dc2626"}
        col = colours.get(score, "#D1D5DB")
        conf_dot = f'<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:{col};margin-left:4px"></span>'
        bar_html = f'<div class="tb-conf-bar tb-conf-bar-{score}"></div>'
    return (f'<div class="tb-field">'
            f'<div class="tb-field-label">{label}{conf_dot}</div>'
            f'{v_html}{bar_html}</div>')

# ══════════════════════════════════════════════════════════════════════════════
# ▶▶ FIX 3 — LOGO EXTRACTION with status feedback
# ══════════════════════════════════════════════════════════════════════════════
def extract_logo(file_bytes: bytes, media_type: str) -> tuple[bytes | None, str]:
    """
    Returns (logo_bytes_or_None, status_message)
    Status can be: 'cached', 'extracted', 'no_logo', 'error'
    FIX 3: Now returns a status so callers can show informative feedback.
    """
    h = _file_hash(file_bytes)
    cached = _load_logo_from_cache(h)
    if cached is not None:
        return cached, "cached"

    import base64 as _b64
    import anthropic

    working_bytes = file_bytes
    working_mt    = media_type

    if media_type == "application/pdf":
        try:
            from pdf2image import convert_from_bytes
            pages = convert_from_bytes(file_bytes, first_page=1, last_page=1, dpi=150)
            if not pages:
                return None, "error"
            buf = io.BytesIO()
            pages[0].save(buf, format="PNG")
            working_bytes = buf.getvalue()
            working_mt    = "image/png"
        except Exception as e:
            return None, f"error: pdf2image failed — {e}"

    def _call():
        client = anthropic.Anthropic()
        b64 = _b64.standard_b64encode(working_bytes).decode()
        return client.messages.create(
            model="claude-opus-4-5",
            max_tokens=256,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": working_mt, "data": b64}},
                {"type": "text", "text": (
                    'Does this invoice have a vendor/company logo? Reply ONLY with valid JSON:\n'
                    '{"has_logo":true,"x1_pct":5,"y1_pct":2,"x2_pct":28,"y2_pct":18}\n'
                    'No logo: {"has_logo":false}'
                )}
            ]}]
        )
    try:
        resp = _wrap_api_call(_call)
        raw  = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        info = json.loads(raw)
        if not info.get("has_logo"):
            return None, "no_logo"
        from PIL import Image
        img = Image.open(io.BytesIO(working_bytes)).convert("RGBA")
        w, h_img = img.size
        pad = 10
        x1 = max(0, int(info["x1_pct"] / 100 * w)     - pad)
        y1 = max(0, int(info["y1_pct"] / 100 * h_img)  - pad)
        x2 = min(w,     int(info["x2_pct"] / 100 * w)  + pad)
        y2 = min(h_img, int(info["y2_pct"] / 100 * h_img) + pad)
        if x2 > x1 and y2 > y1:
            logo = img.crop((x1, y1, x2, y2))
            buf  = io.BytesIO()
            logo.save(buf, format="PNG")
            logo_bytes = buf.getvalue()
            _save_logo_to_cache(h, logo_bytes)
            return logo_bytes, "extracted"
        return None, "no_logo"
    except ClaudeAPIError as e:
        return None, f"error: {e.error_type} — {e}"
    except Exception as e:
        return None, f"error: {e}"

def render_logo_header(vendor_name: str, logo_bytes: bytes | None):
    initials = "".join(w[0].upper() for w in (vendor_name or "??").split()[:2])
    if logo_bytes:
        c1, c2 = st.columns([1, 8])
        with c1: st.image(logo_bytes, width=52)
        with c2: st.markdown(f'<div class="tb-vendor-name" style="padding-top:14px">{vendor_name or "—"}</div>', unsafe_allow_html=True)
    else:
        st.markdown(
            f'<div class="tb-logo-row">'
            f'<div class="tb-monogram">{initials}</div>'
            f'<div><div class="tb-vendor-name">{vendor_name or "—"}</div>'
            f'<div class="tb-vendor-sub">Vendor</div></div></div>',
            unsafe_allow_html=True)

# ── Canadian Tax ──────────────────────────────────────────────────────────────
_CA_TAX = {
    "AB":(5.0,0.0,0.0,"GST only"), "BC":(5.0,7.0,0.0,"GST+PST"),
    "MB":(5.0,7.0,0.0,"GST+RST"), "NB":(0.0,0.0,15.0,"HST"),
    "NL":(0.0,0.0,15.0,"HST"),    "NS":(0.0,0.0,15.0,"HST"),
    "NT":(5.0,0.0,0.0,"GST only"),"NU":(5.0,0.0,0.0,"GST only"),
    "ON":(0.0,0.0,13.0,"HST"),    "PE":(0.0,0.0,15.0,"HST"),
    "QC":(5.0,9.975,0.0,"GST+QST"),"SK":(5.0,6.0,0.0,"GST+PST"),
    "YT":(5.0,0.0,0.0,"GST only"),
}
_CA_NAMES = {
    "AB":"Alberta","BC":"British Columbia","MB":"Manitoba",
    "NB":"New Brunswick","NL":"Newfoundland","NS":"Nova Scotia",
    "NT":"NW Territories","NU":"Nunavut","ON":"Ontario",
    "PE":"PEI","QC":"Québec","SK":"Saskatchewan","YT":"Yukon",
}

def _detect_province(text: str) -> str | None:
    if not text: return None
    u = text.upper()
    for code in _CA_TAX:
        if re.search(r'\b' + code + r'\b', u): return code
    for code, name in _CA_NAMES.items():
        if name.upper() in u: return code
    return None

def canadian_tax_flags(data: dict) -> list[str]:
    flags = []
    v_addr   = (data.get("vendor", {}).get("address") or "")
    b_addr   = (data.get("buyer",  {}).get("address") or "")
    currency = (data.get("invoice_meta", {}).get("currency") or "").upper()
    is_ca = (currency == "CAD" or "CANADA" in v_addr.upper() or "CANADA" in b_addr.upper()
             or _detect_province(v_addr) or _detect_province(b_addr))
    if not is_ca: return flags
    subtotal  = float(data.get("totals", {}).get("subtotal")  or 0)
    tax_total = float(data.get("totals", {}).get("tax_total") or 0)
    province  = _detect_province(v_addr) or _detect_province(b_addr)
    if subtotal > 0 and tax_total > 0:
        eff = tax_total / subtotal * 100
        if province:
            gst, pst, hst, label = _CA_TAX[province]
            expected = hst if hst else (gst + pst)
            if abs(eff - expected) > 0.6:
                flags.append(f"🇨🇦 {_CA_NAMES[province]}: expected {expected:.1f}% ({label}), got {eff:.1f}%")
        elif eff > 15.0:
            flags.append(f"🇨🇦 Tax rate {eff:.1f}% exceeds max Canadian HST (15%)")
    tax_id = (data.get("vendor", {}).get("tax_id") or "")
    if tax_id and currency == "CAD":
        digits = re.sub(r"\D", "", tax_id)
        if len(digits) not in (9, 15):
            flags.append(f"🇨🇦 Vendor tax ID '{tax_id}' doesn't match Canadian BN format")
    return flags

def enhanced_fraud_flags(data: dict) -> list[str]:
    flags = []
    m = data.get("invoice_meta", {})
    t = data.get("totals", {})
    items = data.get("line_items", [])
    try:
        inv_d = m.get("invoice_date"); due_d = m.get("due_date")
        if inv_d and due_d and due_d < inv_d:
            flags.append(f"Due date ({due_d}) is before invoice date ({inv_d})")
    except Exception: pass
    amounts = [float(i.get("amount") or 0) for i in items if i.get("amount")]
    if len(amounts) >= 2 and all(a % 100 == 0 for a in amounts):
        flags.append("All line item amounts are round multiples of 100")
    if amounts:
        grand = float(t.get("grand_total") or 0)
        if grand > 0 and abs(sum(amounts) - grand) > 1.0:
            flags.append(f"Line items sum ({sum(amounts):,.2f}) ≠ grand total ({grand:,.2f})")
    if not m.get("invoice_number"):
        flags.append("Invoice number is missing")
    for item in items:
        qty = float(item.get("quantity") or 0)
        if qty > 9999:
            flags.append(f"Unusually high quantity ({qty}) for: {item.get('description','?')}")
    return flags

# ══════════════════════════════════════════════════════════════════════════════
# ▶▶ FIX 1 — UNIFIED RISK LEVEL COMPUTATION
# This single function is now the ONE place that decides the final risk level.
# It's used both when saving (so DB gets the upgraded level) and when displaying.
# ══════════════════════════════════════════════════════════════════════════════
def compute_final_risk_level(data: dict) -> str:
    """
    Combines Claude's risk level with rule-based flags to produce
    the final, authoritative risk level. This is now used everywhere —
    at save-time (written to DB) and at display-time — so they always match.
    """
    fraud = data.get("fraud_flags") or {}
    claude_risk = fraud.get("risk_level", "low")

    extra_flags = enhanced_fraud_flags(data) + canadian_tax_flags(data)

    # Upgrade logic: rules can only raise the risk, never lower it
    risk_order = {"low": 0, "medium": 1, "high": 2}
    final_risk = claude_risk

    if extra_flags:
        # Any rule flags at all → at least medium
        if risk_order.get(final_risk, 0) < risk_order["medium"]:
            final_risk = "medium"
        # 3 or more rule flags → high
        if len(extra_flags) >= 3 and risk_order.get(final_risk, 0) < risk_order["high"]:
            final_risk = "high"

    return final_risk

def is_valid_invoice(data: dict) -> tuple[bool, str]:
    doc_type = data.get("document_type", "invoice")
    if doc_type not in ("invoice", "receipt", "credit_note", "bill"):
        return False, f"Document type is '{doc_type}' — expected invoice, receipt or bill."
    conf = data.get("confidence", {}).get("overall", "low")
    m = data.get("invoice_meta", {}); v = data.get("vendor", {}); t = data.get("totals", {})
    null_critical = sum([m.get("invoice_number") is None, m.get("invoice_date") is None,
                         v.get("name") is None, t.get("grand_total") is None])
    if null_critical == 4:
        return False, "No invoice fields found."
    if null_critical >= 3 and conf == "low":
        return False, f"{null_critical}/4 key fields missing with low confidence."
    return True, ""

def render_fraud_section(data: dict):
    """
    FIX 1: Now takes the full data dict and calls compute_final_risk_level()
    so display always uses the same logic as what's saved to DB.
    """
    fraud = data.get("fraud_flags") or {}
    flags = list(fraud.get("flags", []))
    extra_flags = enhanced_fraud_flags(data) + canadian_tax_flags(data)
    all_flags = flags + extra_flags

    # Use the unified function — same as what gets saved to DB
    final_risk = compute_final_risk_level(data)

    math = fraud.get("math_check", {})

    if fraud.get("is_suspicious") or final_risk in ("medium", "high") or all_flags:
        items_html = "".join(f'<div class="tb-fraud-item">• {f}</div>' for f in all_flags) or \
                     '<div class="tb-fraud-item">Flagged as suspicious</div>'
        st.markdown(
            f'<div class="tb-fraud-box">'
            f'<div class="tb-fraud-title">🚨 Fraud analysis — {risk_badge(final_risk)}</div>'
            f'{items_html}</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown('<div class="tb-ok-box">✓ No fraud indicators detected</div>', unsafe_allow_html=True)

    if math and not math.get("matches", True):
        e, a = math.get("expected_total"), math.get("actual_total")
        if e and a:
            st.warning(f"⚠️ Math check: expected {e}, invoice shows {a}")

def render_field_scores(scores: dict, data: dict):
    m = data.get("invoice_meta", {}); v = data.get("vendor", {}); b = data.get("buyer", {})
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown('<div class="tb-section-head">Invoice details</div>', unsafe_allow_html=True)
        for label, key, sk in [
            ("Invoice #","invoice_number","invoice_number"),("PO #","po_number",None),
            ("Invoice date","invoice_date","invoice_date"),("Due date","due_date","due_date"),
            ("Terms","terms",None),("Currency","currency",None),
        ]:
            st.markdown(field_card(label, m.get(key), scores.get(sk) if sk else None), unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="tb-section-head">Vendor</div>', unsafe_allow_html=True)
        for label, key, sk in [
            ("Name","name","vendor_name"),("Address","address",None),
            ("Email","email",None),("Phone","phone",None),("Tax ID","tax_id","vendor_tax_id"),
        ]:
            st.markdown(field_card(label, v.get(key), scores.get(sk) if sk else None), unsafe_allow_html=True)
    with c3:
        st.markdown('<div class="tb-section-head">Bill to</div>', unsafe_allow_html=True)
        st.markdown(field_card("Name", b.get("name")), unsafe_allow_html=True)
        st.markdown(field_card("Address", b.get("address")), unsafe_allow_html=True)

def render_invoice(data: dict, invoice_id: int = None, editable: bool = False,
                   logo_bytes: bytes | None = None, key_prefix: str = "") -> dict:
    m = data.get("invoice_meta",{}); v = data.get("vendor",{}); b = data.get("buyer",{})
    t = data.get("totals",{}); conf = data.get("confidence",{}); fraud = data.get("fraud_flags",{})
    cur = m.get("currency") or ""
    scores = conf.get("field_scores", {})

    render_logo_header(v.get("name"), logo_bytes)

    # FIX 1: Use unified risk level for display header too
    final_risk = compute_final_risk_level(data)

    h1,h2,h3,h4 = st.columns(4)
    h1.markdown(f"**Confidence** {conf_badge(conf.get('overall','low'))}", unsafe_allow_html=True)
    h2.markdown(f"**Type** `{data.get('document_type','invoice')}`")
    h3.markdown(f"**Fraud** {risk_badge(final_risk)}", unsafe_allow_html=True)
    if invoice_id: h4.markdown(_badge(f"✓ Saved #{invoice_id}", "blue"), unsafe_allow_html=True)

    flagged = conf.get("flagged_fields", [])
    if flagged: st.warning(f"Flagged: {', '.join(flagged)}")

    st.divider()
    render_fraud_section(data)   # FIX 1: pass full data, not just fraud sub-dict

    if editable:
        st.markdown("**✏️ Edit fields before saving**")
        ec1,ec2 = st.columns(2)
        with ec1:
            v["name"]           = st.text_input("Vendor name",      v.get("name") or "",        key=f"{key_prefix}_vname")
            v["tax_id"]         = st.text_input("Vendor tax ID",    v.get("tax_id") or "",      key=f"{key_prefix}_vtaxid")
            m["invoice_number"] = st.text_input("Invoice #",        m.get("invoice_number") or "", key=f"{key_prefix}_invnum")
            m["invoice_date"]   = st.text_input("Invoice date",     m.get("invoice_date") or "", key=f"{key_prefix}_invdate")
            m["due_date"]       = st.text_input("Due date",         m.get("due_date") or "",    key=f"{key_prefix}_duedate")
        with ec2:
            b["name"]      = st.text_input("Buyer name", b.get("name") or "",   key=f"{key_prefix}_bname")
            m["currency"]  = st.text_input("Currency",   m.get("currency") or "", key=f"{key_prefix}_currency")
            raw_total      = st.text_input("Grand total", str(t.get("grand_total") or ""), key=f"{key_prefix}_grandtotal")
            try: t["grand_total"] = float(raw_total) if raw_total else None
            except ValueError: pass
            m["terms"] = st.text_input("Terms", m.get("terms") or "", key=f"{key_prefix}_terms")
        data["vendor"]=v; data["buyer"]=b; data["invoice_meta"]=m; data["totals"]=t
        st.divider()
    else:
        render_field_scores(scores, data)

    st.divider()
    st.markdown('<div class="tb-section-head">Line items</div>', unsafe_allow_html=True)
    items = data.get("line_items", [])
    if items:
        st.dataframe(items, use_container_width=True, hide_index=True,
            column_config={
                "description": st.column_config.TextColumn("Description", width="large"),
                "quantity":    st.column_config.NumberColumn("Qty"),
                "unit_price":  st.column_config.NumberColumn("Unit price", format=f"{cur} %.2f"),
                "tax":         st.column_config.NumberColumn("Tax"),
                "amount":      st.column_config.NumberColumn("Amount", format=f"{cur} %.2f"),
            })

    st.divider()
    st.markdown('<div class="tb-section-head">Totals</div>', unsafe_allow_html=True)
    tc1,tc2,tc3,tc4 = st.columns(4)
    for col,label,key in [(tc1,"Subtotal","subtotal"),(tc2,"Discount","discount"),
                           (tc3,"Tax","tax_total"),(tc4,"Grand total","grand_total")]:
        amt = t.get(key)
        col.metric(label, f"{cur} {amt:,.2f}" if amt is not None else "—")

    if data.get("notes"):
        st.divider(); st.info(data["notes"])

    st.divider()
    with st.expander("View raw JSON"):
        st.json(data)
    st.download_button("⬇ Download JSON", data=json.dumps(data, indent=2),
        file_name=f"invoice_{invoice_id or 'extracted'}.json", mime="application/json",
        key=f"dl_{invoice_id or 'new'}_{id(data)}")
    return data

# ══════════════════════════════════════════════════════════════════════════════
# BATCH ZIP EXPORT
# ══════════════════════════════════════════════════════════════════════════════
def build_zip_export(invoice_ids: list[int]) -> bytes:
    buf = io.BytesIO()
    rows_for_csv = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for iid in invoice_ids:
            record = get_invoice_by_id(iid)
            if not record: continue
            raw = record.get("raw_json")
            data = raw if isinstance(raw, dict) else json.loads(raw)
            fname = f"invoice_{iid}_{data.get('vendor',{}).get('name','unknown')}.json"
            fname = re.sub(r'[^A-Za-z0-9_\-.]', '_', fname)
            zf.writestr(fname, json.dumps(data, indent=2))
            m = data.get("invoice_meta",{}); v = data.get("vendor",{}); t = data.get("totals",{})
            rows_for_csv.append({
                "id": iid, "invoice_number": m.get("invoice_number",""),
                "vendor": v.get("name",""), "date": m.get("invoice_date",""),
                "total": t.get("grand_total",""), "currency": m.get("currency",""),
            })
        if rows_for_csv:
            out = io.StringIO()
            w = csv.DictWriter(out, fieldnames=rows_for_csv[0].keys())
            w.writeheader(); w.writerows(rows_for_csv)
            zf.writestr("summary.csv", out.getvalue())
    return buf.getvalue()

# ══════════════════════════════════════════════════════════════════════════════
# ▶▶ FIX 1 + FIX 2 + FIX 3 — BATCH PROCESSOR
# ══════════════════════════════════════════════════════════════════════════════
def _process_single(uploaded_file, do_logo: bool, do_save: bool,
                    tracker: ProgressTracker | None = None) -> dict:
    name = uploaded_file.name
    result = {"name": name, "status": "error", "data": None,
              "logo_bytes": None, "logo_status": None, "invoice_id": None,
              "error": None, "dup": None, "rejected": None, "thumb": None}

    suffix = os.path.splitext(name)[1].lower()
    file_bytes = uploaded_file.getvalue()

    if tracker: tracker.update(name, 10, "processing", "Reading file…")

    if suffix == ".pdf":
        result["thumb"] = get_pdf_thumbnail(file_bytes)

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes); tmp_path = tmp.name

        if tracker: tracker.update(name, 30, "processing", "Extracting…")

        # ── FIX 2: Clean error handling — no silent re-call fallback ──────
        try:
            data = _wrap_api_call(extract_invoice, tmp_path)
        except ClaudeAPIError as e:
            # Show exactly what went wrong; don't silently retry with same call
            error_messages = {
                "rate_limit": "API rate limit reached — please wait a moment and try again.",
                "timeout":    "Request timed out — the invoice may be too complex or the API is busy.",
                "connection": "Could not connect to Claude API — check your internet connection.",
                "api_error":  "Claude API returned an error — check your API key and quota.",
            }
            friendly = error_messages.get(e.error_type, f"API error: {e}")
            result["error"] = friendly
            os.unlink(tmp_path)
            if tracker: tracker.update(name, 100, "error")
            return result
        except Exception as e:
            result["error"] = f"Extraction failed: {e}"
            os.unlink(tmp_path)
            if tracker: tracker.update(name, 100, "error")
            return result
        finally:
            try: os.unlink(tmp_path)
            except Exception: pass

    except Exception as e:
        result["error"] = str(e)
        if tracker: tracker.update(name, 100, "error")
        return result

    if tracker: tracker.update(name, 55, "processing", "Validating…")
    valid, reason = is_valid_invoice(data)
    if not valid:
        result["status"] = "rejected"; result["rejected"] = reason
        if tracker: tracker.update(name, 100, "error")
        return result

    inv_num = data.get("invoice_meta", {}).get("invoice_number")
    dup = check_duplicate(inv_num) if inv_num else None
    result["dup"] = dup

    # ── FIX 3: Logo extraction with status feedback ───────────────────────
    if do_logo:
        if tracker: tracker.update(name, 70, "processing", "Logo…")
        mt_map = {".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",
                  ".webp":"image/webp",".pdf":"application/pdf"}
        media_type = mt_map.get(suffix, "image/png")
        try:
            logo_bytes, logo_status = extract_logo(file_bytes, media_type)
            result["logo_bytes"]  = logo_bytes
            result["logo_status"] = logo_status
        except Exception as e:
            result["logo_status"] = f"error: {e}"

    result["data"] = data

    # ── FIX 1: Compute unified risk level BEFORE saving to DB ────────────
    final_risk = compute_final_risk_level(data)
    # Write it back into the data dict so save_invoice() picks it up
    if "fraud_flags" not in data or data["fraud_flags"] is None:
        data["fraud_flags"] = {}
    data["fraud_flags"]["risk_level"] = final_risk

    result["status"] = "extracted"

    if do_save and not dup:
        if tracker: tracker.update(name, 88, "processing", "Saving…")
        try:
            iid = save_invoice(data)    # now saves the upgraded risk_level
            result["invoice_id"] = iid
            result["status"] = "saved"
        except Exception as e:
            result["error"] = f"Save failed: {e}"

    if tracker: tracker.update(name, 100, "completed")
    return result


def render_batch_results(results: list[dict], edit_mode: bool):
    for r in results:
        icon = {"saved":"✅","extracted":"📄","rejected":"🚫","error":"❌"}.get(r["status"],"❓")
        with st.expander(f"{icon} {r['name']}", expanded=(r["status"] not in ("saved",))):
            if r.get("thumb"):
                st.image(r["thumb"], width=120, caption="Page 1 preview")

            if r["status"] == "rejected":
                st.error(f"Rejected: {r['rejected']}"); continue
            if r["status"] == "error":
                st.error(f"Error: {r['error']}"); continue

            data = r["data"]

            # ── FIX 3: Show logo extraction status ────────────────────────
            logo_status = r.get("logo_status")
            if logo_status == "extracted":
                st.success("🖼 Logo extracted successfully")
            elif logo_status == "cached":
                st.info("🖼 Logo loaded from cache")
            elif logo_status == "no_logo":
                st.caption("🖼 No logo detected in this document")
            elif logo_status and logo_status.startswith("error"):
                st.warning(f"🖼 Logo extraction skipped: {logo_status}")

            if r["dup"]:
                dup = r["dup"]
                st.markdown(
                    f'<div class="tb-dup-box">⚠️ <b>Duplicate:</b> Invoice already exists as '
                    f'DB #{dup["id"]} — {dup["vendor_name"]}, total {dup["grand_total"]}</div>',
                    unsafe_allow_html=True)
                if st.button("Save anyway", key=f"force_{r['name']}", type="secondary") and db_ok:
                    try:
                        iid = save_invoice(data); r["invoice_id"] = iid
                        st.success(f"✓ Force-saved as #{iid}")
                    except Exception as e:
                        st.warning(str(e))

            if r["logo_bytes"]:
                import base64 as _b64
                data["_logo_b64"] = _b64.b64encode(r["logo_bytes"]).decode()

            if edit_mode:
                data = render_invoice(data, editable=True, logo_bytes=r["logo_bytes"], key_prefix=r["name"])
                if st.button(f"💾 Confirm & Save", key=f"esave_{r['name']}") and db_ok:
                    try:
                        iid = save_invoice(data); st.success(f"✓ Saved #{iid}")
                    except Exception as e:
                        st.warning(str(e))
            else:
                render_invoice(data, invoice_id=r.get("invoice_id"), logo_bytes=r["logo_bytes"])
                if r.get("invoice_id"):
                    st.success(f"✓ Saved to DB as #{r['invoice_id']}")

# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
if not db_ok:
    st.error(f"⚠️ Database not connected: {db_error}")

tab_extract, tab_scan, tab_history, tab_summary = st.tabs(
    ["📤 Extract", "📷 Scan Receipt", "📋 History", "📊 Spend Summary"]
)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — EXTRACT
# ══════════════════════════════════════════════════════════════════════════════
with tab_extract:
    st.markdown("""
    <div style="margin-bottom:1.25rem">
      <div class="tb-page-title">Extract invoices</div>
      <div class="tb-page-sub">Upload any number of invoices — processed in parallel with fraud &amp; tax analysis.</div>
    </div>
    """, unsafe_allow_html=True)

    oc1, oc2, _ = st.columns([2, 2, 4])
    with oc1:
        em_bg  = "#EEF2FF" if st.session_state.edit_mode else "#F9FAFB"
        em_col = "#1A56E8" if st.session_state.edit_mode else "#6B7280"
        em_bd  = "#C7D2FE" if st.session_state.edit_mode else "#E5E7EB"
        st.markdown(f'<div style="background:{em_bg};border:1px solid {em_bd};border-radius:8px;padding:8px 14px;font-size:0.82rem;font-weight:600;color:{em_col};margin-bottom:4px">{"✏️ Edit mode: ON" if st.session_state.edit_mode else "✏️ Edit mode: OFF"}</div>', unsafe_allow_html=True)
        if st.button("Toggle edit mode", key="toggle_edit", use_container_width=True):
            st.session_state.edit_mode = not st.session_state.edit_mode; st.rerun()
    with oc2:
        as_bg  = "#DCFCE7" if st.session_state.auto_save else "#F9FAFB"
        as_col = "#15803D" if st.session_state.auto_save else "#6B7280"
        as_bd  = "#BBF7D0" if st.session_state.auto_save else "#E5E7EB"
        st.markdown(f'<div style="background:{as_bg};border:1px solid {as_bd};border-radius:8px;padding:8px 14px;font-size:0.82rem;font-weight:600;color:{as_col};margin-bottom:4px">{"💾 Auto-save: ON" if st.session_state.auto_save else "💾 Auto-save: OFF"}</div>', unsafe_allow_html=True)
        if st.button("Toggle auto-save", key="toggle_save", use_container_width=True):
            st.session_state.auto_save = not st.session_state.auto_save; st.rerun()

    uploaded_files = st.file_uploader(
        "Upload invoices", type=["pdf","png","jpg","jpeg","webp"],
        accept_multiple_files=True, label_visibility="collapsed",
    )

    if uploaded_files:
        n = len(uploaded_files)
        workers = min(BATCH_WORKERS, n)
        est = max(1, n // workers) * 12

        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;margin:0.75rem 0">'
            f'{_badge(f"{n} file(s) selected", "blue")}'
            f'<span style="font-size:0.78rem;color:var(--text3)">{workers} parallel workers · ~{est}s estimated</span>'
            f'</div>', unsafe_allow_html=True)

        if st.button("⚡ Process all", type="primary"):
            tracker = ProgressTracker([f.name for f in uploaded_files])
            dash_slot = st.empty()

            progress_bar = st.progress(0, text="Starting batch…")
            completed_count = 0
            all_results = []

            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_file = {
                    executor.submit(
                        _process_single, f, True,
                        st.session_state.auto_save and not st.session_state.edit_mode,
                        tracker
                    ): f
                    for f in uploaded_files
                }
                for future in as_completed(future_to_file):
                    f = future_to_file[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        result = {"name": f.name, "status": "error", "error": str(e),
                                  "data": None, "logo_bytes": None, "logo_status": None,
                                  "invoice_id": None, "dup": None, "rejected": None, "thumb": None}
                    all_results.append(result)
                    completed_count += 1
                    dash_slot.markdown(tracker.render_html(), unsafe_allow_html=True)
                    progress_bar.progress(completed_count / n, text=f"{completed_count}/{n} processed…")

            progress_bar.progress(1.0, text="Done!")
            dash_slot.markdown(tracker.render_html(), unsafe_allow_html=True)

            saved    = sum(1 for r in all_results if r["status"] == "saved")
            errors   = sum(1 for r in all_results if r["status"] == "error")
            rejected = sum(1 for r in all_results if r["status"] == "rejected")
            dups     = sum(1 for r in all_results if r.get("dup"))

            st.markdown(
                f'<div style="display:flex;gap:0.75rem;margin:1rem 0;flex-wrap:wrap">'
                f'{_badge(f"✓ {saved} saved","green")}'
                f'{_badge(f"⚠ {dups} duplicates","amber") if dups else ""}'
                f'{_badge(f"✗ {rejected} rejected","red") if rejected else ""}'
                f'{_badge(f"✗ {errors} errors","red") if errors else ""}'
                f'</div>', unsafe_allow_html=True)

            saved_ids = [r["invoice_id"] for r in all_results if r.get("invoice_id")]
            if saved_ids:
                zip_bytes = build_zip_export(saved_ids)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button(
                    f"⬇ Download batch ZIP ({len(saved_ids)} invoices)",
                    data=zip_bytes,
                    file_name=f"trackbook_batch_{ts}.zip",
                    mime="application/zip",
                    key=f"batch_zip_{ts}",
                )

            st.divider()
            render_batch_results(all_results, st.session_state.edit_mode)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — SCAN RECEIPT
# ══════════════════════════════════════════════════════════════════════════════
with tab_scan:
    st.markdown("""
    <div style="margin-bottom:1.25rem">
      <div class="tb-page-title">Scan a receipt</div>
      <div class="tb-page-sub">Point your camera at any receipt — Claude reads it live.</div>
    </div>
    """, unsafe_allow_html=True)

    sc1, sc2 = st.columns([1, 1])
    with sc1:
        camera_image = st.camera_input("Take a photo", help="Works on mobile and desktop webcam.")
    with sc2:
        st.markdown("""
        **Tips for best results**
        - Good lighting, no shadows across text
        - Keep the whole document in frame
        - Avoid glare on glossy receipts
        """)
        if camera_image:
            se_bg  = "#EEF2FF" if st.session_state.scan_edit else "#F9FAFB"
            se_col = "#1A56E8" if st.session_state.scan_edit else "#6B7280"
            se_bd  = "#C7D2FE" if st.session_state.scan_edit else "#E5E7EB"
            st.markdown(f'<div style="background:{se_bg};border:1px solid {se_bd};border-radius:8px;padding:7px 12px;font-size:0.82rem;font-weight:600;color:{se_col};margin-bottom:4px">{"✏️ Edit mode: ON" if st.session_state.scan_edit else "✏️ Edit mode: OFF"}</div>', unsafe_allow_html=True)
            if st.button("Toggle edit", key="scan_edit_btn", use_container_width=True):
                st.session_state.scan_edit = not st.session_state.scan_edit; st.rerun()
            ss_bg  = "#DCFCE7" if st.session_state.scan_save else "#F9FAFB"
            ss_col = "#15803D" if st.session_state.scan_save else "#6B7280"
            ss_bd  = "#BBF7D0" if st.session_state.scan_save else "#E5E7EB"
            st.markdown(f'<div style="background:{ss_bg};border:1px solid {ss_bd};border-radius:8px;padding:7px 12px;font-size:0.82rem;font-weight:600;color:{ss_col};margin-bottom:4px">{"💾 Auto-save: ON" if st.session_state.scan_save else "💾 Auto-save: OFF"}</div>', unsafe_allow_html=True)
            if st.button("Toggle save", key="scan_save_btn", use_container_width=True):
                st.session_state.scan_save = not st.session_state.scan_save; st.rerun()
            do_extract = st.button("⚡ Extract from photo", type="primary", key="scan_btn")

    if camera_image and do_extract:
        with st.spinner("Reading receipt…"):
            file_bytes = camera_image.getvalue()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                tmp.write(file_bytes); tmp_path = tmp.name
            try:
                data = _wrap_api_call(extract_invoice, tmp_path)

            # ── FIX 2: Scan tab also gets clean error messages ────────────
            except ClaudeAPIError as e:
                error_messages = {
                    "rate_limit": "Rate limit reached — please wait a moment and try again.",
                    "timeout":    "Request timed out — try again with better lighting.",
                    "connection": "Cannot connect to Claude API — check your internet.",
                    "api_error":  "API error — check your key and quota.",
                }
                st.error(f"❌ {error_messages.get(e.error_type, str(e))}")
                data = None
            except Exception as e:
                st.error(f"Extraction failed: {e}")
                data = None
            finally:
                try: os.unlink(tmp_path)
                except Exception: pass

        if data:
            valid, reason = is_valid_invoice(data)
            if not valid:
                st.error(f"❌ Rejected: {reason}")
            else:
                # FIX 1: Apply unified risk level before saving
                final_risk = compute_final_risk_level(data)
                if "fraud_flags" not in data or data["fraud_flags"] is None:
                    data["fraud_flags"] = {}
                data["fraud_flags"]["risk_level"] = final_risk

                st.divider()
                if st.session_state.scan_edit:
                    data = render_invoice(data, editable=True, key_prefix="scan")
                    if st.button("💾 Confirm & Save scan", key="scan_confirm"):
                        if db_ok and st.session_state.scan_save:
                            try:
                                iid = save_invoice(data); st.success(f"✓ Saved — DB ID #{iid}")
                            except Exception as e:
                                st.warning(f"Save failed: {e}")
                else:
                    data = render_invoice(data)
                    if db_ok and st.session_state.scan_save:
                        try:
                            iid = save_invoice(data); st.success(f"✓ Saved — DB ID #{iid}")
                        except Exception as e:
                            st.warning(f"Save failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — HISTORY (unchanged)
# ══════════════════════════════════════════════════════════════════════════════
with tab_history:
    st.markdown('<div class="tb-page-title">Invoice history</div>', unsafe_allow_html=True)

    if not db_ok:
        st.error("Database not connected."); st.stop()

    with st.expander("🔍 Filter invoices", expanded=True):
        fc1,fc2,fc3 = st.columns(3)
        with fc1:
            f_vendor = st.text_input("Vendor name contains")
            f_conf   = st.selectbox("Confidence", ["","high","medium","low"])
        with fc2:
            f_date_from = st.date_input("Date from", value=None)
            f_date_to   = st.date_input("Date to",   value=None)
        with fc3:
            f_min  = st.number_input("Min amount", value=0.0, step=100.0)
            f_max  = st.number_input("Max amount", value=0.0, step=100.0)
            f_risk = st.selectbox("Fraud risk", ["","low","medium","high"])

    col_refresh, col_export = st.columns([1,1])
    with col_refresh:
        if st.button("🔄 Refresh"): st.rerun()

    try:
        rows = get_all_invoices(
            vendor=f_vendor,
            date_from=str(f_date_from) if f_date_from else "",
            date_to=str(f_date_to) if f_date_to else "",
            min_amount=f_min if f_min > 0 else None,
            max_amount=f_max if f_max > 0 else None,
            confidence=f_conf, risk=f_risk,
        )
    except Exception as e:
        st.error(f"Could not load history: {e}"); st.stop()

    with col_export:
        if rows:
            export_rows = get_all_invoices_for_export()
            if export_rows:
                out = io.StringIO()
                writer = csv.DictWriter(out, fieldnames=export_rows[0].keys())
                writer.writeheader()
                writer.writerows([{k: str(v) if v is not None else "" for k,v in r.items()} for r in export_rows])
                st.download_button("⬇ Export CSV", data=out.getvalue(),
                    file_name="trackbook_export.csv", mime="text/csv")

    if not rows:
        st.info("No invoices found.")
    else:
        st.caption(f"{len(rows)} invoice(s)")

        all_ids = [r["id"] for r in rows]
        col_sel1, col_sel2, col_zip = st.columns([1,1,2])
        with col_sel1:
            if st.button("Select all", key="sel_all"):
                st.session_state.zip_selected = all_ids; st.rerun()
        with col_sel2:
            if st.button("Deselect all", key="desel_all"):
                st.session_state.zip_selected = []; st.rerun()
        selected = st.multiselect(
            "Select invoices for ZIP export",
            options=all_ids,
            default=[x for x in st.session_state.zip_selected if x in all_ids],
            format_func=lambda i: next((f"#{i} — {r['vendor_name']}" for r in rows if r["id"]==i), str(i)),
            key="zip_ms",
        )
        st.session_state.zip_selected = selected
        with col_zip:
            if selected:
                zip_bytes = build_zip_export(selected)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button(
                    f"⬇ ZIP {len(selected)} invoice(s)",
                    data=zip_bytes, file_name=f"trackbook_{ts}.zip",
                    mime="application/zip", key=f"hist_zip_{ts}",
                )

        st.dataframe(rows, use_container_width=True, hide_index=True,
            column_config={
                "id":             st.column_config.NumberColumn("ID", width="small"),
                "created_at":     st.column_config.DatetimeColumn("Saved", format="DD MMM YYYY, HH:mm"),
                "invoice_number": st.column_config.TextColumn("Invoice #"),
                "vendor_name":    st.column_config.TextColumn("Vendor"),
                "buyer_name":     st.column_config.TextColumn("Buyer"),
                "invoice_date":   st.column_config.DateColumn("Date"),
                "due_date":       st.column_config.DateColumn("Due"),
                "currency":       st.column_config.TextColumn("Cur", width="small"),
                "grand_total":    st.column_config.NumberColumn("Total", format="%.2f"),
                "confidence":     st.column_config.TextColumn("Conf", width="small"),
                "risk_level":     st.column_config.TextColumn("Risk", width="small"),
                "document_type":  st.column_config.TextColumn("Type"),
            })

        st.divider()
        st.markdown("**View full invoice**")
        inv_id = st.number_input("Invoice ID", min_value=1, step=1, value=rows[0]["id"])
        if st.button("Load invoice"):
            record = get_invoice_by_id(int(inv_id))
            if record:
                raw = record.get("raw_json")
                display_data = raw if isinstance(raw, dict) else json.loads(raw)
                import base64 as _b64
                logo_b64   = display_data.get("_logo_b64")
                logo_bytes = _b64.b64decode(logo_b64) if logo_b64 else None
                vendor_name = display_data.get("vendor",{}).get("name") or ""
                if vendor_name:
                    st.markdown(
                        f'<div style="background:var(--primary-bg);border:1px solid var(--primary-bd);'
                        f'border-radius:8px;padding:8px 14px;font-size:0.82rem;color:var(--primary);margin-bottom:0.75rem">'
                        f'🏢 Vendor: <strong>{vendor_name}</strong></div>',
                        unsafe_allow_html=True)
                render_invoice(display_data, inv_id, logo_bytes=logo_bytes)
            else:
                st.error(f"No invoice found with ID {inv_id}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — SUMMARY (unchanged)
# ══════════════════════════════════════════════════════════════════════════════
with tab_summary:
    st.markdown('<div class="tb-page-title">Vendor spend summary</div>', unsafe_allow_html=True)

    if not db_ok:
        st.error("Database not connected."); st.stop()

    try:
        summary = get_vendor_summary()
    except Exception as e:
        st.error(f"Could not load summary: {e}"); st.stop()

    if not summary:
        st.info("No data yet — extract some invoices first.")
    else:
        import pandas as pd

        total_invoices = sum(r["invoice_count"] for r in summary)
        total_spend    = sum(float(r["total_spend"] or 0) for r in summary)
        top_vendor     = summary[0]["vendor_name"] if summary else "—"
        avg_invoice    = total_spend / total_invoices if total_invoices else 0

        st.markdown(f"""
        <div class="tb-metric-strip">
          <div class="tb-metric">
            <div class="tb-metric-label">Total invoices</div>
            <div class="tb-metric-value">{total_invoices}</div>
          </div>
          <div class="tb-metric">
            <div class="tb-metric-label">Total spend</div>
            <div class="tb-metric-value">{total_spend:,.0f}</div>
          </div>
          <div class="tb-metric">
            <div class="tb-metric-label">Top vendor</div>
            <div class="tb-metric-value" style="font-size:0.9rem">{top_vendor}</div>
          </div>
          <div class="tb-metric">
            <div class="tb-metric-label">Avg per invoice</div>
            <div class="tb-metric-value">{avg_invoice:,.0f}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        df = pd.DataFrame(summary)
        df["total_spend"] = df["total_spend"].astype(float)

        st.markdown('<div class="tb-section-head">Spend by vendor (top 15)</div>', unsafe_allow_html=True)
        chart_df = (df[["vendor_name","total_spend"]]
                    .set_index("vendor_name")
                    .sort_values("total_spend", ascending=False)
                    .head(15))
        st.bar_chart(chart_df, use_container_width=True, height=280)

        try:
            all_inv = get_all_invoices_for_export()
            if all_inv:
                risk_counts = {"low": 0, "medium": 0, "high": 0}
                for row in all_inv:
                    lvl = (row.get("risk_level") or "low").lower()
                    if lvl in risk_counts:
                        risk_counts[lvl] += 1

                total_risk = sum(risk_counts.values())
                if total_risk > 0:
                    st.markdown('<div class="tb-section-head">Fraud risk breakdown</div>', unsafe_allow_html=True)
                    rc1, rc2, rc3 = st.columns(3)
                    risk_cfg = [
                        (rc1, "low",    "✅ Low risk",    "#F0FDF4", "#BBF7D0", "#15803D"),
                        (rc2, "medium", "⚠️ Medium risk", "#FFFBEB", "#FDE68A", "#B45309"),
                        (rc3, "high",   "🚨 High risk",   "#FFF1F2", "#FECDD3", "#B91C1C"),
                    ]
                    for col, level, label, bg, bd, tc in risk_cfg:
                        cnt = risk_counts[level]
                        pct = round(cnt / total_risk * 100) if total_risk else 0
                        col.markdown(
                            f'<div style="background:{bg};border:1px solid {bd};border-radius:10px;'
                            f'padding:1rem;text-align:center">'
                            f'<div style="font-size:0.7rem;font-weight:600;text-transform:uppercase;'
                            f'letter-spacing:0.06em;color:{tc};margin-bottom:6px">{label}</div>'
                            f'<div style="font-size:2rem;font-weight:800;color:{tc}">{cnt}</div>'
                            f'<div style="font-size:0.75rem;color:{tc};opacity:0.75;margin-top:2px">{pct}% of invoices</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
        except Exception:
            pass

        st.divider()
        st.markdown('<div class="tb-section-head">Full breakdown</div>', unsafe_allow_html=True)
        st.dataframe(summary, use_container_width=True, hide_index=True,
            column_config={
                "vendor_name":     st.column_config.TextColumn("Vendor", width="large"),
                "invoice_count":   st.column_config.NumberColumn("# Invoices"),
                "total_spend":     st.column_config.NumberColumn("Total spend", format="%.2f"),
                "largest_invoice": st.column_config.NumberColumn("Largest", format="%.2f"),
                "first_invoice":   st.column_config.DateColumn("First"),
                "last_invoice":    st.column_config.DateColumn("Last"),
                "currency":        st.column_config.TextColumn("Cur", width="small"),
            })

# ══════════════════════════════════════════════════════════════════════════════
# VERSION FOOTER
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="tb-footer">
  <span>TrackBook v2.1 · NxtWave</span>
  <span>Invoice Intelligence Engine · Claude-powered</span>
  <span>© 2025</span>
</div>
""", unsafe_allow_html=True)
