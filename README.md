# PayRecall

PayRecall is a memory-powered collections assistant for B2B accounts receivable: it remembers what happened with each customer, learns from every logged outcome, and changes its next recommended action accordingly.

Built for Hack With Hyderabad 3.0 (theme: "AI Agents That Learn Using Hindsight").

## Problem

Collections teams chase the same customers month after month, but the context that decides whether a chase works is rarely written down and is easily lost:

- Which channel this customer actually responds to (a shared inbox that nobody reads, a WhatsApp number, a phone call).
- Who the right person is today, and whether the person you dealt with last quarter has left.
- Which tactics worked (a friendly call, an instalment plan) and which backfired (a firm notice that triggered a dispute).
- What the customer promised, disputed, or partially paid, and when.

Dunning tools run fixed cadences and templates. A plain LLM prompt sees only the invoice in front of it. When the collector who knew the account leaves, the knowledge leaves with them.

## Solution

PayRecall recommends the next collection action for one overdue invoice: who to contact, on which channel, in what tone, when, with what approach, and why. It runs the same invoice through two paths so the effect of memory is visible.

```
MEMORY OFF
  invoice + basic customer profile
  -> Groq LLM
  -> generic recommendation

MEMORY ON
  invoice + basic customer profile
  + Hindsight recall (customer-scoped memories and observations)
  + Hindsight customer playbook (mental model)
  + Hindsight reflect (evidence-based assessment)
  -> Groq LLM
  -> personalized recommendation with cited memories
```

The LLM, prompt structure, and invoice are identical in both paths. Only the memory input differs.

## Why Memory Matters

A one-shot prompt can only reason from what is in the prompt. It cannot know that emails to this customer's shared inbox have been ignored five times, that a firm notice caused a dispute three weeks ago, or that the accounts-payable head changed last week. It will produce a reasonable-sounding generic reminder every time.

Representative output for Meridian Retail, invoice INV-2041 (Rs 4,20,000, 38 days overdue), as produced by the current implementation. Exact wording varies between runs because the LLM is non-deterministic.

| | MEMORY OFF | MEMORY ON |
|---|---|---|
| Recipient | Kavita Menon (email address) | Kavita Menon |
| Channel | Email | Call |
| Tone | Polite | Friendly |
| Timing | Next business morning | Tuesday or Thursday after 3 pm, her stated call window |
| Approach | Standard reminder asking for payment within a few days | Reference the 24 Sep introduction email, confirm she has the ledger, ask for a payment date |
| Confidence | 40% | 85 to 93% |
| Evidence | None | Cited memories: emails to the shared inbox ignored, calls to the AP head produced payment, firm notice caused a dispute, Ramesh Iyer left, Kavita Menon's stated preferences |

What changed because of memory: the channel (email to call), the tone (polite to friendly, with firm language explicitly avoided), the timing (a real availability window), and the confidence. The memory-on path also knows the previous contact has left and that the new contact does not use WhatsApp.

## Live Learning

The learning loop is implemented in the UI and runs against the live Hindsight bank:

```
MEMORY ON recommendation
  -> collection action happens
  -> user logs the customer outcome (reply text, resolution, date)
  -> Hindsight retain: agent action stored as an experience, customer reply stored as a world fact
  -> Hindsight extracts memories from the new documents (polled until retrievable)
  -> customer playbook refreshed from memory
  -> MEMORY ON recommendation regenerated
  -> BEFORE vs AFTER comparison with the changed fields highlighted
```

The "Log Customer Outcome" form appears under every MEMORY ON recommendation. After submission the UI shows the recorded outcome, the new Hindsight document ids, the facts extracted from them, the refreshed playbook, and the updated recommendation. Duplicate submissions of the same outcome are blocked.

## Hindsight Usage

All Hindsight calls live in `hindsight_memory.py`. The table lists what is actually used and what each capability contributes.

