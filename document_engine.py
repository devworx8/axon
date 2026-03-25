"""Axon Document Operator foundation.

This module provides a local-first invoice engine that can:
- detect missing invoice fields
- ask follow-up questions
- reuse template hints from memory/resources
- render polished markdown and HTML
- prepare share/export payloads

It is intentionally framework-light so it can be wired into FastAPI, CLI tools,
or future agent workflows without dragging UI concerns into the core logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import html
import io
import json
import re
from typing import Any, Iterable

CURRENCY_SYMBOLS = {
    "ZAR": "R",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
}


@dataclass
class InvoiceLineItem:
    description: str
    quantity: float = 1.0
    unit_price: float = 0.0
    tax_rate: float = 0.0

    @property
    def line_total(self) -> float:
        subtotal = float(self.quantity) * float(self.unit_price)
        tax = subtotal * float(self.tax_rate)
        return round(subtotal + tax, 2)


@dataclass
class InvoiceDraft:
    sender_name: str = ""
    sender_email: str = ""
    sender_phone: str = ""
    sender_address: str = ""
    sender_bank_name: str = ""
    sender_account_name: str = ""
    sender_account_number: str = ""
    sender_branch_code: str = ""
    sender_tax_number: str = ""
    invoice_number: str = ""
    invoice_date: str = ""
    due_date: str = ""
    currency: str = "ZAR"
    client_name: str = ""
    client_contact: str = ""
    client_email: str = ""
    client_phone: str = ""
    client_address: str = ""
    reference: str = ""
    payment_terms: str = "Payment due within 7 days"
    notes: str = "Thank you for your business."
    workspace_name: str = ""
    items: list[InvoiceLineItem] = field(default_factory=list)

    @property
    def subtotal(self) -> float:
        return round(sum(float(item.quantity) * float(item.unit_price) for item in self.items), 2)

    @property
    def tax_amount(self) -> float:
        return round(sum((float(item.quantity) * float(item.unit_price)) * float(item.tax_rate) for item in self.items), 2)

    @property
    def total(self) -> float:
        return round(self.subtotal + self.tax_amount, 2)


REQUIRED_FIELDS = {
    "sender_name": "What business or sender name should appear on the invoice?",
    "client_name": "Who is the invoice for?",
    "invoice_number": "What invoice number should I use?",
    "invoice_date": "What invoice date should I use?",
    "due_date": "What due date should I use?",
    "items": "What should the invoice include as line items, quantities, and prices?",
}


def today_iso() -> str:
    return date.today().isoformat()


def default_due_date(days: int = 7) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def money(value: float, currency: str = "ZAR") -> str:
    symbol = CURRENCY_SYMBOLS.get((currency or "ZAR").upper(), (currency or "ZAR").upper() + " ")
    return f"{symbol}{float(value):,.2f}"


def normalize_invoice_number(raw: str | None, *, prefix: str = "INV", when: str | None = None) -> str:
    value = str(raw or "").strip()
    if value:
        return value
    day = (when or today_iso()).replace("-", "")
    return f"{prefix}-{day}-001"


def parse_amount(text: str) -> float | None:
    if not text:
        return None
    match = re.search(r"(?:R|ZAR\s*)?([0-9]{1,3}(?:[ ,][0-9]{3})*(?:\.[0-9]{2})|[0-9]+(?:\.[0-9]{2})?)", text, re.I)
    if not match:
        return None
    raw = match.group(1).replace(" ", "").replace(",", "")
    try:
        return round(float(raw), 2)
    except Exception:
        return None


def extract_invoice_seed(message: str) -> dict[str, Any]:
    text = str(message or "").strip()
    amount = parse_amount(text)
    lower = text.lower()
    client_name = ""
    for marker in ("for ", "to ", "made to ", "bill "):
        if marker in lower:
            segment = text[lower.index(marker) + len(marker):]
            segment = re.split(r"(?: for | with | due | amount | of )", segment, maxsplit=1, flags=re.I)[0]
            client_name = segment.strip(" .,:;-\n\t")
            break
    description = ""
    if "invoice" in lower:
        description = re.sub(r".*invoice", "", text, flags=re.I).strip(" :,-")
    return {
        "client_name": client_name,
        "amount": amount,
        "description": description,
        "currency": "ZAR" if "r" in lower or "zar" in lower or "south africa" in lower else "ZAR",
    }


def build_invoice_draft(
    *,
    prompt: str,
    sender_profile: dict[str, Any] | None = None,
    client_profile: dict[str, Any] | None = None,
    workspace_name: str = "",
    line_items: Iterable[dict[str, Any]] | None = None,
    defaults: dict[str, Any] | None = None,
) -> InvoiceDraft:
    seed = extract_invoice_seed(prompt)
    sender_profile = sender_profile or {}
    client_profile = client_profile or {}
    defaults = defaults or {}
    items: list[InvoiceLineItem] = []
    if line_items:
        for item in line_items:
            items.append(
                InvoiceLineItem(
                    description=str(item.get("description") or item.get("title") or "Service"),
                    quantity=float(item.get("quantity") or 1),
                    unit_price=float(item.get("unit_price") or item.get("price") or 0),
                    tax_rate=float(item.get("tax_rate") or 0),
                )
            )
    elif seed.get("amount") is not None:
        items.append(
            InvoiceLineItem(
                description=seed.get("description") or workspace_name or defaults.get("default_description") or "Professional services",
                quantity=1,
                unit_price=float(seed["amount"]),
                tax_rate=float(defaults.get("default_tax_rate") or 0),
            )
        )

    when = str(defaults.get("invoice_date") or today_iso())
    draft = InvoiceDraft(
        sender_name=str(sender_profile.get("business_name") or sender_profile.get("name") or defaults.get("business_name") or ""),
        sender_email=str(sender_profile.get("email") or ""),
        sender_phone=str(sender_profile.get("phone") or ""),
        sender_address=str(sender_profile.get("address") or ""),
        sender_bank_name=str(sender_profile.get("bank_name") or ""),
        sender_account_name=str(sender_profile.get("account_name") or sender_profile.get("business_name") or ""),
        sender_account_number=str(sender_profile.get("account_number") or ""),
        sender_branch_code=str(sender_profile.get("branch_code") or ""),
        sender_tax_number=str(sender_profile.get("tax_number") or ""),
        invoice_number=normalize_invoice_number(defaults.get("invoice_number"), prefix=str(defaults.get("invoice_prefix") or "INV"), when=when),
        invoice_date=when,
        due_date=str(defaults.get("due_date") or default_due_date(int(defaults.get("payment_days") or 7))),
        currency=str(defaults.get("currency") or seed.get("currency") or "ZAR"),
        client_name=str(client_profile.get("name") or seed.get("client_name") or ""),
        client_contact=str(client_profile.get("contact_person") or ""),
        client_email=str(client_profile.get("email") or ""),
        client_phone=str(client_profile.get("phone") or ""),
        client_address=str(client_profile.get("address") or ""),
        reference=str(defaults.get("reference") or ""),
        payment_terms=str(defaults.get("payment_terms") or client_profile.get("default_terms") or "Payment due within 7 days"),
        notes=str(defaults.get("notes") or "Thank you for your business."),
        workspace_name=workspace_name,
        items=items,
    )
    return draft


def missing_fields(draft: InvoiceDraft) -> list[str]:
    missing: list[str] = []
    if not draft.sender_name:
        missing.append("sender_name")
    if not draft.client_name:
        missing.append("client_name")
    if not draft.invoice_number:
        missing.append("invoice_number")
    if not draft.invoice_date:
        missing.append("invoice_date")
    if not draft.due_date:
        missing.append("due_date")
    if not draft.items:
        missing.append("items")
    return missing


def follow_up_questions(fields: Iterable[str]) -> list[str]:
    return [REQUIRED_FIELDS[field] for field in fields if field in REQUIRED_FIELDS]


def invoice_to_payload(draft: InvoiceDraft) -> dict[str, Any]:
    return {
        "sender": {
            "name": draft.sender_name,
            "email": draft.sender_email,
            "phone": draft.sender_phone,
            "address": draft.sender_address,
            "bank_name": draft.sender_bank_name,
            "account_name": draft.sender_account_name,
            "account_number": draft.sender_account_number,
            "branch_code": draft.sender_branch_code,
            "tax_number": draft.sender_tax_number,
        },
        "client": {
            "name": draft.client_name,
            "contact": draft.client_contact,
            "email": draft.client_email,
            "phone": draft.client_phone,
            "address": draft.client_address,
        },
        "invoice_number": draft.invoice_number,
        "invoice_date": draft.invoice_date,
        "due_date": draft.due_date,
        "currency": draft.currency,
        "reference": draft.reference,
        "payment_terms": draft.payment_terms,
        "notes": draft.notes,
        "workspace_name": draft.workspace_name,
        "subtotal": draft.subtotal,
        "tax_amount": draft.tax_amount,
        "total": draft.total,
        "items": [
            {
                "description": item.description,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "tax_rate": item.tax_rate,
                "line_total": item.line_total,
            }
            for item in draft.items
        ],
    }


def render_markdown(draft: InvoiceDraft) -> str:
    lines = [
        "# 🧾 INVOICE",
        "",
        f"**Invoice Number:** {draft.invoice_number}",
        f"**Invoice Date:** {draft.invoice_date}",
        f"**Due Date:** {draft.due_date}",
        "",
        "## From",
        f"**{draft.sender_name or '[Sender Name]'}**",
    ]
    for value in (draft.sender_address, draft.sender_email, draft.sender_phone):
        if value:
            lines.append(value)
    if draft.sender_tax_number:
        lines.append(f"Tax Number: {draft.sender_tax_number}")
    lines.extend(["", "## Bill To", f"**{draft.client_name or '[Client Name]'}**"])
    for value in (draft.client_contact, draft.client_address, draft.client_email, draft.client_phone):
        if value:
            lines.append(value)
    lines.extend(["", "## Services", "", "| Description | Qty | Unit Price | Total |", "|---|---:|---:|---:|"])
    for item in draft.items:
        lines.append(
            f"| {item.description} | {item.quantity:g} | {money(item.unit_price, draft.currency)} | {money(item.line_total, draft.currency)} |"
        )
    lines.extend([
        "",
        f"**Subtotal:** {money(draft.subtotal, draft.currency)}",
        f"**Tax:** {money(draft.tax_amount, draft.currency)}",
        f"**Total Due:** **{money(draft.total, draft.currency)}**",
        "",
        "## Payment Details",
        f"**Bank:** {draft.sender_bank_name or '[Bank Name]'}",
        f"**Account Name:** {draft.sender_account_name or draft.sender_name or '[Account Name]'}",
        f"**Account Number:** {draft.sender_account_number or '[Account Number]'}",
        f"**Branch Code:** {draft.sender_branch_code or '[Branch Code]'}",
        f"**Reference:** {draft.reference or draft.invoice_number}",
        "",
        "## Notes",
        draft.notes or draft.payment_terms,
        "",
        "Thank you for your business.",
    ])
    return "\n".join(lines)


def render_html(draft: InvoiceDraft) -> str:
    rows = []
    for item in draft.items:
        rows.append(
            f"<tr><td>{html.escape(item.description)}</td><td>{item.quantity:g}</td><td>{html.escape(money(item.unit_price, draft.currency))}</td><td>{html.escape(money(item.line_total, draft.currency))}</td></tr>"
        )
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
<title>Invoice {html.escape(draft.invoice_number)}</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 0; padding: 32px; color: #111827; background: #f8fafc; }}
.sheet {{ max-width: 960px; margin: 0 auto; background: white; border: 1px solid #e5e7eb; border-radius: 20px; padding: 32px; }}
.header {{ display: flex; justify-content: space-between; gap: 24px; margin-bottom: 28px; }}
.muted {{ color: #6b7280; font-size: 13px; }}
h1 {{ margin: 0 0 8px; font-size: 34px; }}
.block h3 {{ margin: 0 0 8px; font-size: 14px; text-transform: uppercase; letter-spacing: .08em; color: #6b7280; }}
.block p {{ margin: 0 0 4px; line-height: 1.45; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 24px; }}
th, td {{ border-bottom: 1px solid #e5e7eb; padding: 12px; text-align: left; font-size: 14px; }}
th {{ color: #6b7280; font-weight: 600; }}
.summary {{ margin-top: 24px; margin-left: auto; width: 320px; }}
.summary div {{ display: flex; justify-content: space-between; padding: 8px 0; }}
.total {{ font-weight: 700; font-size: 18px; border-top: 2px solid #111827; margin-top: 8px; padding-top: 12px; }}
.notes {{ margin-top: 28px; padding: 16px; background: #f8fafc; border-radius: 14px; }}
</style>
</head>
<body>
<div class=\"sheet\">
  <div class=\"header\">
    <div>
      <h1>Invoice</h1>
      <div class=\"muted\">{html.escape(draft.invoice_number)}</div>
    </div>
    <div class=\"block\">
      <h3>Invoice Details</h3>
      <p><strong>Date:</strong> {html.escape(draft.invoice_date)}</p>
      <p><strong>Due:</strong> {html.escape(draft.due_date)}</p>
      <p><strong>Reference:</strong> {html.escape(draft.reference or draft.invoice_number)}</p>
    </div>
  </div>
  <div class=\"header\">
    <div class=\"block\">
      <h3>From</h3>
      <p><strong>{html.escape(draft.sender_name or '[Sender Name]')}</strong></p>
      <p>{html.escape(draft.sender_address)}</p>
      <p>{html.escape(draft.sender_email)}</p>
      <p>{html.escape(draft.sender_phone)}</p>
    </div>
    <div class=\"block\">
      <h3>Bill To</h3>
      <p><strong>{html.escape(draft.client_name or '[Client Name]')}</strong></p>
      <p>{html.escape(draft.client_contact)}</p>
      <p>{html.escape(draft.client_address)}</p>
      <p>{html.escape(draft.client_email)}</p>
      <p>{html.escape(draft.client_phone)}</p>
    </div>
  </div>
  <table>
    <thead>
      <tr><th>Description</th><th>Qty</th><th>Unit Price</th><th>Total</th></tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
  <div class=\"summary\">
    <div><span>Subtotal</span><strong>{html.escape(money(draft.subtotal, draft.currency))}</strong></div>
    <div><span>Tax</span><strong>{html.escape(money(draft.tax_amount, draft.currency))}</strong></div>
    <div class=\"total\"><span>Total Due</span><strong>{html.escape(money(draft.total, draft.currency))}</strong></div>
  </div>
  <div class=\"notes\">
    <strong>Payment Details</strong><br />
    {html.escape(draft.sender_bank_name or '[Bank Name]')} · {html.escape(draft.sender_account_name or draft.sender_name or '[Account Name]')} · {html.escape(draft.sender_account_number or '[Account Number]')} · Ref: {html.escape(draft.reference or draft.invoice_number)}
    <br /><br />
    <strong>Notes</strong><br />
    {html.escape(draft.notes or draft.payment_terms)}
  </div>
</div>
</body>
</html>"""


