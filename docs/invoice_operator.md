# Axon Invoice Operator

Axon can now act as a **document operator** for invoices. This module focuses on:

- Interactive invoice creation
- Memory-aware template reuse
- Professional output formats (Markdown, HTML, PDF)
- Share-ready payloads (email, WhatsApp, copy)

## Flow

1. User asks: "Create an invoice for Khanyisa Disability Centre"
2. Axon extracts what it can (client, amount, description)
3. Axon detects missing fields
4. Axon asks follow-up questions
5. Axon builds a structured draft
6. Axon renders preview (Markdown/HTML)
7. Axon offers export and share options

## Example Usage (Python)

```python
from document_engine import build_invoice_draft, missing_fields, follow_up_questions, render_markdown

draft = build_invoice_draft(
    prompt="Create invoice for Khanyisa Disability Centre for R1500",
    sender_profile={"business_name": "BkkinnovationHub"},
)

missing = missing_fields(draft)
if missing:
    questions = follow_up_questions(missing)
    print(questions)
else:
    print(render_markdown(draft))
```

## Memory Integration

Axon can use Resource Bank and Memory to:

- find prior invoice templates
- reuse branding
- reuse payment terms
- remember clients

Use helpers like:

- `memory_template_hints(resources, memories)`

## Exports

- `render_markdown(draft)`
- `render_html(draft)`
- `export_pdf_bytes(draft)` (requires reportlab)

## Share Payloads

Use `share_payloads(draft)` to generate:

- email subject/body
- WhatsApp text
- summary

## Database Tables

Call `ensure_document_tables_sql()` and execute statements to create:

- business_profiles
- clients
- documents
- invoices
- invoice_items
- document_exports
- document_shares

## Next Steps

- Wire endpoints in server.py
- Add UI preview panel
- Add "Create Invoice" action in Console
- Persist invoices per workspace
- Track invoice status (draft → sent → paid)

Axon is now capable of producing **real business outputs**, not just text.
