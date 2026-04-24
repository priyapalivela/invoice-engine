SYSTEM_PROMPT = """You are an expert invoice data extraction engine.
Your job is to extract structured data from invoices provided as images or PDFs.

Rules:
- Always respond with ONLY a valid JSON object — no explanation, no markdown, no backticks
- If a field is not found, set its value to null
- Never guess or hallucinate values — only extract what is explicitly present
- For amounts, always return numbers (not strings) without currency symbols
- For dates, always return in YYYY-MM-DD format
- For line_items, always return an array even if there is only one item
- Currency should be the 3-letter ISO code (e.g. USD, INR, EUR)
"""

USER_PROMPT = """Extract all invoice data from the provided document and return it
in this exact JSON structure:

{
  "vendor": {
    "name": "",
    "address": "",
    "email": null,
    "phone": null,
    "tax_id": null
  },
  "buyer": {
    "name": "",
    "address": null
  },
  "invoice_meta": {
    "invoice_number": "",
    "po_number": null,
    "invoice_date": "",
    "due_date": null,
    "terms": null,
    "currency": "USD"
  },
  "line_items": [
    {
      "description": "",
      "quantity": null,
      "unit_price": null,
      "tax": null,
      "amount": null
    }
  ],
  "totals": {
    "subtotal": null,
    "discount": null,
    "tax_total": null,
    "grand_total": null
  },
  "notes": null,
  "confidence": {
    "overall": "high | medium | low",
    "flagged_fields": []
  }
}
"""