def share_payloads(draft: InvoiceDraft) -> dict[str, str]:
    summary = f"Invoice {draft.invoice_number} for {draft.client_name}: {money(draft.total, draft.currency)} due {draft.due_date}."
    email_subject = f"Invoice {draft.invoice_number} — {draft.sender_name or 'Axon'}"
    email_body = f"Hello {draft.client_name},\n\nPlease find attached invoice {draft.invoice_number} for {money(draft.total, draft.currency)}. Payment is due by {draft.due_date}.\n\nKind regards,\n{draft.sender_name or 'Axon'}"
    whatsapp = f"Hello {draft.client_name}, here is invoice {draft.invoice_number} for {money(draft.total, draft.currency)} due {draft.due_date}."
    return {
        "summary": summary,
        "email_subject": email_subject,
        "email_body": email_body,
        "whatsapp_text": whatsapp,
    }


def memory_template_hints(resources: Iterable[dict[str, Any]], memories: Iterable[dict[str, Any]]) -> list[str]:
    hints: list[str] = []
    for item in resources:
        title = str(item.get("title") or "").strip()
        if title:
            hints.append(f"Resource template candidate: {title}")
    for item in memories:
        title = str(item.get("title") or item.get("summary") or "").strip()
        if title:
            hints.append(f"Memory hint: {title}")
    deduped: list[str] = []
    for hint in hints:
        if hint not in deduped:
            deduped.append(hint)
    return deduped[:8]


