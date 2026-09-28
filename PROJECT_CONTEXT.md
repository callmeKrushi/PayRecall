# PayRecall — Project Context

Hack With Hyderabad 3.0 · Theme: "AI Agents That Learn Using Hindsight"

## 1. Project goal

Build a demo-ready AI collections agent whose recommendations for an overdue B2B invoice visibly change because of Hindsight memory of what worked and what backfired with that customer. Memory is the product, not a feature.

## 2. Target user

The accounts-receivable / collections specialist (or founder doing collections) at a B2B supplier with 50–500 customers. Framed for an Indian MSME; works generically.

## 3. Problem

- Collections knowledge is tacit and person-dependent: one customer pays only after a call to their AP head, another disputes anything with a firm tone, a third pays on the month-end run regardless.
- Dunning tools run fixed cadences and templates; they do not remember per-customer outcomes or backfires.
- When the collector leaves, the knowledge leaves with them.

## 4. Solution

PayRecall recommends, per overdue invoice, a concrete action (channel, recipient, tone, lever, timing) with a drafted message, citing the past interactions that justify it. After the user logs the customer's response, the outcome is retained in Hindsight and the next recommendation for that customer changes.

## 5. Core memory loop

Overdue invoice → recall customer history (Hindsight recall + reflect) → structured recommendation + draft → user takes action (mock send) → customer responds → outcome retained (agent action as experience fact, customer reply as world fact) → Hindsight consolidates observations and refreshes the customer playbook → next recommendation differs.

## 6. MVP features

1. Overdue-invoice queue (6 invoices, 5 customers) loaded from JSON.
2. Invoice detail with Memory ON/OFF toggle and "Recommend" button.
3. Side-by-side cards: recommendation without memory vs with memory.
4. Recommendation output: channel, recipient, tone, lever, suggested timing, rationale, confidence, supporting memories.
5. Drafted message + "Send (mock)" button.
6. Outcome form (reply text, resolution, date) → retain to Hindsight.
7. Memory panel per customer: observations, customer playbook (mental model), directives, raw recalled facts.
8. "Seed history" and "Reset bank" buttons; pre-seeded backup bank for the stage.

## 7. Hindsight's role

| Hindsight capability | Use in PayRecall |
|---|---|
| World facts | Customer profile, contacts, stated payment habits, customer replies verbatim |
| Experience facts | Every action the agent took and its outcome ("I sent a firm email on 12 Mar → dispute opened") |
| Observations (auto-consolidated) | Per-customer beliefs with proof counts: "emails to accounts@ ignored 0/4", "call to AP head → paid 3/3", "firm tone → dispute 1/1"; cross-customer patterns |
| Mental models | "Collections playbook: <customer>", refreshed after consolidation |
| Directives | Compliance rules: no legal threats before day 60; MSMED interest only after day 45; cite invoice number; no personal numbers |
| Disposition | Skepticism 4, empathy 3 |
| Recall (semantic + keyword + entity + temporal) | Customer-tagged recall for the transparency panel |
| Reflect with response_schema | Produces the structured recommendation with `based_on` citations |

Why not a table or plain RAG: outcomes arrive as free-text replies; beliefs must be extracted, consolidated, and revised with history (AP contact leaves); the agent's own actions are weighed differently from customer claims.

## 8. Data design (JSON, synthetic)

- `customers.json` — 5 customers: id, name, sector, contacts (name, role, channel), payment habits, MSME/Udyam flag.
  - 3 with rich history, 2 with little or none (fallback scenario).
- `invoices.json` — 6 overdue invoices: id, customer_id, amount, due_date, days_overdue, status.
- `history.json` — ~30 interaction records across 6 months for the 3 rich customers. Each: date, customer_id, invoice_id, actor (agent | customer), channel (email | whatsapp | call), content (narrative text), outcome (paid | partial | promise | dispute | ignored | none).
  - Includes emails ignored, a WhatsApp reply, call notes, a payment-plan honoured, a firm email that caused a dispute.
  - One contradiction event: AP head Ramesh leaves; new AP head Kavita.
- Seeding: `retain_batch` with backdated `timestamp`, `context` naming the speaker (agent vs customer), tags `customer:<id>`, `invoice:<id>`; then trigger consolidation and create one mental model per rich customer.

## 9. Agent behavior

- `recommend(invoice, memory_on)` returns a Pydantic `Decision`: channel, recipient, tone, lever, send_when, rationale, confidence, supporting_memories[]; plus `draft_message`.
- Memory OFF: single LLM call with invoice + basic customer profile only → generic recommendation.
- Memory ON: `recall(tags=customer)` for the panel; `reflect(query, response_schema=Decision, tags=customer)` for the decision; LLM drafts the message from the decision and citations.
- Lever options: none, early-payment discount, payment plan, MSMED 45-day / 43B(h) reminder to buyer's finance head, interest notice, ODR filing (gated by directives and days overdue).
- No history → follow directives and cross-customer observations, state low confidence.
- Outcome logging retains two items (agent action as experience, customer reply as world), triggers consolidation, refreshes the playbook.

## 10. Demo scenario (~3.5 min)

1. Memory OFF, Meridian Retail INV-2041 (₹4.2 lakh, 38 days): generic polite email to accounts@.
2. Seed 6 months of history; observation cards and playbook appear.
3. Memory ON, same invoice: WhatsApp then call to AP head Ramesh, friendly tone, no firm language, day-45 statutory heads-up queued; each element cites its memory. "Same invoice, same LLM, only memory differs."
4. Log outcome "paid 30 Sep" → observation proof count rises, playbook refreshes.
5. Log "Ramesh has left; new AP head Kavita" → belief superseded; next recommendation switches to Kavita with lower confidence.
6. New customer with no history → policy-driven default, low confidence.

## 11. Technology stack

Python 3.11 · Streamlit · hindsight-client (Hindsight Cloud bank) · one LLM API (Groq or Gemini free tier, Anthropic if key available) · Pydantic · pandas · python-dotenv · local JSON files.

## 12. Out of scope

Real email/WhatsApp sending, ERP integration, authentication, payment prediction, analytics dashboards, multi-user, extra databases, HydraDB, Rocketride.

## 13. Build milestones

| # | Milestone | Done when |
|---|---|---|
| 1 | Hindsight wrapper + bank config + directives | Retain/recall/reflect round-trip works from Python |
| 2 | Synthetic data + seed script | Observations and playbook visible for Meridian |
| 3 | Agent: Decision schema, OFF and ON paths, draft | Both paths return valid Decision for INV-2041 |
| 4 | Streamlit: queue, detail, toggle, side-by-side cards | Demo steps 1–3 run end to end |
| 5 | Outcome logging → retain → consolidation → panel refresh | Demo steps 4–5 run end to end |
| 6 | Fallback customer, reset/seed buttons, error handling | Demo step 6 runs; two full rehearsals |
| 7 | README, backup video, pitch text | Ready to present |
