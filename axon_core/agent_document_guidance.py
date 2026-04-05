from __future__ import annotations


def document_operator_guidance_block() -> str:
    return """
## Document Operator Patterns

When the user asks for operating plans, fundraising plans, board memos, execution playbooks, grounded briefs, or strategy docs:
- Prefer executable artifacts over vague summaries. Produce repo-ready Markdown, clear handoff structure, and concrete next actions.
- When a workspace already has `docs/` content, prefer writing the artifact into `docs/` with a specific filename and update the nearest docs index or README if one already exists.
- Use decision-friendly sections such as objective, operating model, offers, owners, KPIs, cadence, risks, assumptions, and a 30-60-90 day execution sequence when they fit the task.
- If the topic touches law, grants, tax, labour, procurement, compliance, or public programmes, ground claims in official or public-primary sources first and separate verified facts from your inferences.
- If you cannot verify a citation or source-backed claim, say so plainly instead of implying it is settled fact.
- When a strategy or document implies concrete follow-up work, convert that into missions or a small execution checklist.
"""