def export_pdf_bytes(draft: InvoiceDraft) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except Exception as exc:  # pragma: no cover - optional dependency path
        raise RuntimeError("reportlab is required for PDF export") from exc

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 24 * mm
    c.setFont("Helvetica-Bold", 20)
    c.drawString(20 * mm, y, "INVOICE")
    c.setFont("Helvetica", 10)
    y -= 8 * mm
    for line in [
        f"Invoice Number: {draft.invoice_number}",
        f"Invoice Date: {draft.invoice_date}",
        f"Due Date: {draft.due_date}",
        "",
        f"From: {draft.sender_name}",
        draft.sender_address,
        draft.sender_email,
        draft.sender_phone,
        "",
        f"Bill To: {draft.client_name}",
        draft.client_address,
        draft.client_email,
        draft.client_phone,
        "",
    ]:
        c.drawString(20 * mm, y, line)
        y -= 5 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Description")
    c.drawString(110 * mm, y, "Qty")
    c.drawString(130 * mm, y, "Unit")
    c.drawString(165 * mm, y, "Total")
    y -= 4 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    for item in draft.items:
        c.drawString(20 * mm, y, item.description[:50])
        c.drawRightString(125 * mm, y, f"{item.quantity:g}")
        c.drawRightString(155 * mm, y, money(item.unit_price, draft.currency))
        c.drawRightString(190 * mm, y, money(item.line_total, draft.currency))
        y -= 6 * mm
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(190 * mm, y, f"Total Due: {money(draft.total, draft.currency)}")
    y -= 10 * mm
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, y, f"Payment reference: {draft.reference or draft.invoice_number}")
    y -= 5 * mm
    c.drawString(20 * mm, y, f"Notes: {draft.notes}")
    c.showPage()
    c.save()
    return buffer.getvalue()


