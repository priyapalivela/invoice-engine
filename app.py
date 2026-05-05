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
import time
import tempfile
import threading
import queue
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
  /* ══ CSS CUSTOM PROPERTIES ══ */
  :root {
    --primary-color: #1A56E8 !important;
    --secondary-background-color: #FFFFFF !important;
    --text-color: #111827 !important;
  }
  * { --primary: #1A56E8 !important; }

  /* ── Google Font ── */
  @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;0,9..40,800&display=swap');

  /* ── Global ── */
  *, *::before, *::after { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  html, body, [class*="css"], .stApp, .main, section[data-testid="stSidebar"],
  [data-testid="stAppViewContainer"] {
    font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
  }
  [data-testid="stAppViewContainer"],
  .stApp { background: #F4F5F7 !important; }

  /* ── Kill Streamlit chrome ── */
  #MainMenu { visibility: hidden !important; }
  footer { visibility: hidden !important; }
  header { visibility: hidden !important; }
  [data-testid="stToolbar"] { display: none !important; }
  [data-testid="stDecoration"] { display: none !important; }
  [data-testid="stStatusWidget"] { display: none !important; }
  .viewerBadge_container__r5tak { display: none !important; }

  /* ── Sidebar ── */
  [data-testid="stSidebar"] {
    background: #FFFFFF !important;
    border-right: 1px solid #E5E7EB !important;
  }
  [data-testid="stSidebar"] > div { background: #FFFFFF !important; }
  [data-testid="stSidebar"] .stButton > button {
    background: #F9FAFB !important; color: #374151 !important;
    border: 1px solid #E5E7EB !important; border-radius: 8px !important;
    font-size: 0.82rem !important; width: 100% !important;
    padding: 6px 12px !important; font-weight: 500 !important;
    font-family: 'DM Sans', sans-serif !important;
  }
  [data-testid="stSidebar"] .stButton > button:hover {
    background: #EEF2FF !important; color: #1A56E8 !important;
    border-color: #C7D2FE !important;
  }

  /* ── Main content area ── */
  .block-container {
    padding: 1.5rem 2rem 3rem !important;
    max-width: 1300px !important;
  }

  /* ═══════════════════════════════════════════════
     FILE UPLOADER
  ═══════════════════════════════════════════════ */
  [data-testid="stFileUploader"] { background: transparent !important; }
  [data-testid="stFileUploader"] > div,
  [data-testid="stFileUploader"] section,
  [data-testid="stFileUploaderDropzone"],
  [data-testid="stFileUploaderDropzone"] > div {
    background: #FFFFFF !important;
    border-color: #D1D5DB !important;
  }
  [data-testid="stFileUploader"] > div > div,
  [data-testid="stFileUploader"] section > div,
  [data-testid="stFileUploaderDropzone"] + div,
  div[data-testid="stFileUploader"] div[style*="background"] {
    background: #FFFFFF !important;
    border-color: #E5E7EB !important;
  }
  [data-testid="stFileUploader"] button,
  [data-testid="stFileUploaderDropzone"] button,
  button[data-testid="baseButton-secondary"][kind="secondary"] {
    background: #1A56E8 !important; color: #FFFFFF !important;
    border: none !important; border-radius: 8px !important;
    font-size: 0.82rem !important; font-weight: 600 !important;
    padding: 7px 16px !important;
    font-family: 'DM Sans', sans-serif !important;
  }
  [data-testid="stFileUploader"] button:hover { background: #1347C8 !important; }
  [data-testid="stFileUploaderDropzoneInstructions"],
  [data-testid="stFileUploaderDropzoneInstructions"] *,
  [data-testid="stFileUploader"] span,
  [data-testid="stFileUploader"] small,
  [data-testid="stFileUploader"] p {
    color: #6B7280 !important;
    background: transparent !important;
  }
  [data-testid="stFileUploaderDropzoneInstructions"] svg { color: #9CA3AF !important; }

  /* ═══════════════════════════════════════════════
     TEXT INPUTS
  ═══════════════════════════════════════════════ */
  [data-baseweb="input"],
  [data-baseweb="textarea"],
  [data-baseweb="base-input"] {
    background: #FFFFFF !important;
    border-color: #D1D5DB !important;
    border-radius: 8px !important;
  }
  [data-baseweb="input"] input,
  [data-baseweb="base-input"] input,
  input[type="text"], input[type="password"], input[type="number"], input[type="email"],
  .stTextInput input, .stNumberInput input, .stTextInput > div > div > input,
  .stNumberInput > div > div > input {
    background: #FFFFFF !important;
    color: #111827 !important;
    border: 1px solid #D1D5DB !important;
    border-radius: 8px !important;
    font-size: 0.875rem !important;
    font-family: 'DM Sans', sans-serif !important;
    padding: 8px 12px !important;
    -webkit-text-fill-color: #111827 !important;
  }
  [data-baseweb="input"] input:focus,
  .stTextInput input:focus,
  .stNumberInput input:focus,
  input:focus {
    border-color: #1A56E8 !important;
    box-shadow: 0 0 0 3px rgba(26,86,232,0.12) !important;
    outline: none !important;
  }
  .stTextInput > div > div,
  .stNumberInput > div > div {
    background: #FFFFFF !important;
    border-radius: 8px !important;
  }
  input:-webkit-autofill,
  input:-webkit-autofill:hover,
  input:-webkit-autofill:focus {
    -webkit-box-shadow: 0 0 0 1000px #FFFFFF inset !important;
    -webkit-text-fill-color: #111827 !important;
    border: 1px solid #D1D5DB !important;
  }

  /* ═══════════════════════════════════════════════
     TEXTAREA
  ═══════════════════════════════════════════════ */
  textarea, .stTextArea textarea {
    background: #FFFFFF !important; color: #111827 !important;
    border: 1px solid #D1D5DB !important; border-radius: 8px !important;
    font-family: 'DM Sans', sans-serif !important;
  }

  /* ═══════════════════════════════════════════════
     SELECT BOXES
  ═══════════════════════════════════════════════ */
  [data-baseweb="select"] > div,
  [data-baseweb="select"] [data-baseweb="control"],
  .stSelectbox > div > div {
    background: #FFFFFF !important;
    border-color: #D1D5DB !important;
    border-radius: 8px !important;
    color: #111827 !important;
  }
  [data-baseweb="select"] span,
  [data-baseweb="select"] [data-baseweb="value"] { color: #111827 !important; }
  [data-baseweb="popover"] { background: #FFFFFF !important; border: 1px solid #E5E7EB !important; border-radius: 8px !important; }
  [data-baseweb="menu"] { background: #FFFFFF !important; }
  [data-baseweb="menu"] li { color: #111827 !important; }
  [data-baseweb="menu"] li:hover { background: #EEF2FF !important; }
  .stSelectbox svg { color: #6B7280 !important; }

  /* ═══════════════════════════════════════════════
     DATE INPUT
  ═══════════════════════════════════════════════ */
  .stDateInput > div > div { background: #FFFFFF !important; border: 1px solid #D1D5DB !important; border-radius: 8px !important; }
  .stDateInput input { background: #FFFFFF !important; color: #111827 !important; font-family: 'DM Sans', sans-serif !important; }

  /* ═══════════════════════════════════════════════
     CHECKBOXES — FIXED
  ═══════════════════════════════════════════════ */
  .stCheckbox,
  [data-testid="stCheckbox"] {
    background: transparent !important;
    user-select: none !important;
  }
  [data-baseweb="checkbox"] {
    background: transparent !important;
    align-items: center !important;
    gap: 8px !important;
  }
  [data-baseweb="checkbox"] > label,
  .stCheckbox > label,
  [data-testid="stCheckbox"] > label {
    background: transparent !important;
    outline: none !important;
    cursor: pointer !important;
    user-select: none !important;
    display: flex !important;
    align-items: center !important;
    gap: 8px !important;
  }
  [data-baseweb="checkbox"] > label:hover,
  [data-baseweb="checkbox"] > label:focus,
  [data-baseweb="checkbox"] > label:active,
  [data-baseweb="checkbox"] > label:focus-within,
  [data-testid="stCheckbox"] > label:hover,
  [data-testid="stCheckbox"] > label:focus,
  [data-testid="stCheckbox"] > label:focus-within {
    background: transparent !important;
    outline: none !important;
    box-shadow: none !important;
  }
  [data-baseweb="checkbox"] label span,
  [data-baseweb="checkbox"] [data-testid="stMarkdownContainer"],
  [data-baseweb="checkbox"] [data-testid="stMarkdownContainer"] p,
  [data-baseweb="checkbox"] p,
  .stCheckbox label span {
    color: #374151 !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    font-family: 'DM Sans', sans-serif !important;
    background: transparent !important;
    visibility: visible !important;
    display: inline !important;
    opacity: 1 !important;
  }
  [data-baseweb="checkbox"] span[role="checkbox"] {
    border: 1.5px solid #D1D5DB !important;
    border-radius: 4px !important;
    background: #FFFFFF !important;
    flex-shrink: 0 !important;
    min-width: 16px !important;
    min-height: 16px !important;
    width: 16px !important;
    height: 16px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
  }
  [data-baseweb="checkbox"] span[role="checkbox"][aria-checked="true"] {
    background: #1A56E8 !important;
    border-color: #1A56E8 !important;
  }
  [data-baseweb="checkbox"] span[role="checkbox"] svg {
    color: #FFFFFF !important;
    fill: #FFFFFF !important;
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
    width: 12px !important;
    height: 12px !important;
  }
  [data-baseweb="checkbox"] span[role="checkbox"]::after,
  [data-baseweb="checkbox"] span[role="checkbox"]::before {
    display: none !important;
    background: transparent !important;
    opacity: 0 !important;
  }
  [data-baseweb="checkbox"] span[role="checkbox"]:focus,
  [data-baseweb="checkbox"] span[role="checkbox"]:focus-visible {
    outline: 2px solid #1A56E8 !important;
    outline-offset: 1px !important;
    box-shadow: none !important;
  }
  input[type="checkbox"] {
    accent-color: #1A56E8 !important;
    width: 16px !important;
    height: 16px !important;
    cursor: pointer !important;
  }

  /* ═══════════════════════════════════════════════
     BUTTONS
  ═══════════════════════════════════════════════ */
  .stButton > button[kind="primary"],
  button[kind="primary"],
  [data-testid="baseButton-primary"] {
    background: #1A56E8 !important; color: #FFFFFF !important;
    border: none !important; border-radius: 8px !important;
    font-size: 0.875rem !important; font-weight: 600 !important;
    padding: 10px 22px !important; letter-spacing: 0 !important;
    box-shadow: 0 1px 3px rgba(26,86,232,0.3) !important;
    font-family: 'DM Sans', sans-serif !important;
    transition: background 0.15s ease !important;
  }
  .stButton > button[kind="primary"]:hover,
  [data-testid="baseButton-primary"]:hover { background: #1347C8 !important; }

  .stButton > button:not([kind="primary"]),
  .stButton > button[kind="secondary"],
  [data-testid="baseButton-secondary"] {
    background: #FFFFFF !important; color: #374151 !important;
    border: 1px solid #D1D5DB !important; border-radius: 8px !important;
    font-size: 0.875rem !important; font-weight: 500 !important;
    padding: 9px 18px !important;
    font-family: 'DM Sans', sans-serif !important;
  }
  .stButton > button:not([kind="primary"]):hover,
  [data-testid="baseButton-secondary"]:hover {
    background: #F9FAFB !important; border-color: #9CA3AF !important;
  }

  [data-testid="stDownloadButton"] button {
    background: #FFFFFF !important; color: #374151 !important;
    border: 1px solid #D1D5DB !important; border-radius: 8px !important;
    font-size: 0.82rem !important; font-weight: 500 !important;
    font-family: 'DM Sans', sans-serif !important;
  }
  [data-testid="stDownloadButton"] button:hover {
    background: #F9FAFB !important; border-color: #9CA3AF !important;
  }

  /* ═══════════════════════════════════════════════
     FORM
  ═══════════════════════════════════════════════ */
  [data-testid="stForm"] {
    background: #FFFFFF !important;
    border: 1px solid #E5E7EB !important;
    border-radius: 12px !important;
    padding: 1.5rem !important;
  }

  /* ═══════════════════════════════════════════════
     TABS
  ═══════════════════════════════════════════════ */
  [data-testid="stTabs"] [role="tablist"] {
    background: #FFFFFF !important;
    border-bottom: 1px solid #E5E7EB !important;
    padding: 0 1rem !important;
    border-radius: 12px 12px 0 0 !important;
    gap: 0 !important;
  }
  [data-testid="stTabs"] [role="tab"] {
    font-size: 0.875rem !important; font-weight: 500 !important;
    color: #6B7280 !important; padding: 0.75rem 1.25rem !important;
    border-bottom: 2px solid transparent !important;
    background: transparent !important;
    font-family: 'DM Sans', sans-serif !important;
  }
  [data-testid="stTabs"] [role="tab"]:hover { color: #111827 !important; }
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

  /* ═══════════════════════════════════════════════
     EXPANDER
  ═══════════════════════════════════════════════ */
  [data-testid="stExpander"],
  .streamlit-expanderHeader,
  details > summary {
    background: #F9FAFB !important;
    border: 1px solid #E5E7EB !important;
    border-radius: 8px !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    color: #374151 !important;
    font-family: 'DM Sans', sans-serif !important;
  }
  .streamlit-expanderContent,
  details[open] > div {
    background: #FFFFFF !important;
    border: 1px solid #E5E7EB !important;
    border-top: none !important;
    border-radius: 0 0 8px 8px !important;
    padding: 1rem !important;
  }

  /* ═══════════════════════════════════════════════
     DATAFRAME & TABLE
  ═══════════════════════════════════════════════ */
  [data-testid="stDataFrame"] {
    border-radius: 10px !important;
    overflow: hidden !important;
    border: 1px solid #E5E7EB !important;
  }
  [data-testid="stDataFrame"] table { background: #FFFFFF !important; }
  [data-testid="stDataFrame"] thead tr th {
    background: #F9FAFB !important; color: #6B7280 !important;
    font-size: 0.72rem !important; font-weight: 600 !important;
    text-transform: uppercase !important; letter-spacing: 0.06em !important;
    border-bottom: 1px solid #E5E7EB !important;
  }
  [data-testid="stDataFrame"] tbody tr { background: #FFFFFF !important; }
  [data-testid="stDataFrame"] tbody tr:hover { background: #F9FAFB !important; }
  [data-testid="stDataFrame"] tbody td { color: #111827 !important; font-size: 0.875rem !important; border-bottom: 1px solid #F3F4F6 !important; }

  /* ═══════════════════════════════════════════════
     METRICS
  ═══════════════════════════════════════════════ */
  [data-testid="stMetric"] {
    background: #FFFFFF !important;
    border: 1px solid #E5E7EB !important;
    border-radius: 10px !important;
    padding: 1rem !important;
  }
  [data-testid="stMetricLabel"] {
    font-size: 0.72rem !important; color: #6B7280 !important;
    text-transform: uppercase !important; letter-spacing: 0.06em !important;
    font-family: 'DM Sans', sans-serif !important;
  }
  [data-testid="stMetricValue"] {
    font-size: 1.35rem !important; font-weight: 700 !important;
    color: #111827 !important; font-family: 'DM Sans', sans-serif !important;
  }

  /* ═══════════════════════════════════════════════
     ALERTS
  ═══════════════════════════════════════════════ */
  [data-testid="stAlert"],
  div[data-baseweb="notification"] {
    border-radius: 8px !important;
    font-size: 0.875rem !important;
    font-family: 'DM Sans', sans-serif !important;
  }

  /* ═══════════════════════════════════════════════
     PROGRESS BAR
  ═══════════════════════════════════════════════ */
  [data-testid="stProgressBar"] {
    background: #E5E7EB !important;
    border-radius: 4px !important;
  }
  [data-testid="stProgressBar"] > div > div {
    background: #1A56E8 !important;
    border-radius: 4px !important;
  }

  /* ═══════════════════════════════════════════════
     CAMERA INPUT
  ═══════════════════════════════════════════════ */
  [data-testid="stCameraInput"] > div {
    border: 1.5px dashed #D1D5DB !important;
    border-radius: 10px !important;
    background: #FAFAFA !important;
  }
  [data-testid="stCameraInput"] button {
    background: #1A56E8 !important; color: white !important;
    border-radius: 8px !important; border: none !important;
    font-weight: 600 !important;
  }

  /* ═══════════════════════════════════════════════
     LABEL / CAPTION TEXT
  ═══════════════════════════════════════════════ */
  label, .stTextInput label, .stNumberInput label, .stSelectbox label,
  .stCheckbox label, [data-testid="stWidgetLabel"] {
    color: #374151 !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    font-family: 'DM Sans', sans-serif !important;
  }
  small, .stCaption, [data-testid="stCaptionContainer"] {
    color: #6B7280 !important;
    font-family: 'DM Sans', sans-serif !important;
  }

  /* ═══════════════════════════════════════════════
     MISC
  ═══════════════════════════════════════════════ */
  hr { border: none !important; border-top: 1px solid #E5E7EB !important; margin: 1rem 0 !important; }

  /* ═══════════════════════════════════════════════
     FORM SUBMIT BUTTON
  ═══════════════════════════════════════════════ */
  [data-testid="baseButton-primaryFormSubmit"],
  button[data-testid="baseButton-primaryFormSubmit"],
  .stFormSubmitButton > button,
  [data-testid="stFormSubmitButton"] button,
  form button[type="submit"],
  form button {
    background: #1A56E8 !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 8px !important;
    font-size: 0.9rem !important;
    font-weight: 600 !important;
    padding: 12px 22px !important;
    font-family: 'DM Sans', sans-serif !important;
    box-shadow: 0 1px 4px rgba(26,86,232,0.3) !important;
    transition: background 0.15s ease !important;
    width: 100% !important;
  }
  [data-testid="baseButton-primaryFormSubmit"]:hover,
  .stFormSubmitButton > button:hover { background: #1347C8 !important; }

  /* ═══════════════════════════════════════════════
     PASSWORD / INPUT ADDON BUTTONS
  ═══════════════════════════════════════════════ */
  [data-baseweb="input"] [role="button"],
  [data-baseweb="input"] button,
  [data-baseweb="base-input"] ~ div button,
  input + div button,
  [data-testid="stTextInput"] button,
  div[data-baseweb="input-container"] button {
    background: #F9FAFB !important;
    color: #6B7280 !important;
    border: none !important;
    border-left: 1px solid #E5E7EB !important;
    border-radius: 0 8px 8px 0 !important;
    padding: 0 12px !important;
  }
  [data-baseweb="input"] [role="button"]:hover,
  [data-baseweb="input"] button:hover { background: #F3F4F6 !important; color: #374151 !important; }
  [data-baseweb="input"] svg,
  [data-testid="stTextInput"] svg { color: #6B7280 !important; fill: #6B7280 !important; }

  /* ═══════════════════════════════════════════════
     INPUT CONTAINER BORDER
  ═══════════════════════════════════════════════ */
  [data-baseweb="input"],
  [data-baseweb="input-container"],
  [data-baseweb="base-input"] {
    background: #FFFFFF !important;
    border: 1px solid #D1D5DB !important;
    border-radius: 8px !important;
    overflow: hidden !important;
  }
  [data-baseweb="input"]:focus-within,
  [data-baseweb="input-container"]:focus-within {
    border-color: #1A56E8 !important;
    box-shadow: 0 0 0 3px rgba(26,86,232,0.12) !important;
  }

  /* ═══════════════════════════════════════════════
     HIDE ROGUE NAV ELEMENTS
  ═══════════════════════════════════════════════ */
  [data-testid="stSidebarNavItems"],
  [data-testid="stSidebarNavSeparator"] { display: none !important; }
  [data-testid="stSearchBox"],
  .stSearchBox { display: none !important; }
  [data-testid="stSidebar"] nav button { display: none !important; }

  /* ── TrackBook component classes ── */
  .tb-brand {
    padding: 1rem 1.25rem 0.875rem;
    font-size: 1.05rem; font-weight: 700; letter-spacing: -0.3px;
    color: #111827; border-bottom: 1px solid #E5E7EB;
    display: flex; align-items: center; gap: 8px; margin-bottom: 0.5rem;
  }
  .tb-brand-dot { width: 9px; height: 9px; border-radius: 50%; background: #1A56E8; }

  .tb-page-title { font-size: 1.2rem; font-weight: 700; color: #111827; margin-bottom: 2px; }
  .tb-page-sub   { font-size: 0.82rem; color: #6B7280; margin-bottom: 1.25rem; }

  .tb-upload {
    background: #FFFFFF; border: 1.5px dashed #D1D5DB; border-radius: 10px;
    padding: 1.5rem; text-align: center; margin-bottom: 0.75rem; display: none;
  }
  .tb-upload-icon { font-size: 1.5rem; margin-bottom: 6px; }
  .tb-upload-title { font-size: 0.9rem; font-weight: 600; color: #374151; margin-bottom: 2px; }
  .tb-upload-sub { font-size: 0.78rem; color: #9CA3AF; }

  .tb-field {
    background: #F9FAFB; border: 1px solid #E5E7EB;
    border-radius: 8px; padding: 0.6rem 0.85rem; margin-bottom: 0.5rem;
  }
  .tb-field-label {
    font-size: 0.65rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.07em; color: #9CA3AF;
    display: flex; align-items: center; gap: 5px; margin-bottom: 3px;
  }
  .tb-field-value { font-size: 0.875rem; color: #111827; font-weight: 500; }
  .tb-field-null  { font-size: 0.875rem; color: #D1D5DB; font-style: italic; }
  .tb-conf-bar    { height: 2px; border-radius: 1px; margin-top: 5px; }
  .tb-conf-bar-high   { background: #16a34a; width: 100%; }
  .tb-conf-bar-medium { background: #d97706; width: 60%; }
  .tb-conf-bar-low    { background: #dc2626; width: 25%; }

  .tb-badge {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 2px 9px; border-radius: 99px;
    font-size: 0.72rem; font-weight: 600; letter-spacing: 0.02em;
  }
  .tb-badge-green  { background: #DCFCE7; color: #15803D; }
  .tb-badge-amber  { background: #FEF3C7; color: #B45309; }
  .tb-badge-red    { background: #FEE2E2; color: #B91C1C; }
  .tb-badge-blue   { background: #EEF2FF; color: #1A56E8; }
  .tb-badge-gray   { background: #F3F4F6; color: #6B7280; }

  .tb-logo-row { display: flex; align-items: center; gap: 12px; margin-bottom: 1rem; }
  .tb-monogram {
    width: 48px; height: 48px; border-radius: 10px; background: #EEF2FF;
    display: flex; align-items: center; justify-content: center;
    font-size: 1rem; font-weight: 800; color: #1A56E8; flex-shrink: 0;
  }
  .tb-vendor-name { font-size: 1rem; font-weight: 700; color: #111827; }
  .tb-vendor-sub  { font-size: 0.78rem; color: #6B7280; margin-top: 2px; }

  .tb-fraud-box {
    background: #FFF1F2; border: 1px solid #FECDD3;
    border-radius: 10px; padding: 0.85rem 1rem; margin-bottom: 0.75rem;
  }
  .tb-fraud-title { font-size: 0.8rem; font-weight: 600; color: #B91C1C; margin-bottom: 6px; }
  .tb-fraud-item  { font-size: 0.8rem; color: #7F1D1D; margin-bottom: 3px; }

  .tb-dup-box {
    background: #FFFBEB; border: 1px solid #FDE68A;
    border-radius: 10px; padding: 0.85rem 1rem; margin-bottom: 0.75rem;
  }

  .tb-queue-row {
    display: flex; align-items: center; gap: 10px;
    padding: 0.6rem 0.85rem; border-radius: 8px;
    background: #F9FAFB; border: 1px solid #E5E7EB;
    margin-bottom: 6px; font-size: 0.82rem; color: #374151;
  }
  .tb-queue-name { flex: 1; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .status-pending  { color: #9CA3AF; }
  .status-running  { color: #1A56E8; }
  .status-done     { color: #16a34a; }
  .status-error    { color: #dc2626; }
  .status-skipped  { color: #d97706; }

  .tb-metric-strip { display: flex; gap: 0.75rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .tb-metric {
    flex: 1; min-width: 120px; background: #FFFFFF;
    border: 1px solid #E5E7EB; border-radius: 10px; padding: 0.85rem 1rem;
  }
  .tb-metric-label { font-size: 0.7rem; color: #6B7280; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; }
  .tb-metric-value { font-size: 1.25rem; font-weight: 700; color: #111827; margin-top: 4px; }

  .tb-section-head {
    font-size: 0.65rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.08em; color: #9CA3AF; margin: 1rem 0 0.5rem;
  }
  .tb-ok-box {
    background: #F0FDF4; border: 1px solid #BBF7D0;
    border-radius: 10px; padding: 0.7rem 1rem;
    font-size: 0.82rem; color: #15803D; margin-bottom: 0.75rem;
  }
</style>
""", unsafe_allow_html=True)


# ── Force-override iframe/shadow-DOM widgets via components ──────────────────
import streamlit.components.v1 as _st_comp
_st_comp.html("""
<script>
(function forceStyles() {
  const css = `
    [data-testid="stFileUploader"] section,
    [data-testid="stFileUploader"] > div,
    [data-testid="stFileUploaderDropzone"] {
      background: #FFFFFF !important;
    }
    [data-testid="stFileUploader"] > div > div:last-child,
    [data-testid="stFileUploader"] section > div:last-child {
      background: #F9FAFB !important;
      border-top: 1px solid #E5E7EB !important;
    }
  `;
  function inject() {
    const frames = document.querySelectorAll("iframe");
    frames.forEach(frame => {
      try {
        const doc = frame.contentDocument || frame.contentWindow.document;
        if (!doc) return;
        const style = doc.createElement("style");
        style.textContent = css;
        doc.head.appendChild(style);
      } catch(e) {}
    });
    let mainStyle = document.getElementById("tb-force-style");
    if (!mainStyle) {
      mainStyle = document.createElement("style");
      mainStyle.id = "tb-force-style";
      mainStyle.textContent = css;
      document.head.appendChild(mainStyle);
    }
  }
  inject();
  const obs = new MutationObserver(inject);
  obs.observe(document.body, { childList: true, subtree: true });
})();
</script>
""", height=0)

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
              <div style="font-size:1.5rem;font-weight:800;letter-spacing:-0.5px;color:#111827">
                <span style="display:inline-block;width:10px;height:10px;background:#1A56E8;border-radius:50%;margin-right:6px;vertical-align:middle"></span>
                TrackBook
              </div>
              <div style="font-size:0.82rem;color:#6B7280;margin-top:4px">Invoice Intelligence · NxtWave</div>
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

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div class="tb-brand">
      <span class="tb-brand-dot"></span> TrackBook
    </div>
    """, unsafe_allow_html=True)
    st.caption(f"Signed in as **{st.session_state.get('username','user')}**")
    if st.button("Sign out", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()
    st.divider()
    
    st.markdown("### NAVIGATION")
    
    # These buttons will change the active tab using session state
    if st.button("📤 Extract Invoices", use_container_width=True, 
                 type="primary" if st.session_state.active_tab == "Extract" else "secondary"):
        st.session_state.active_tab = "Extract"
        st.rerun()
    
    if st.button("📷 Scan Receipt", use_container_width=True,
                 type="primary" if st.session_state.active_tab == "Scan" else "secondary"):
        st.session_state.active_tab = "Scan"
        st.rerun()
    
    if st.button("📋 History", use_container_width=True,
                 type="primary" if st.session_state.active_tab == "History" else "secondary"):
        st.session_state.active_tab = "History"
        st.rerun()
    
    if st.button("📊 Spend Summary", use_container_width=True,
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
    conf_dot = ""
    bar_html = ""
    if score:
        colours = {"high": "#16a34a", "medium": "#d97706", "low": "#dc2626"}
        col = colours.get(score, "#D1D5DB")
        conf_dot = f'<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:{col};margin-left:4px"></span>'
        bar_html = f'<div class="tb-conf-bar tb-conf-bar-{score}"></div>'
    return (f'<div class="tb-field">'
            f'<div class="tb-field-label">{label}{conf_dot}</div>'
            f'{v_html}{bar_html}'
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
            model="claude-opus-4-5",
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": (
                        "Does this invoice have a vendor/company logo (graphic mark, wordmark, or icon)? "
                        "Reply ONLY with valid JSON — no markdown:\n"
                        '{"has_logo":true,"x1_pct":5,"y1_pct":2,"x2_pct":28,"y2_pct":18}\n'
                        "x1/y1 = top-left, x2/y2 = bottom-right, values are % of image w/h. "
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
        pad = 10
        x1 = max(0, int(info["x1_pct"] / 100 * w) - pad)
        y1 = max(0, int(info["y1_pct"] / 100 * h) - pad)
        x2 = min(w, int(info["x2_pct"] / 100 * w) + pad)
        y2 = min(h, int(info["y2_pct"] / 100 * h) + pad)
        if x2 > x1 and y2 > y1:
            logo = img.crop((x1, y1, x2, y2))
            buf = io.BytesIO()
            logo.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        pass
    return None


def render_logo_header(vendor_name: str, logo_bytes: bytes | None):
    initials = "".join(w[0].upper() for w in (vendor_name or "??").split()[:2])
    if logo_bytes:
        c1, c2 = st.columns([1, 8])
        with c1:
            st.image(logo_bytes, width=52)
        with c2:
            st.markdown(
                f'<div class="tb-vendor-name" style="padding-top:14px">{vendor_name or "—"}</div>',
                unsafe_allow_html=True)
    else:
        st.markdown(
            f'<div class="tb-logo-row">'
            f'<div class="tb-monogram">{initials}</div>'
            f'<div><div class="tb-vendor-name">{vendor_name or "—"}</div>'
            f'<div class="tb-vendor-sub">Vendor</div></div>'
            f'</div>', unsafe_allow_html=True)


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
    if not text:
        return None
    u = text.upper()
    for code in _CA_TAX:
        if re.search(r'\b' + code + r'\b', u):
            return code
    for code, name in _CA_NAMES.items():
        if name.upper() in u:
            return code
    return None

def canadian_tax_flags(data: dict) -> list[str]:
    flags = []
    v_addr  = (data.get("vendor", {}).get("address") or "")
    b_addr  = (data.get("buyer",  {}).get("address") or "")
    currency = (data.get("invoice_meta", {}).get("currency") or "").upper()
    is_ca = (currency == "CAD" or "CANADA" in v_addr.upper() or "CANADA" in b_addr.upper()
             or _detect_province(v_addr) or _detect_province(b_addr))
    if not is_ca:
        return flags
    subtotal  = float(data.get("totals", {}).get("subtotal")  or 0)
    tax_total = float(data.get("totals", {}).get("tax_total") or 0)
    province  = _detect_province(v_addr) or _detect_province(b_addr)
    if subtotal > 0 and tax_total > 0:
        eff = tax_total / subtotal * 100
        if province:
            gst, pst, hst, label = _CA_TAX[province]
            expected = hst if hst else (gst + pst)
            if abs(eff - expected) > 0.6:
                flags.append(f"🇨🇦 {_CA_NAMES[province]}: expected {expected:.1f}% ({label}), got {eff:.1f}% — tax mismatch")
        elif eff > 15.0:
            flags.append(f"🇨🇦 Tax rate {eff:.1f}% exceeds max Canadian HST (15%)")
    tax_id = (data.get("vendor", {}).get("tax_id") or "")
    if tax_id and currency == "CAD":
        digits = re.sub(r"\D", "", tax_id)
        if len(digits) not in (9, 15):
            flags.append(f"🇨🇦 Vendor tax ID '{tax_id}' doesn't match Canadian BN format (9 or 15 digits)")
    return flags


# ── Enhanced Fraud ────────────────────────────────────────────────────────────
def enhanced_fraud_flags(data: dict) -> list[str]:
    flags = []
    m = data.get("invoice_meta", {})
    t = data.get("totals", {})
    items = data.get("line_items", [])
    try:
        from datetime import date as _date
        inv_d = m.get("invoice_date")
        due_d = m.get("due_date")
        if inv_d and due_d and due_d < inv_d:
            flags.append(f"Due date ({due_d}) is before invoice date ({inv_d})")
    except Exception:
        pass
    amounts = [float(i.get("amount") or 0) for i in items if i.get("amount")]
    if len(amounts) >= 2 and all(a % 100 == 0 for a in amounts):
        flags.append("All line item amounts are round multiples of 100 — may be fabricated")
    if amounts:
        items_sum = sum(amounts)
        grand = float(t.get("grand_total") or 0)
        if grand > 0 and abs(items_sum - grand) > 1.0:
            flags.append(f"Line items sum ({items_sum:,.2f}) doesn't match grand total ({grand:,.2f})")
    if not m.get("invoice_number"):
        flags.append("Invoice number is missing")
    for item in items:
        qty = float(item.get("quantity") or 0)
        if qty > 9999:
            flags.append(f"Unusually high quantity ({qty}) for: {item.get('description','?')}")
    return flags


# ── Input Validation ──────────────────────────────────────────────────────────
def is_valid_invoice(data: dict) -> tuple[bool, str]:
    doc_type = data.get("document_type", "invoice")
    if doc_type not in ("invoice", "receipt", "credit_note", "bill"):
        return False, f"Document type is '{doc_type}' — expected invoice, receipt or bill."
    conf = data.get("confidence", {}).get("overall", "low")
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
        return False, "No invoice fields found — this doesn't look like an invoice or receipt."
    if null_critical >= 3 and conf == "low":
        return False, f"{null_critical}/4 key fields missing with low confidence — document may not be an invoice."
    return True, ""


# ── Fraud render ──────────────────────────────────────────────────────────────
def render_fraud_section(fraud: dict, extra_flags: list[str] | None = None):
    fraud = fraud or {}
    risk  = fraud.get("risk_level", "low")
    flags = list(fraud.get("flags", [])) + (extra_flags or [])
    math  = fraud.get("math_check", {})
    is_sus = fraud.get("is_suspicious", False)
    if extra_flags and risk == "low":
        risk = "medium"
    if is_sus or risk in ("medium", "high") or flags:
        items_html = "".join(f'<div class="tb-fraud-item">• {f}</div>' for f in flags) if flags else '<div class="tb-fraud-item">Flagged as suspicious</div>'
        st.markdown(
            f'<div class="tb-fraud-box">'
            f'<div class="tb-fraud-title">🚨 Fraud analysis — {risk_badge(risk)}</div>'
            f'{items_html}</div>',
            unsafe_allow_html=True)
    else:
        st.markdown('<div class="tb-ok-box">✓ No fraud indicators detected</div>', unsafe_allow_html=True)
    if math and not math.get("matches", True):
        e, a = math.get("expected_total"), math.get("actual_total")
        if e and a:
            st.warning(f"⚠️ Math check: expected {e}, invoice shows {a}")


# ── Field scores render ───────────────────────────────────────────────────────
def render_field_scores(scores: dict, data: dict):
    m = data.get("invoice_meta", {})
    v = data.get("vendor", {})
    b = data.get("buyer", {})
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown('<div class="tb-section-head">Invoice details</div>', unsafe_allow_html=True)
        for label, key, sk in [
            ("Invoice #", "invoice_number", "invoice_number"),
            ("PO #", "po_number", None),
            ("Invoice date", "invoice_date", "invoice_date"),
            ("Due date", "due_date", "due_date"),
            ("Terms", "terms", None),
            ("Currency", "currency", None),
        ]:
            st.markdown(field_card(label, m.get(key), scores.get(sk) if sk else None), unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="tb-section-head">Vendor</div>', unsafe_allow_html=True)
        for label, key, sk in [
            ("Name", "name", "vendor_name"),
            ("Address", "address", None),
            ("Email", "email", None),
            ("Phone", "phone", None),
            ("Tax ID", "tax_id", "vendor_tax_id"),
        ]:
            st.markdown(field_card(label, v.get(key), scores.get(sk) if sk else None), unsafe_allow_html=True)
    with c3:
        st.markdown('<div class="tb-section-head">Bill to</div>', unsafe_allow_html=True)
        st.markdown(field_card("Name", b.get("name")), unsafe_allow_html=True)
        st.markdown(field_card("Address", b.get("address")), unsafe_allow_html=True)


# ── Full invoice render ───────────────────────────────────────────────────────
def render_invoice(data: dict, invoice_id: int = None, editable: bool = False,
                   logo_bytes: bytes | None = None, key_prefix: str = "") -> dict:
    m     = data.get("invoice_meta", {})
    v     = data.get("vendor", {})
    b     = data.get("buyer", {})
    t     = data.get("totals", {})
    conf  = data.get("confidence", {})
    fraud = data.get("fraud_flags", {})
    cur   = m.get("currency") or ""
    scores = conf.get("field_scores", {})

    render_logo_header(v.get("name"), logo_bytes)

    h1, h2, h3, h4 = st.columns(4)
    h1.markdown(f"**Confidence** {conf_badge(conf.get('overall','low'))}", unsafe_allow_html=True)
    h2.markdown(f"**Type** `{data.get('document_type','invoice')}`")
    h3.markdown(f"**Fraud** {risk_badge((fraud or {}).get('risk_level','low'))}", unsafe_allow_html=True)
    if invoice_id:
        h4.markdown(_badge(f"✓ Saved #{invoice_id}", "blue"), unsafe_allow_html=True)

    flagged = conf.get("flagged_fields", [])
    if flagged:
        st.warning(f"Flagged: {', '.join(flagged)}")

    st.divider()

    extra = enhanced_fraud_flags(data) + canadian_tax_flags(data)
    render_fraud_section(fraud, extra_flags=extra or None)

    if editable:
        st.markdown("**✏️ Edit fields before saving**")
        ec1, ec2 = st.columns(2)
        with ec1:
            v["name"]           = st.text_input("Vendor name", v.get("name") or "",            key=f"{key_prefix}_vname")
            v["tax_id"]         = st.text_input("Vendor tax ID", v.get("tax_id") or "",        key=f"{key_prefix}_vtaxid")
            m["invoice_number"] = st.text_input("Invoice #", m.get("invoice_number") or "",    key=f"{key_prefix}_invnum")
            m["invoice_date"]   = st.text_input("Invoice date (YYYY-MM-DD)", m.get("invoice_date") or "", key=f"{key_prefix}_invdate")
            m["due_date"]       = st.text_input("Due date (YYYY-MM-DD)", m.get("due_date") or "", key=f"{key_prefix}_duedate")
        with ec2:
            b["name"]       = st.text_input("Buyer name", b.get("name") or "",    key=f"{key_prefix}_bname")
            m["currency"]   = st.text_input("Currency", m.get("currency") or "",  key=f"{key_prefix}_currency")
            raw_total       = st.text_input("Grand total", str(t.get("grand_total") or ""), key=f"{key_prefix}_grandtotal")
            try:
                t["grand_total"] = float(raw_total) if raw_total else None
            except ValueError:
                pass
            m["terms"] = st.text_input("Terms", m.get("terms") or "", key=f"{key_prefix}_terms")
        data["vendor"] = v; data["buyer"] = b
        data["invoice_meta"] = m; data["totals"] = t
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
    tc1, tc2, tc3, tc4 = st.columns(4)
    for col, label, key in [
        (tc1, "Subtotal", "subtotal"), (tc2, "Discount", "discount"),
        (tc3, "Tax", "tax_total"), (tc4, "Grand total", "grand_total")
    ]:
        amt = t.get(key)
        col.metric(label, f"{cur} {amt:,.2f}" if amt is not None else "—")

    if data.get("notes"):
        st.divider()
        st.info(data["notes"])

    st.divider()
    with st.expander("View raw JSON"):
        st.json(data)
    st.download_button("⬇ Download JSON", data=json.dumps(data, indent=2),
        file_name=f"invoice_{invoice_id or 'extracted'}.json", mime="application/json",
        key=f"dl_{invoice_id or 'new'}_{id(data)}")
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
        mt_map = {".png":"image/png", ".jpg":"image/jpeg", ".jpeg":"image/jpeg",
                  ".webp":"image/webp", ".pdf":"application/pdf"}
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
        icon = {"saved":"✅","extracted":"📄","rejected":"🚫","error":"❌"}.get(r["status"],"❓")
        with st.expander(f"{icon} {r['name']}", expanded=(r["status"] not in ("saved",))):
            if r["status"] == "rejected":
                st.error(f"Rejected: {r['rejected']}")
                continue
            if r["status"] == "error":
                st.error(f"Error: {r['error']}")
                continue

            data = r["data"]

            if r["dup"]:
                dup = r["dup"]
                st.markdown(
                    f'<div class="tb-dup-box">⚠️ <b>Duplicate:</b> Invoice already exists as '
                    f'DB #{dup["id"]} — {dup["vendor_name"]}, total {dup["grand_total"]}</div>',
                    unsafe_allow_html=True)
                # FIX 2: "Save anyway" is now a button, not a checkbox
                force = st.button("Save anyway", key=f"force_{r['name']}", type="secondary")
                if force and db_ok:
                    try:
                        iid = save_invoice(data)
                        r["invoice_id"] = iid
                        st.success(f"✓ Force-saved as #{iid}")
                    except Exception as e:
                        st.warning(str(e))

            if r["logo_bytes"]:
                import base64 as _b64
                data["_logo_b64"] = _b64.b64encode(r["logo_bytes"]).decode("utf-8")

            if edit_mode:
                data = render_invoice(data, editable=True, logo_bytes=r["logo_bytes"], key_prefix=r["name"])
                if st.button(f"💾 Confirm & Save", key=f"esave_{r['name']}") and db_ok:
                    try:
                        iid = save_invoice(data)
                        st.success(f"✓ Saved #{iid}")
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

# Initialize active tab from session state if not exists
if 'active_tab' not in st.session_state:
    st.session_state.active_tab = "Extract"

# Create tabs normally - they will always be in the same order
tab_extract, tab_scan, tab_history, tab_summary = st.tabs(
    ["📤 Extract", "📷 Scan Receipt", "📋 History", "📊 Spend Summary"]
)
# Add JavaScript to switch tabs based on session state
if st.session_state.active_tab != "Extract":
    tab_index = {
        "Extract": 0,
        "Scan": 1, 
        "History": 2,
        "Summary": 3
    }.get(st.session_state.active_tab, 0)
    
    st.components.v1.html(f"""
    <script>
        // Function to click the correct tab
        function activateTab() {{
            const tabs = window.parent.document.querySelectorAll('[data-testid="stTabs"] button');
            if (tabs && tabs[{tab_index}]) {{
                tabs[{tab_index}].click();
            }}
        }}
        setTimeout(activateTab, 100);
    </script>
    """, height=0)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — EXTRACT
# ══════════════════════════════════════════════════════════════════════════════
with tab_extract:
    st.markdown("""
    <div style="margin-bottom:1.25rem">
      <div style="font-size:1.25rem;font-weight:700;color:#111827">Extract invoices</div>
      <div style="font-size:0.82rem;color:#6B7280;margin-top:2px">
        Upload any number of invoices — processed 3 at a time with full fraud &amp; tax analysis.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # FIX 1: logo always on, other two are stateful toggle buttons
    do_logo = True  # always extract automatically

    if "edit_mode" not in st.session_state:
        st.session_state.edit_mode = False
    if "auto_save" not in st.session_state:
        st.session_state.auto_save = True

    oc1, oc2, _ = st.columns([2, 2, 4])
    with oc1:
        em_bg  = "#EEF2FF" if st.session_state.edit_mode else "#F9FAFB"
        em_col = "#1A56E8" if st.session_state.edit_mode else "#6B7280"
        em_bd  = "#C7D2FE" if st.session_state.edit_mode else "#E5E7EB"
        em_lbl = "✏️ Edit mode: ON" if st.session_state.edit_mode else "✏️ Edit mode: OFF"
        st.markdown(f'<div style="background:{em_bg};border:1px solid {em_bd};border-radius:8px;'
                    f'padding:8px 14px;font-size:0.82rem;font-weight:600;color:{em_col};margin-bottom:4px">'
                    f'{em_lbl}</div>', unsafe_allow_html=True)
        if st.button("Toggle edit mode", key="toggle_edit", use_container_width=True):
            st.session_state.edit_mode = not st.session_state.edit_mode
            st.rerun()
    with oc2:
        as_bg  = "#DCFCE7" if st.session_state.auto_save else "#F9FAFB"
        as_col = "#15803D" if st.session_state.auto_save else "#6B7280"
        as_bd  = "#BBF7D0" if st.session_state.auto_save else "#E5E7EB"
        as_lbl = "💾 Auto-save: ON" if st.session_state.auto_save else "💾 Auto-save: OFF"
        st.markdown(f'<div style="background:{as_bg};border:1px solid {as_bd};border-radius:8px;'
                    f'padding:8px 14px;font-size:0.82rem;font-weight:600;color:{as_col};margin-bottom:4px">'
                    f'{as_lbl}</div>', unsafe_allow_html=True)
        if st.button("Toggle auto-save", key="toggle_save", use_container_width=True):
            st.session_state.auto_save = not st.session_state.auto_save
            st.rerun()

    edit_mode = st.session_state.edit_mode
    auto_save = st.session_state.auto_save

    st.markdown('<div class="tb-upload">'
                '<div class="tb-upload-icon">📄</div>'
                '<div class="tb-upload-title">Upload invoices</div>'
                '<div class="tb-upload-sub">PDF, PNG, JPG, WEBP — no file limit</div>'
                '</div>', unsafe_allow_html=True)

    uploaded_files = st.file_uploader(
        "Upload invoices",
        type=["pdf", "png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    if uploaded_files:
        n = len(uploaded_files)
        workers = min(BATCH_WORKERS, n)
        est = max(1, n // workers) * 12

        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;margin:0.75rem 0">'
            f'{_badge(f"{n} file(s) selected", "blue")}'
            f'<span style="font-size:0.78rem;color:#6B7280">{workers} parallel workers · ~{est}s estimated</span>'
            f'</div>', unsafe_allow_html=True)

        if st.button("⚡ Process all", type="primary"):

            st.markdown('<div class="tb-section-head">Processing queue</div>', unsafe_allow_html=True)
            status_slots = {f.name: st.empty() for f in uploaded_files}

            def _update_slot(name, status, icon="⏳"):
                status_slots[name].markdown(
                    f'<div class="tb-queue-row">'
                    f'<span class="status-{status}">{icon}</span>'
                    f'<span class="tb-queue-name">{name}</span>'
                    f'<span class="tb-badge tb-badge-gray" style="font-size:0.68rem">{status}</span>'
                    f'</div>', unsafe_allow_html=True)

            for f in uploaded_files:
                _update_slot(f.name, "pending", "○")

            progress_bar = st.progress(0, text="Starting batch…")
            completed_count = 0
            all_results = []

            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_file = {
                    executor.submit(_process_single, f, do_logo, auto_save and not edit_mode): f
                    for f in uploaded_files
                }
                for f in uploaded_files:
                    _update_slot(f.name, "running", "●")

                for future in as_completed(future_to_file):
                    f = future_to_file[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        result = {"name": f.name, "status": "error", "error": str(e),
                                  "data": None, "logo_bytes": None, "invoice_id": None,
                                  "dup": None, "rejected": None}

                    all_results.append(result)
                    completed_count += 1

                    status_map = {
                        "saved": ("done", "✓"),
                        "extracted": ("running", "~"),
                        "rejected": ("error", "✗"),
                        "error": ("error", "✗"),
                    }
                    sc, ic = status_map.get(result["status"], ("pending", "?"))
                    _update_slot(result["name"], result["status"], ic)

                    pct = completed_count / n
                    progress_bar.progress(pct, text=f"{completed_count}/{n} processed…")

            progress_bar.progress(1.0, text="Done!")

            saved    = sum(1 for r in all_results if r["status"] == "saved")
            errors   = sum(1 for r in all_results if r["status"] == "error")
            rejected = sum(1 for r in all_results if r["status"] == "rejected")
            dups     = sum(1 for r in all_results if r.get("dup"))

            st.markdown(
                f'<div style="display:flex;gap:0.75rem;margin:1rem 0;flex-wrap:wrap">'
                f'{_badge(f"✓ {saved} saved", "green")}'
                f'{_badge(f"⚠ {dups} duplicates", "amber") if dups else ""}'
                f'{_badge(f"✗ {rejected} rejected", "red") if rejected else ""}'
                f'{_badge(f"✗ {errors} errors", "red") if errors else ""}'
                f'</div>', unsafe_allow_html=True)

            st.divider()
            render_batch_results(all_results, edit_mode)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — SCAN RECEIPT
# ══════════════════════════════════════════════════════════════════════════════
with tab_scan:
    st.markdown("""
    <div style="margin-bottom:1.25rem">
      <div style="font-size:1.25rem;font-weight:700;color:#111827">Scan a receipt</div>
      <div style="font-size:0.82rem;color:#6B7280;margin-top:2px">
        Point your camera at any receipt or invoice — Claude reads it live.
      </div>
    </div>
    """, unsafe_allow_html=True)

    sc1, sc2 = st.columns([1, 1])
    with sc1:
        camera_image = st.camera_input("Take a photo",
            help="Works on mobile and desktop webcam.")
    with sc2:
        st.markdown("""
        **Tips for best results**
        - Good lighting, no shadows across text
        - Keep the whole document in frame
        - Avoid glare on glossy receipts
        - Works with thermal printer receipts
        """)
        if camera_image:
            # FIX 3: replace scan tab checkboxes with stateful toggle buttons
            if "scan_edit" not in st.session_state:
                st.session_state.scan_edit = False
            if "scan_save" not in st.session_state:
                st.session_state.scan_save = True
            se_bg  = "#EEF2FF" if st.session_state.scan_edit else "#F9FAFB"
            se_col = "#1A56E8" if st.session_state.scan_edit else "#6B7280"
            se_bd  = "#C7D2FE" if st.session_state.scan_edit else "#E5E7EB"
            st.markdown(f'<div style="background:{se_bg};border:1px solid {se_bd};border-radius:8px;'
                        f'padding:7px 12px;font-size:0.82rem;font-weight:600;color:{se_col};margin-bottom:4px">'
                        f'{"✏️ Edit mode: ON" if st.session_state.scan_edit else "✏️ Edit mode: OFF"}</div>',
                        unsafe_allow_html=True)
            if st.button("Toggle edit", key="scan_edit_btn", use_container_width=True):
                st.session_state.scan_edit = not st.session_state.scan_edit
                st.rerun()
            ss_bg  = "#DCFCE7" if st.session_state.scan_save else "#F9FAFB"
            ss_col = "#15803D" if st.session_state.scan_save else "#6B7280"
            ss_bd  = "#BBF7D0" if st.session_state.scan_save else "#E5E7EB"
            st.markdown(f'<div style="background:{ss_bg};border:1px solid {ss_bd};border-radius:8px;'
                        f'padding:7px 12px;font-size:0.82rem;font-weight:600;color:{ss_col};margin-bottom:4px">'
                        f'{"💾 Auto-save: ON" if st.session_state.scan_save else "💾 Auto-save: OFF"}</div>',
                        unsafe_allow_html=True)
            if st.button("Toggle save", key="scan_save_btn", use_container_width=True):
                st.session_state.scan_save = not st.session_state.scan_save
                st.rerun()
            scan_edit = st.session_state.scan_edit
            scan_save = st.session_state.scan_save
            do_extract = st.button("⚡ Extract from photo", type="primary", key="scan_btn")

    if camera_image and do_extract:
        with st.spinner("Reading receipt…"):
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
                if scan_edit:
                    data = render_invoice(data, editable=True, key_prefix="scan")
                    if st.button("💾 Confirm & Save scan", key="scan_confirm"):
                        if db_ok and scan_save:
                            try:
                                iid = save_invoice(data)
                                st.success(f"✓ Saved — DB ID #{iid}")
                            except Exception as e:
                                st.warning(f"Save failed: {e}")
                else:
                    data = render_invoice(data)
                    if db_ok and scan_save:
                        try:
                            iid = save_invoice(data)
                            st.success(f"✓ Saved — DB ID #{iid}")
                        except Exception as e:
                            st.warning(f"Save failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — HISTORY
# ══════════════════════════════════════════════════════════════════════════════
with tab_history:
    st.markdown("""
    <div style="margin-bottom:1.25rem">
      <div style="font-size:1.25rem;font-weight:700;color:#111827">Invoice history</div>
    </div>
    """, unsafe_allow_html=True)

    if not db_ok:
        st.error("Database not connected.")
        st.stop()

    with st.expander("🔍 Filter invoices", expanded=True):
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            f_vendor = st.text_input("Vendor name contains")
            f_conf   = st.selectbox("Confidence", ["", "high", "medium", "low"])
        with fc2:
            f_date_from = st.date_input("Date from", value=None)
            f_date_to   = st.date_input("Date to",   value=None)
        with fc3:
            f_min  = st.number_input("Min amount", value=0.0, step=100.0)
            f_max  = st.number_input("Max amount", value=0.0, step=100.0)
            f_risk = st.selectbox("Fraud risk", ["", "low", "medium", "high"])

    col_refresh, col_export = st.columns([1, 1])
    with col_refresh:
        if st.button("🔄 Refresh"):
            st.rerun()

    try:
        rows = get_all_invoices(
            vendor=f_vendor,
            date_from=str(f_date_from) if f_date_from else "",
            date_to=str(f_date_to) if f_date_to else "",
            min_amount=f_min if f_min > 0 else None,
            max_amount=f_max if f_max > 0 else None,
            confidence=f_conf,
            risk=f_risk,
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
                    file_name="trackbook_export.csv", mime="text/csv")

    if not rows:
        st.info("No invoices found.")
    else:
        st.caption(f"{len(rows)} invoice(s)")
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
                logo_b64 = display_data.get("_logo_b64")
                logo_bytes = _b64.b64decode(logo_b64) if logo_b64 else None
                vendor_name = display_data.get("vendor", {}).get("name") or ""
                if vendor_name:
                    st.markdown(
                        f'<div style="background:#EEF2FF;border:1px solid #C7D2FE;border-radius:8px;'
                        f'padding:8px 14px;font-size:0.82rem;color:#3730A3;margin-bottom:0.75rem">'
                        f'&#127970; Company detected: <strong>{vendor_name}</strong>'
                        f'</div>', unsafe_allow_html=True)
                render_invoice(display_data, inv_id, logo_bytes=logo_bytes)
            else:
                st.error(f"No invoice found with ID {inv_id}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
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

        import pandas as pd
        df = pd.DataFrame(summary)
        df["total_spend"] = df["total_spend"].astype(float)

        st.markdown('<div class="tb-section-head">Spend by vendor (top 15)</div>', unsafe_allow_html=True)
        chart_df = (df[["vendor_name", "total_spend"]]
                    .set_index("vendor_name")
                    .sort_values("total_spend", ascending=False)
                    .head(15))
        st.bar_chart(chart_df, use_container_width=True, height=280)

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