| Capability | How PayRecall uses it | Contribution |
|---|---|---|
| Retain | `retain_batch` seeds 35 historical interactions as separate documents with deterministic ids. `retain` stores each live outcome as two documents: the agent's action and the customer's reply. | Narrative history and new outcomes become memory without any schema design. Seeding is idempotent. |
| Recall | `recall` with the tag `customer:<id>` and `tags_match="all_strict"`. Observations are ranked first, then raw facts. | Supplies the evidence list the LLM reasons over and cites. |
| Reflect | `reflect` scoped to the same customer tag with `include_facts=True`, retried once. | Produces an evidence-based assessment that is fed to the LLM alongside the raw memories. |
| Observations | Bank configured with an observations mission focused on collection patterns; the observation layer was rebuilt under it. Hindsight consolidates automatically after each retain. | Turns individual events into beliefs such as "shared-inbox emails are ignored" or "firm notices cause disputes". |
| Mental model (customer playbook) | One mental model per customer, generated by Hindsight from a source query covering channels, contacts, tones, timing, recent changes, and evidence. Set to refresh after consolidation and refreshed explicitly after each logged outcome. | A readable per-customer playbook shown in the UI and given to the LLM. |
| Bank configuration | Reflect mission and disposition (skepticism 4, literalism 4, empathy 3) set through the bank config API. | Keeps reflect factual, cautious, and unwilling to invent preferences. |
| Customer-scoped tags | Every memory carries `customer:<id>`, `invoice:<id>`, `channel:<x>`, `actor:<agent or customer>`, and `outcome:<x>` tags plus metadata. | Strict tag matching means one customer's history never influences another's recommendation. |
| Evidence references | Each recalled memory is given a short id (M1, M2, ...) in the prompt. The LLM cites the ids it used; the UI shows those memories. | Every recommendation is traceable to specific remembered events. |
| Playbook refresh | `refresh_mental_model` after new outcomes, with the operation polled to completion. | The learned playbook stays current as outcomes arrive. |

Not implemented: Hindsight directives. The original plan listed compliance directives, but none were created.

## Architecture

```
User
 |
 v
Streamlit UI (app.py)
 |
 v
PayRecall Agent (agent.py)
 |                  \
 v                   v
Groq LLM        Hindsight (hindsight_memory.py)
                     |
                     v
          Memories / Observations
                     |
                     v
            Customer Playbook
                     |
                     v
         Personalized Action (cited)
```

Live learning loop:

```
Recommendation --> Action --> Logged outcome --> Hindsight retain
      ^                                              |
      |                                              v
Updated recommendation <-- Playbook refresh <-- Memory extraction
```

## Features

- Customer selection
- Overdue invoice selection, filtered by customer
- MEMORY OFF recommendation (generic, Hindsight never called)
- MEMORY ON recommendation (personalized, with cited memories)
- Side-by-side comparison of both paths for the same invoice, with a dynamic "what changed because of memory" table
- Supporting memory evidence with reference ids, type, and date
- Learned customer playbook (Hindsight mental model)
- Live outcome logging with retain, playbook refresh, and regeneration
- Before/after learning comparison, including confidence
- Confidence score, capped when no evidence exists
- Error handling with user-friendly messages for missing credentials, unknown customer or invoice, memory failures, and LLM failures
- Customer memory isolation through strict tag matching

## Tech Stack

| Component | Technology | Version used |
|---|---|---|
| Language | Python | 3.11 |
| UI | Streamlit | 1.64 |
| Memory | Hindsight Cloud via `hindsight-client` | 0.10.1 |
| LLM | Groq, model `openai/gpt-oss-120b` by default | `groq` SDK 1.7 |
| Configuration | python-dotenv | 1.2 |

The Groq model is configurable through the `GROQ_MODEL` environment variable.

## Project Structure

| Path | Purpose |
|---|---|
| `app.py` | Streamlit demo: selectors, recommendation views, comparison, outcome logging, learning view. |
| `agent.py` | Decision agent: MEMORY OFF and MEMORY ON paths, Groq calls, structured `Recommendation`, error types, CLI demo. |
| `hindsight_memory.py` | All Hindsight integration: configuration, client lifecycle, retain, recall, reflect, seeding, bank configuration, observations rebuild, customer playbooks. |
| `data/customers.json` | Synthetic dataset: customers, invoices, interaction history. |
| `requirements.txt` | Python dependencies. |
| `.env.example` | Template for environment variables. |
| `PROJECT_CONTEXT.md` | Original project brief, demo scenario, and build milestones. Some planned items differ from what was built; this README is authoritative. |
| `research_report.md` | Pre-hackathon research on the problem space and Hindsight. |