def ensure_document_tables_sql() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS business_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            address TEXT DEFAULT '',
            tax_number TEXT DEFAULT '',
            bank_name TEXT DEFAULT '',
            account_name TEXT DEFAULT '',
            account_number TEXT DEFAULT '',
            branch_code TEXT DEFAULT '',
            invoice_prefix TEXT DEFAULT 'INV',
            default_currency TEXT DEFAULT 'ZAR',
            default_payment_terms TEXT DEFAULT 'Payment due within 7 days',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            contact_person TEXT DEFAULT '',
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            address TEXT DEFAULT '',
            default_terms TEXT DEFAULT '',
            currency TEXT DEFAULT 'ZAR',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'draft',
            workspace_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
            client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
            meta_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            invoice_number TEXT NOT NULL,
            invoice_date TEXT NOT NULL,
            due_date TEXT NOT NULL,
            currency TEXT DEFAULT 'ZAR',
            subtotal REAL DEFAULT 0,
            tax_amount REAL DEFAULT 0,
            total_amount REAL DEFAULT 0,
            payment_terms TEXT DEFAULT '',
            payment_reference TEXT DEFAULT '',
            sender_profile_json TEXT DEFAULT '{}',
            client_snapshot_json TEXT DEFAULT '{}',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
            description TEXT NOT NULL,
            quantity REAL DEFAULT 1,
            unit_price REAL DEFAULT 0,
            tax_rate REAL DEFAULT 0,
            line_total REAL DEFAULT 0,
            sort_order INTEGER DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS document_exports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            format TEXT NOT NULL,
            file_path TEXT DEFAULT '',
            size_bytes INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS document_shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            share_type TEXT NOT NULL,
            target TEXT DEFAULT '',
            status TEXT DEFAULT 'prepared',
            meta_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now'))
        )
        """,
    ]
