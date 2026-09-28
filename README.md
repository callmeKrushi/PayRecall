# PayRecall

AI collections agent for B2B accounts receivable that remembers, per customer, which collection approaches worked or backfired (via Hindsight persistent memory) and changes its next recommendation accordingly.

## Current MVP status

Project scaffold only. No functionality implemented yet.

- `app.py` — Streamlit UI (placeholder)
- `agent.py` — recommendation agent (placeholder)
- `hindsight_memory.py` — Hindsight memory wrapper (placeholder)
- `data/customers.json` — synthetic customer data (empty)
- `PROJECT_CONTEXT.md` — full project context, demo scenario and build milestones

## Setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then fill in the keys
```