## Dataset

All data is fictional and exists only for demonstration. Company names, people, email addresses, and phone numbers do not refer to real entities.

- 5 B2B customers with contacts, roles, known channels, and notes
- 6 overdue invoices
- 35 narrative interaction records covering April to September 2026
- Emails, WhatsApp messages, call notes, payment events, and customer replies
- Promises to pay, an honoured instalment plan, a goods dispute with a partial payment, ignored reminders, and a firm email that caused a dispute
- One customer contact change: the accounts-payable head leaves and a new one takes over
- Two customers with little or no history, to show low-confidence behaviour

Meridian Retail is the primary demo customer with the richest history.

## Setup

Windows (PowerShell or Command Prompt):

```
git clone <repo>
cd payrecall
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and fill in your own values. Never commit this file; it is already ignored by `.gitignore`.

| Variable | Required | Description |
|---|---|---|
| `HINDSIGHT_API_KEY` | Yes | Hindsight Cloud API key. |
| `HINDSIGHT_BANK_ID` | Yes | Memory bank id to use, for example `payrecall`. |
| `HINDSIGHT_BASE_URL` | No | Hindsight API base URL. Defaults to `https://api.hindsight.vectorize.io`. |
| `GROQ_API_KEY` or `LLM_API_KEY` | Yes (one of them) | Groq API key. The code reads `GROQ_API_KEY` first and falls back to `LLM_API_KEY`. |
| `GROQ_MODEL` | No | Groq model id. Defaults to `openai/gpt-oss-120b`. |

Example `.env` with placeholders:

```
HINDSIGHT_API_KEY=your-hindsight-key
HINDSIGHT_BANK_ID=payrecall
LLM_API_KEY=your-groq-key
```

## Initialize Hindsight

The bank is prepared with functions from `hindsight_memory.py`. There is no separate setup script; run these from the activated virtual environment inside the project folder.

Check the connection (prints no secrets):

```
python -c "import hindsight_memory as hm; print(hm.initialize_memory())"
```

Seed the synthetic history. This is idempotent: each interaction maps to a fixed document id, so running it again sends nothing new.

```
python -c "import hindsight_memory as hm; print(hm.seed_customer_history())"
```

Apply the observations mission, reflect mission, and disposition, then rebuild the observation layer under that mission:

```
python -c "import hindsight_memory as hm; hm.configure_bank(); print(hm.rebuild_observations())"
```

Create the customer playbook for the demo customer (Hindsight generates the content from memory):

```
python -c "import hindsight_memory as hm; print(hm.ensure_customer_playbook('CUST-001'))"
```

Playbooks for other customers can be created the same way with their ids (`CUST-002` to `CUST-005`). Customers with no history produce an empty playbook.

Optional CLI check that both agent paths work for the demo invoice:

```
python agent.py INV-2041
```

## Run

```
streamlit run app.py
```

The browser opens on the PayRecall page. The sidebar has the customer selector, the invoice selector filtered to that customer, and the MEMORY OFF / MEMORY ON switch. The main area shows the selected invoice, a "Generate Recommendation" button, and a "Compare OFF vs ON" button. Each recommendation takes a few seconds; the comparison runs both paths and takes roughly 20 to 30 seconds.

## Demo Flow

About 60 to 90 seconds:

1. Select **Meridian Retail** in the sidebar.
2. Select invoice **INV-2041** (Rs 4,20,000, 38 days overdue).
3. Click **Compare OFF vs ON**. Both recommendations appear side by side: the generic one on the left with the "memory OFF" badge, the personalized one on the right with the "memory ON" badge.
4. Read the "What changed because of memory?" table: channel, recipient, tone, timing, and approach are compared field by field, and the confidence change is shown.
5. On the right, point to "What PayRecall remembered": the cited memories with reference ids and dates. Open the "Learned customer playbook" expander to show the Hindsight mental model.
6. Scroll to **Log Customer Outcome**. Enter a realistic reply, for example that Kavita confirmed payment for a specific date after the call, choose "Promise to Pay", and submit.
7. PayRecall retains the action and the reply, shows the new document ids and the facts Hindsight extracted from them, and refreshes the playbook.
8. The **BEFORE LEARNING / AFTER LEARNING** panels show the previous and updated recommendation, with the changed fields and confidence highlighted.

## Testing

The following checks were run during development. They are scripted checks, not a committed test suite.

| Check | What it covers |
|---|---|
| Python compilation | `python -m py_compile app.py agent.py hindsight_memory.py` |
| Streamlit AppTest | Starts the app, switches customers, verifies invoice filtering, runs MEMORY OFF, MEMORY ON, and the comparison, and confirms no `.env` key values appear in rendered output. |
| Live learning AppTest | Runs MEMORY ON, submits an outcome, verifies two documents are retained, new memories are shown, BEFORE and AFTER render, changed fields are reported, and the duplicate-submit guard fires. Test documents are deleted afterwards. |
| Agent regression | `python agent.py INV-2041` for both paths, plus the new-customer path (`INV-2062`). |
| Customer isolation | Meridian recall returns only Meridian-tagged memories, a Nova recall with a Meridian-specific query returns no Meridian content, and an unknown customer id returns nothing. |
| Error paths | Missing Groq key, missing Hindsight credentials, unknown customer, unknown invoice, invoice belonging to another customer, and a recall failure each raise the intended typed error. |

## Hindsight Memory Design

- **Customer tags.** Every memory is tagged `customer:<id>` plus invoice, channel, actor, and outcome tags, and carries metadata with the contact, date, and tone.
- **Strict matching.** Recall and reflect use `tags_match="all_strict"`, so untagged memories and other customers' memories are excluded. The comparison and learning views are generic; nothing is keyed to a specific customer.
- **Experience and world facts.** Agent actions are retained with the agent as the actor and become experience facts ("we sent a firm email, outcome: dispute"). Customer replies and payments are retained with the customer as the actor and become world facts. Hindsight stores them as distinct fact types, and both appear in recall results with their type.
- **Observations.** Hindsight consolidates facts into observations under a mission that asks for reliable per-customer patterns across channels, contacts, tones, timing, and approaches, preserving contradictions and counting successes and failures. Observations are ranked first in the evidence list.
- **Mental model.** The customer playbook is generated by Hindsight from a source query, refreshed after consolidation and after each logged outcome, and shown verbatim in the UI. Nothing in it is hand-written.
- **Evidence references.** Recalled memories are numbered in the prompt; the LLM returns the ids it relied on; the UI renders exactly those memories. Reflect's own source facts are merged into the same list.
- **Newer versus older information.** The observations mission and the prompt both instruct that recent evidence overrides older evidence. In the seeded data the playbook marks the previous contact as former, marks WhatsApp as obsolete, and names the current contact and her stated preferences, while the older beliefs remain in memory as history.

## Limitations

- All data is synthetic. No real customer, invoice, or payment data is involved.
- No accounting or ERP integration. Invoices come from a JSON file, and "sending" a message is not implemented; outcomes are entered by hand.
- Requires Hindsight Cloud and a Groq API key. There is no offline mode.
- LLM output varies between runs. Channel, tone, and confidence for the same invoice can differ, and the JSON-mode call occasionally fails and falls back to plain-text parsing.
- Hindsight reflect occasionally fails server-side; the agent retries once and then proceeds without it.
- Only the demo customer has a generated playbook at the time of writing. Playbooks for other customers must be created with the command in "Initialize Hindsight".
- Directives (compliance rules such as no legal threats before a given day) are described in the project brief but were not implemented.
- Single user, single bank, no authentication.

## Hackathon Demo Takeaway

PayRecall is not just an LLM generating another collection reminder. Its value comes from remembering what happened with a specific customer, learning from outcomes, and changing the next action accordingly.
