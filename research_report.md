# HackwithHyderabad 3.0 — AI Agent Project Research Report

Prepared 28 September 2026. Research-only; no code was written. "VERIFIED" means read on the cited page; "INFERENCE" means our judgment.

## Table of contents

1. Executive summary
2. Hindsight: what it actually is (verified)
3. The hackathon landscape: what other teams already built
4. Candidate domain 1 — Finance operations (AR collections, AP exceptions)
5. Candidate domain 2 — IT infrastructure and compliance (change risk, audit remediation)
6. Candidate domain 3 — Healthcare administration and manufacturing quality (prior-auth, CAPA)
7. Candidate domain 4 — People and supply operations (recruiting calibration, procurement, freight, field service)
8. Competitive research summary
9. Hindsight suitability per candidate
10. Feasibility analysis
11. Demo analysis and Hindsight-necessity test
12. Comparison table
13. Recommended project: PayRecall
14. Why we should build it
15. Why we should NOT build the other candidates
16. Exact MVP
17. Exact architecture and technology stack
18. Exact demo flow and the 60-second WOW moment
19. Build plan
20. Sources

---

## 1. Executive summary

**Recommendation: build "PayRecall" (temporary name), a B2B accounts-receivable collections agent that remembers, per customer, which collection tactics worked and which backfired, and changes its next action accordingly.**

Why this one, in five points:

- **The memory loop is the purest instance of the organizers' diagram.** The agent *acts* (chooses channel, recipient, tone, lever, timing and drafts the message), the *outcome* arrives days later as an unstructured reply (paid, ignored, disputed, promise-to-pay), the outcome is *retained* as the agent's own experience, and the next decision for that customer is *different*. The loop repeats every invoice cycle, so "the agent improves over time" is believable and demonstrable in three cycles inside a 3-minute demo.
- **Originality is defensible.** The AR-automation category is crowded (HighRadius, Upflow, Chaser, Tesorio, Kolleno, Growfin, Peakflo, AgentCollect), but VERIFIED product pages show shipped mechanisms are risk scoring, payment-date prediction, send-time optimization, segment workflows and template drafting. Per-customer, evidence-backed *tactic-outcome memory including backfires* is only claimed in marketing copy (Kolleno, AgentCollect), never shown. No GitHub project and no Hindsight project in this hackathon does AR collections (GitHub API search: 0 results for Hindsight + collections/receivable/dunning).
- **Hindsight is necessary, not decorative.** Outcomes arrive as free-text replies, so a SQL table cannot capture "your tone was unacceptable, we are disputing line 3". Hindsight's experience-vs-world split ("I sent a firm email" vs "customer says they pay on the 15th"), auto-consolidated observations with proof counts and preserved history, temporal recall (month-end payment runs), entity graph (an AP contact who changes jobs), self-refreshing mental models (per-customer playbook) and directives (compliance guardrails) are each used for a distinct feature of the demo.
- **The India angle is unclaimed by any global vendor.** MSMED Act Section 15 (45-day cap), Section 16 interest at 3× RBI bank rate, Income-tax Section 43B(h) (now 37(2)(g)) disallowance for buyers, and the MSME ODR portal (since 15 Oct 2025) give a concrete, escalating tactic ladder (WhatsApp → call to AP head → 43B(h) nudge to buyer's finance head → interest notice → ODR filing) that memory can learn to time per customer. ₹7.34 lakh crore is locked in delayed MSME receivables.
- **It fits 8 hours.** Streamlit + Python + `hindsight-client` + a free-tier LLM. Synthetic data is narrative emails and call notes, which is exactly what makes the Hindsight story hold.

Runner-up: an audit-finding remediation agent that learns what each auditor firm accepts (originality of the loop is highest, category C, but feedback is annual, the payoff is a document diff, and a generic "AuditMind" Hindsight repo already exists). Rejected outright: field-service triage (already built twice on Hindsight), CAPA advisor (CAPAloop already at this hackathon), AP exceptions (Fragment markets the exact example), hiring-manager calibration (bias landmine; Metaview already ships self-learning ICPs), prior-auth (LeapHealth sells it in India), change-risk reviewer (ServiceNow/Atlassian/BMC feature; a "Deployment Memory" repo exists at this hackathon), freight exceptions (FourKites Loft markets the identical loop).

---

## 2. Hindsight: what it actually is (verified)

Sources: https://hindsight.vectorize.io/ , https://github.com/vectorize-io/hindsight , https://arxiv.org/abs/2512.12818 , https://hindsight.vectorize.io/developer/retain , /developer/retrieval , /developer/reflect , /developer/observations , /developer/api/memory-banks , /developer/api/mental-models , /developer/api/recall , /developer/api/reflect , https://hindsight.vectorize.io/blog/2026/07/24/recall-vs-reflect

- **Memory layers.** World facts (objective info received), **experience facts** (the bank's own first-person actions, e.g. "I recommended Python to Alice"), **observations** (auto-consolidated, deduplicated beliefs with proof counts and quoted evidence; "updated, not overwritten"; history preserved; flagged stale until re-verified), **mental models** (standing answers to a `source_query`, refreshed on cron or `refresh_after_consolidation`, with `based_on`, diff and version history). Reflect searches mental models → observations → raw facts.
- **Operations.** `retain(bank_id, content, context, timestamp, document_id, metadata, tags, entities, ...)` and `retain_batch(...)`; `recall(bank_id, query, types=["world"|"experience"|"observation"], budget, max_tokens, tags, tags_match, query_timestamp, include_source_facts, ...)` runs semantic + BM25 + entity-graph + temporal strategies fused by RRF, cross-encoder reranked, with recency/temporal/proof-count boosts; `reflect(bank_id, query, budget, max_tokens, response_schema, tags, include_facts, ...)` is an agentic loop (≤10 iterations; tools `search_mental_models` > `search_observations` > `recall` > `expand` > `done`) returning `text`, `structured_output`, `based_on{memories, mental_models, directives}` and a trace.
- **Fact typing is by speaker.** "Describe the speaker in each item's `context`" and name the bank; the agent's own action log retained with a context such as "Speaker: the agent" becomes experience facts. Retain tracks both occurrence time (extracted from text) and learning time (`timestamp`), so backdated history replays correctly.
- **Bank configuration.** `update_bank_config(reflect_mission, retain_mission, disposition_skepticism/literalism/empathy 1–5, observations_mission, enable_observations, enable_auto_consolidation, ...)`; `create_directive(bank_id, name, content)` = hard rules applied in reflect, tag-scopable. Consolidation runs automatically after retain; `trigger_consolidation` exists; `list_memories(type="observation")` and `list_mental_models(detail="content")` expose beliefs for a UI.
- **Deployment.** Python: `pip install hindsight-client`; `Hindsight(base_url="https://api.hindsight.vectorize.io", api_key=...)`. Cloud signup at https://ui.hindsight.vectorize.io/signup with free credits (a hackathon repo cites $50; the Devnovate listing mentions $99 of credits). Usage pricing: retain $10/M tokens, recall $0.75/M, reflect $0.05/call (https://vectorize.io/pricing). Self-host: one `docker run` (1.5–2 GB RAM) or `pip install hindsight-all` embedded. Caveat (VERIFIED in docs/models): Groq free tier is far below what a single retain call needs, so self-hosting on free LLM tiers is risky; use Cloud.
- **Extras usable in a demo.** Control Plane UI (banks, world/experience/observation views, entity timeline); Cloud dashboard; MCP server; webhooks for `consolidation.completed`.
- **Official cookbook** (https://github.com/vectorize-io/hindsight-cookbook): `hindsight-litellm-demo` (Streamlit, side-by-side no-memory / full-history / Hindsight) and `hindsight-tool-learning-demo` (with/without memory columns, accuracy over time) are the sanctioned "memory ON vs OFF" patterns.

---

## 3. The hackathon landscape: what other teams already built

VERIFIED via GitHub (about 30 public repos found; event listing https://devnovate.co/event/hack-with-hyderabad-30 describes an 8-hour hackathon by Devnovate with Hack With India at Microsoft Office Hyderabad, listed 3 Oct 2026, teams 2–6; INFERENCE from a search snippet, confirm with organizers).

| Domain | Count | Examples |
|---|---|---|
| Incident response / on-call / SRE | 11–13 | joshkumar50/hindsight-incident-agent, bharathnow (IncidentMind), MANISHGOOD/incidentmind, kanojiaatharva/HWH_Hindsight, SuryaVignesh06/HACKHYD3.0, Gowthamsai-k, SangaShashank, purnachander06, DRAKS17, emanisaikumar01, Kalyan9639 |
| Customer support | 3 | boyinaguru (MemoryDesk), Asdfyash1/recalldesk, dsribalaji (ShopMind) |
| Sales / deal intelligence | 3–4 | Manibhushanamk/deal-intelligence-agent, SritarunLakkaraju/dealmind, skjani314 |
| Code review | 3 | kaushikteja26/code-review-memory-agent ("PS #8"), RepoMind, DRAKS17 |
| Meeting prep | 2 | rithikag28, nlikitha619-coder |
| DevOps-adjacent | 2 | nehaa-3105 (Deployment Memory: deploy risk vs past incidents), wxhxxd (SEO/deploy correlation) |
| Manufacturing / warehouse / supplier | 3 | Sumasri05/CAPAloop (supplier corrective action, outcome-aware), Ram-2008/GodownIQ (warehouse supplier memory), skjani314 (predictive maintenance) |
| Field service / machine memory | 2 | Manjusha321-art/Machine-Memory-Agent (with "Without vs With Memory" tab), ravirepswal108-lgtm/memory-engineer |
| Compliance / audit | 1 (generic) | akshayavanga/AuditMind ("Compliance & Audit Memory Agent using Hindsight", 4 commits, 0 stars, recalls past findings, no outcome learning, hackathon affiliation not stated) |
| Other | 3 | social media engagement, website builder, generic scaffold |

Observed patterns to beat (VERIFIED across READMEs): nearly all use only retain + recall (+ one reflect call); nearly all show a memory ON/OFF toggle with pre-seeded history; Groq is the dominant LLM; almost none use mental models, directives, disposition, observation scopes, `query_timestamp`, or the experience-vs-world distinction. GitHub API searches for Hindsight combined with collections/receivable/dunning, procurement/supplier/RFQ, freight/logistics/dispatch, and compliance/audit each returned zero relevant results (AuditMind was found via a separate "audit memory agent" query).

The organizers' problem-statement list could not be fetched (Devnovate page renders title-only), but repo READMEs quote what appear to be its entries: customer support, incident response, meeting prep, code review, predictive maintenance, social media. We are avoiding all of them.

---

## 4. Candidate domain 1 — Finance operations

### 4.1 AR collections strategy agent (CANDIDATE 1, the finalist)

- **Target user.** Collections/AR specialist at a mid-size B2B supplier or an Indian MSME (or the founder who does collections themselves).
- **Specific problem.** Each overdue invoice needs a decision: which channel (email / WhatsApp / phone), which person (AP clerk vs AP head vs owner), what tone, which lever (none, early-payment discount, payment plan, MSME 45-day / 43B(h) reminder, interest notice, ODR filing), and when. Today this tacit knowledge lives in one person's head and leaves with them.
- **Current workflow.** Aging report → fixed dunning cadence (template emails at day 7/15/30) → escalation by rule → phone calls from memory.
- **What the agent does.** For each overdue invoice, recommends a concrete action plan and drafts the message; after the user logs the customer's reply, retains the outcome.
- **What Hindsight remembers.** World facts (customer's payment run dates, contacts, stated policies); experience facts (each action the agent took and what happened); observations per customer ("emails to accounts@ ignored 0/4; call to AP head Ramesh → paid within 3 days, 3/3; firm tone → dispute 1/1"); cross-customer observations ("distributors pay after reminders sent 5 days before month-end run"); a self-refreshing mental model "Collections playbook: <customer>"; directives (compliance rules).
- **How memory changes behaviour.** Different channel/recipient/tone/lever/timing for a known customer; hedged, policy-driven default for an unknown one; revised plan when a belief is contradicted (AP head leaves).
- **Why a memoryless LLM is worse.** It sends the generic polite email that was ignored four times, or the firm email that caused a dispute; it cannot know the AP head answers calls; it cannot notice the contact changed.
- **After recall, the agent actually does.** Emits a structured decision (channel, recipient, tone, lever, send_time, rationale with cited memories) and a drafted message; the user clicks "send" (mocked).
- **What is retained afterwards.** The action taken (experience), the customer's reply verbatim (world), and the resolution (paid/partial/promise/dispute/ignored with dates).

### 4.2 AP invoice-exception (3-way match) agent (CANDIDATE 2)

Persona AP clerk; memory of per-vendor quirks and prior resolutions. Rejected: see sections 8 and 15.

---

## 5. Candidate domain 2 — IT infrastructure and compliance

### 5.1 Change-request risk reviewer (CANDIDATE 3)
Persona platform/SRE lead; memory of change outcomes per team/system and which precautions prevented failure; output is risk level + required precautions + review comment citing precedents.

### 5.2 Audit-finding remediation agent (CANDIDATE 4, runner-up)
Persona compliance manager (SOC 2 / ISO 27001); memory of which remediation and evidence type each auditor firm accepted or rejected, which controls fail repeatedly, which fixes were rejected; output is remediation plan + evidence package draft citing precedents.

---

## 6. Candidate domain 3 — Healthcare administration and manufacturing quality

### 6.1 Prior-auth / cashless-claim agent with payer memory (CANDIDATE 5)
Persona hospital insurance desk; memory of per-payer denial patterns and the documents that got approvals.

### 6.2 Deviation / CAPA advisor (CANDIDATE 6)
Persona QA engineer; memory of which CAPAs passed effectiveness checks per line/failure mode.

---

## 7. Candidate domain 4 — People and supply operations

- **CANDIDATE 7** Recruiter shortlist agent learning each hiring manager's unstated criteria.
- **CANDIDATE 8** Procurement supplier-selection and negotiation memory (per-supplier slippage, quality, concession patterns).
- **CANDIDATE 9** Freight/shipment exception agent with carrier and facility memory.
- **CANDIDATE 10** Field-service triage with fix-outcome memory per asset.

---

## 8. Competitive research summary

Classification key: A common / B existing with room / C uncommon / D unexplored combination.

| # | Candidate | Closest products / projects (VERIFIED) | Overlap | Class |
|---|---|---|---|---|
| 1 | AR collections memory | HighRadius Autonomous Collections (risk scoring, Smart Send, templates; https://www.highradius.com/resources/platform/automated-collections-software/); Kolleno AI Agent (claims tactic learning at segment level; https://www.kolleno.com/ai-collections-agents-vs-traditional-dunning-what-finance-leaders-need-to-know/); Chaser recommended chasing times (per-customer timing only; https://www.chaserhq.com/features/recommended-chasing-times); Growfin, Upflow AI agents, Tesorio, Quadient/YayPay; AgentCollect (claims per-account optimization, opaque; https://www.agentcollect.com/blog/agentic-ai-accounts-receivable); Peakflo (WhatsApp/voice, call memory); India: Kapittx, BucksBuddy; academic: RL personalization of collections +8.11% recovery (ICIS 2020, https://aisel.aisnet.org/icis2020/hci_artintel/hci_artintel/18/), DebtBench (arXiv 2607.25218). OSS: Sudarshan-812/collections-agent (no memory), anjali1601-ops/AR-Credit-Projects (no memory). Hindsight/GitHub AR agents with memory: none. | 30–65% | **B** |
| 2 | AP exceptions memory | Ramp AP Agent "remembers how you process invoices" (vendor rules from corrections, Apr 2026; https://ramp.com/blog/ap-agent-processes-invoices); Fragment.ai (uses the exact "vendor bills freight separately" example; https://fragment.ai/wiki/tax-and-freight-discrepancies); HighRadius agentic matching; Stampli Billy; Medius; Vic.ai; 6+ GitHub 3-way-match agents (Gowravsharma, APilot, etc.) | 60–85% | **A/B** |
| 3 | Change-risk reviewer | ServiceNow Change Success Score + Predictive Intelligence + Now Assist risk explanation; Atlassian JSM AI Risk Assessment (GA 2026); BMC HelixGPT Change Risk Advisor; Kyndryl patent US12294503B2 (self-learning change risk); ING "Learning from Change" (ICSE-SEIP 2026); SENTRY (RAG over past changes, arXiv 2608.21203); Lansweeper "Change Manager Agent" vision blog (80% conceptual overlap); hackathon: nehaa-3105 Deployment Memory | 45–65% | **B→A** |
| 4 | Audit remediation memory | Vanta Compliance Agent + Audit Hub (stores auditor accept/reject but does not learn); Drata; Secureframe AI Evidence Validation; Thoropass First Pass; Sprinto/Scrut/Scytale; AuditBoard; Grant Thornton "16 sample agents" (conceptual); Hindsight: akshayavanga/AuditMind (generic recall of findings). No product or paper learns from auditor outcomes. | 25–50% | **C loop inside A category** |
| 5 | Prior-auth payer memory | LeapHealth Insurance & TPA AI (India; flags denials against past TPA decisions; Apollo, Cloudnine customers; https://theleaphealth.com/ai-agents/insurance-tpa); Develop Health (appeal guidance calibrated to each payer's decision patterns); Tennr; Waystar AltitudeAI; Cohere/Anterior (payer side); OSS appeal drafters (stateless) | 50–80% | **B→A** |
| 6 | CAPA effectiveness memory | **CAPAloop (Hindsight, this hackathon, outcome-aware supplier CAPA with confidence upgrade)**; D0D0D0D/HCR-C2-062 (GMP deviation agent using past CAPA outcomes); Veeva Deviation Agent (summaries only); TrackWise/MasterControl (aspirational) | 70–85% | **C commercially, taken at hackathon** |
| 7 | Hiring-manager calibration | Metaview self-learning ICP (learns from accept/reject; https://www.metaview.ai/application-review); Juicebox, Fetcher, hireEZ, Eightfold, High Five; WSDM '26 paper "From Personalization to Prejudice" (memory-enhanced recruiter agents amplify bias; https://arxiv.org/html/2512.16532); NYC LL144, EU AI Act Annex III | 45–65% | **A** |
| 8 | Procurement supplier memory | Pactum (autonomous negotiation, Walmart/Maersk); Arkestro (predictive supplier behaviour, suggested pricing); Fairmarkit; Keelvar; Levelpath/Zip/Coupa/Ariba; OSS ProcurePulse (supplier OTIF memory, 0 stars); hackathon adjacency: GodownIQ (supplier memory), CAPAloop (supplier) | 35–60% | **B leaning C** |
| 9 | Freight exception memory | FourKites Loft ("the 2,500th exception on a lane is resolved better than the first", facility twin; https://www.fourkites.ai/platform/loft); FreightScout (learns from every decision); Loadsmart agents; Fleetworks ("tough facilities" memory); HappyRobot ($1.22B); India: Freight Tiger, Shipsy, Locus | 45–80% | **B** |
| 10 | Field-service fix memory | Aquant (85% overlap); ServiceMax Remote Triage (2019); Maximo; Fiix; Agentforce; **Mem0 field-service memory demo**; **two Hindsight repos (Machine-Memory-Agent, memory-engineer)** | 70–85% | **A** |

---

## 9. Hindsight suitability per candidate

For each: what is retained / recalled / when / how recall changes the decision / what is learned after / why a DB or RAG is less suitable / demo-ability in 2–5 minutes.

**1. AR collections (strong, conditional on narrative data).** Retained: agent actions (experience), customer replies and facts (world), outcomes with dates. Recalled: at decision time, by customer tag and by query ("what worked with Meridian; what backfired"); observations first. Decision change: channel/recipient/tone/lever/timing. Learned after: outcome of the new action; observation proof counts and contradictions ("Ramesh left"). Why not DB/RAG: outcomes are free text; the belief "firm tone → dispute" must be extracted, consolidated and later revised with history; cross-customer generalisation by topic; AP contact as an entity crossing customers; month-end temporal patterns; policy as directives. Demo: yes, three cycles fit in 3 minutes. Honest caveat: if the demo data were a clean CSV of (customer, tactic, outcome), a GROUP BY would replicate it; the data must be emails and call notes.

**2. AP exceptions (weak).** Vendor quirks are table-shaped (vendor_id, exception_type, resolution, count). Hindsight adds little beyond lookup. Rejected.

**3. Change risk (partial).** Team × system × window failure rate is one SQL query (ServiceNow's Change Success Score). Hindsight helps only for narrative rollback notes and precaution-efficacy beliefs; SENTRY already does RAG over past changes. Demo intuitive but reducible to a risk matrix.

**4. Audit remediation (strong).** Auditor feedback lives in comment threads; firm-specific, control-specific, time-bound beliefs ("Firm X rejects screenshots for periodic-review controls since 2025") are exactly observations; mental models map to "Auditor profile: Firm X". Caveat: annual audits mean sparse real-world feedback; a small synthetic history fits in one prompt, so the demo must show consolidation and supersession explicitly.

**5. Prior-auth (moderate).** (payer, procedure, denial_reason, docs) is a GROUP BY; Hindsight wins on consolidation of noisy free-text outcomes, TPA↔insurer entity links and temporal drift. Commercially crowded.

**6. CAPA (strong but taken).** Multi-hop entity graph, mandatory action→outcome time lag, contradictory outcomes across lines. CAPAloop already exploits this at the hackathon.

**7. Hiring-manager calibration (moderate, ethically hazardous).** Observations per HM with evidence counts map well, but the WSDM '26 paper shows memory-enhanced recruiting agents systematically amplify bias; the fairness gate would have to be the product.

**8. Procurement (strong).** Suppliers are natural entities; negotiation-behaviour memory from email threads resists a schema; mental models as supplier playbooks. Caveat: delivery/quality stats alone are a scorecard (ProcurePulse).

**9. Freight (partial).** Carrier scorecards are SQL; free-text check-call logs and facility behaviour beliefs are where Hindsight helps.

**10. Field service (strong but taken twice).** Fix-outcome polarity and temporal decay fit observations well; Machine-Memory-Agent and memory-engineer already do it on Hindsight.

---

## 10. Feasibility analysis (assume ~8 hours of build time; Python, Streamlit, APIs, SQL basics)

| # | Candidate | MVP difficulty (1–10) | Time to functional MVP | Data | Hindsight integration | UI | Demo complexity | Biggest technical risk |
|---|---|---|---|---|---|---|---|---|
| 1 | AR collections | 4 | 5–6 h | Synthetic emails/call notes, 5 customers, ~30 events | Low–medium (retain_batch with timestamps + context; reflect with schema; observations listing; one mental model; 3 directives) | Low (Streamlit queue + detail + memory panel) | Low | Consolidation latency before observations appear; reflect latency 5–20 s |
| 2 | AP exceptions | 4 | 5 h | Synthetic POs/invoices | Low | Low | Low–medium | Looks like a cache |
| 3 | Change risk | 5 | 6 h | ~40 synthetic change tickets | Medium | Low | Low | Reducible to GROUP BY; near incident teams |
| 4 | Audit remediation | 5 | 6 h | Synthetic findings + auditor comments, 2 firms | Medium | Medium (document diff view) | Medium (jargon) | Sparse feedback story; payoff is a document |
| 5 | Prior-auth | 5 | 6 h | Synthetic cases; no PHI | Medium | Medium | Low | LeapHealth clone perception |
| 6 | CAPA | 5 | 6 h | Synthetic deviations | Medium | Medium | Medium (jargon) | CAPAloop already exists |
| 7 | HM calibration | 6 | 7 h | 25 fake candidates, 8 verdicts | Medium | Medium | Low | Bias objection within 30 s |
| 8 | Procurement | 6 | 7 h | POs + negotiation threads + quality incidents (3 data types) | Medium | Medium | Medium (scripted supplier replies) | Scorecard perception; more data to fabricate |
| 9 | Freight | 5 | 6 h | Check-call logs | Medium | Medium | Low | FourKites replica perception |
| 10 | Field service | 4 | 5 h | Work orders | Low | Low | Low | Built twice already |

All candidates use synthetic data (acceptable and preferable: no PII, no PHI). Required APIs for the finalist: Hindsight Cloud (free credits) and one LLM API (Groq or Gemini free tier; Anthropic if a key is available). No datasets needed.

---

## 11. Demo analysis and Hindsight-necessity test

**Necessity test ("remove Hindsight; what disappears?")**

- **1 AR collections:** "Without the accumulated record of what we did to this customer and how they reacted, the agent cannot know that four emails were ignored, that a firm email triggered a two-week dispute, that a call to the AP head worked three times, that the AP head has since left, or that distributors in general pay after month-end-run reminders. It sends the generic polite email again." Substantial.
- **4 Audit:** "Without memory of auditor-specific rejections and repeat findings, the agent submits screenshots the auditor rejected last year and re-proposes the manual fix that failed to prevent recurrence." Substantial, but the feedback loop turns once a year.
- **8 Procurement:** "Without per-supplier memory it invites the supplier who slipped 3 of 4 deliveries and anchors 15% too high." Substantial.
- **3 Change risk:** "Without memory it rates the migration medium risk instead of requiring a window and a flag." Substantial but replicable with a scorecard.
- **2, 5, 7, 9, 10:** substantial in principle, but either reducible to a lookup (2), ethically compromised (7), or already demonstrated by others on the same memory system (6, 10) or in shipped products (5, 9).

**Before/after demo feasibility.** Strongest and most legible for lay judges: 1 (money, everyone has chased a payment), 8 (vendor always late), 10 (chiller keeps breaking), 3 (team broke prod twice). Requires domain translation: 4, 5, 6. Ethically fraught: 7.

---

## 12. Comparison table

Scores are 1–10 (higher is better; "competition" high = little overlap). Weighted with the judging criteria (Innovation 30, Hindsight 25, Technical 20, UX 15, Impact 10) as a sanity check only; the choice is reasoned, not mechanical.

| # | Candidate | Problem originality | Hindsight centrality | Business value | Demo clarity | Feasibility (8 h) | Competition / overlap | Innovation potential | Hackathon prior art on Hindsight | Weighted |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | AR collections | 6 | 8 | 9 | 9 | 9 | 5 | 7 | none | 7.6 |
| 4 | Audit remediation | 8 | 8 | 7 | 6 | 8 | 7 | 8 | AuditMind (generic) | 7.5 |
| 8 | Procurement | 6 | 8 | 8 | 8 | 7 | 5 | 6 | GodownIQ, CAPAloop (supplier-adjacent) | 6.9 |
| 3 | Change risk | 5 | 6 | 7 | 8 | 8 | 4 | 5 | Deployment Memory | 6.1 |
| 9 | Freight | 5 | 6 | 7 | 8 | 7 | 4 | 5 | none | 6.0 |
| 5 | Prior-auth | 4 | 6 | 8 | 8 | 7 | 3 | 5 | none | 5.7 |
| 6 | CAPA | 7 | 8 | 7 | 6 | 7 | 5 | 6 | CAPAloop | 6.6 (disqualified) |
| 7 | HM calibration | 4 | 7 | 6 | 8 | 6 | 3 | 4 | none | 5.3 (ethics) |
| 10 | Field service | 3 | 8 | 7 | 9 | 9 | 2 | 3 | two repos | 5.5 (disqualified) |
| 2 | AP exceptions | 3 | 4 | 7 | 7 | 9 | 3 | 3 | none | 4.6 |

Reasoning beyond the numbers: candidates 1 and 4 are effectively tied. We pick 1 because (a) its feedback loop turns every invoice cycle, so "the agent improves because of past interactions" can be shown three times in one demo instead of once; (b) it has zero prior art on Hindsight, whereas a generic Hindsight audit-memory repo exists; (c) the India MSME payment story gives real-world impact a concrete number and a locally resonant escalation ladder; (d) the payoff is a decision plus money, not a document diff. We accept that "AI collections" is a familiar category and mitigate it by leading with backfire memory and belief revision, which no vendor demonstrates.

---

## 13. Recommended project: PayRecall

**Name check.** "PayRecall": 0 GitHub repositories (GitHub API search, 28 Sep 2026). Web/domain/trademark search could not be completed (search budget exhausted, DuckDuckGo CAPTCHA); treat as a temporary name and re-check before publishing. Alternatives with 0 GitHub hits: none checked beyond this; "Recollect"/"CollectWise" are likely taken (INFERENCE).

**One-line pitch.** PayRecall is a collections agent for B2B suppliers that remembers, per customer, which reminders worked and which backfired, and picks a different channel, person, tone and lever the next time an invoice goes overdue.

**Problem.** Collections is tacit, person-dependent knowledge. Generic dunning cadences ignore that one customer only pays after a call to their AP head, another disputes anything with a firm tone, and a third pays on the month-end run regardless. When the collections person leaves, the knowledge leaves. In India, ₹7.34 lakh crore of MSME receivables are delayed (Kapittx, citing Mar 2024 data), and the statutory levers (MSMED Act 45-day cap and 3× bank-rate interest; Income-tax 43B(h)/37(2)(g) disallowance for buyers; MSME ODR portal) are under-used because nobody remembers when they work.

**Target user.** The collections/AR specialist (or founder) at a B2B supplier with 50–500 customers; framed for an Indian MSME but generic.

**Why existing approaches are insufficient.** VERIFIED product pages for HighRadius, Tesorio, Growfin, Upflow, Quadient show risk scoring, payment-date prediction, send-time optimization, segment workflows and template drafting. Chaser learns per-customer timing only. Kolleno and AgentCollect claim per-account tactic learning in marketing but expose no evidence, no memory, no explanation of *why* a tactic was chosen, and none model *backfires* (disputes, churn). None encode the Indian statutory ladder.

**Why memory matters (exactly what Hindsight remembers).**

| Hindsight layer | Content in PayRecall |
|---|---|
| World facts | Customer profile and stated behaviours ("pays on 15th run"; "AP head is Ramesh"; "prefers WhatsApp"); customer replies verbatim; invoice facts |
| Experience facts | Every action the agent took: "On 12 Mar 2026 I sent a firm email to Meridian re INV-1877" and its outcome "dispute opened on line 3 two days later" |
| Observations (auto) | Per customer: "emails to accounts@ ignored (0/4)"; "call to AP head → paid within 3 days (3/3)"; "firm tone → dispute (1/1)". Cross-customer: "distributors pay after reminders 5 days before month-end run (4/5)" |
| Mental models | "Collections playbook: <customer>" (source_query "How should we collect from <customer> and what should we avoid?", refresh_after_consolidation) |
| Directives | "Never threaten legal action before day 60"; "Mention MSMED interest only after day 45"; "Never contact personal numbers"; "Always cite invoice number and amount" |
| Disposition | skepticism 4 (question repeated "cheque is in the mail"), empathy 3 |

**Memory loop.**
Event (invoice overdue) → Recall (customer-tagged recall + reflect over observations and playbook) → Decision (channel, recipient, tone, lever, timing, draft) → Action (mock send) → Outcome (reply logged: paid / promise / dispute / ignored) → Retain (experience fact + world fact; consolidation updates the observation; playbook refreshes) → next Event.

**Why Hindsight (not a table, not RAG).**
1. Outcomes are unstructured replies; retain extracts the facts; consolidation produces the belief; no hand-coded outcome taxonomy.
2. Beliefs are revised with history, not overwritten: when Ramesh leaves, "call Ramesh works 3/3" is superseded, and the UI shows it.
3. Experience vs world: the agent's own promise ("I offered a 30-day plan in June") is weighed differently from the customer's claim ("we always pay in 30 days").
4. Entity graph: contacts and companies are entities; "Ramesh" recalled across customers if he moves.
5. Temporal recall: "what happened at quarter-end", "since June".
6. Mental models + directives: policy is curated and auditable, learned tactics fill the gaps; reflect returns `based_on` citations so every recommendation is explainable.

**Competitive landscape and differentiation.** See section 8, row 1. Our differentiation: (a) per-customer tactic-outcome memory with **negative** outcomes as first-class; (b) explainable recommendations citing the specific past interactions; (c) live belief revision when evidence contradicts; (d) India statutory escalation ladder timed per customer; (e) policy as directives, learned tactics as observations, both visible.

---

## 14. Why we should build it

- It matches every organizer requirement literally: past experience → Hindsight → new situation → recall → changed action → new outcome → memory updated, and the demo can run that loop three times.
- Memory is the product; without it the agent is a template sender.
- It uses six Hindsight capabilities (experience facts, observations, mental models, directives, disposition, temporal/entity recall) where nearly all competing submissions use retain + recall only.
- It is buildable in 8 hours with tools the team already knows (Python, Streamlit, one LLM API).
- Judges understand it in one sentence, and the money is visible.
- Real-world impact has a number (₹7.34 lakh crore) and a regulatory hook (43B(h)/37(2)(g), ODR portal) that no global vendor demos.

## 15. Why we should NOT build the other candidates

- **AP exceptions (2):** Fragment's public wiki uses our exact freight example; Ramp ships "remembers how you process invoices"; six GitHub 3-way-match agents exist; memory is table-shaped.
- **Change risk (3):** ServiceNow, Atlassian and BMC ship AI change-risk features; a Kyndryl patent covers the self-learning loop; a "Deployment Memory" repo exists at this hackathon; judges will see GROUP BY plus a risk matrix; too close to the 11+ incident teams.
- **Audit remediation (4):** Best originality of the loop, but audits are annual so the learning story is thin, the output is a document diff, jargon costs pitch time, and AuditMind already claims "Compliance & Audit Memory Agent using Hindsight". Keep as backup if the team strongly prefers compliance.
- **Prior-auth (5):** LeapHealth sells almost this to Apollo-tier hospitals in India; Develop Health and Tennr cover the US; regulatory sensitivity.
- **CAPA (6):** CAPAloop already implements an outcome-aware CAPA agent on Hindsight at this hackathon with a near-identical demo.
- **HM calibration (7):** Metaview ships self-learning ideal-candidate profiles; the WSDM '26 paper shows memory-enhanced recruiting agents amplify bias; recruitment is EU AI Act high-risk; the pitch invites "isn't this learning to discriminate?" in the first 30 seconds.
- **Procurement (8):** Good fit, but Pactum/Arkestro/Fairmarkit are well known, two supplier-memory repos exist at this hackathon, and it needs three synthetic data types plus scripted supplier replies in 8 hours.
- **Freight (9):** FourKites Loft publicly markets the identical "gets better with every exception, knows the facility" loop.
- **Field service (10):** Aquant's core product; Mem0 has a public field-service memory demo; two Hindsight repos already do it with a with/without-memory tab.

---

## 16. Exact MVP (only what the demo needs)

1. **Synthetic dataset** (JSON): 5 customers with contacts and payment habits; 6 open overdue invoices; ~30 historical interaction records over 6 months for 3 of the customers, written as emails, WhatsApp messages and call notes, each with a date, the agent's action and the customer's reply/outcome. Two customers have no history (to show the fallback). One customer's history contains a contradiction event (AP head leaves).
2. **Hindsight bank setup**: create bank; `update_bank_config` (reflect_mission, retain_mission, disposition); 3–4 directives; `retain_batch` seeding with backdated `timestamp`, `context` marking speaker (agent vs customer), tags `customer:<id>`, `invoice:<id>`; trigger consolidation; create mental model per seeded customer with `refresh_after_consolidation`.
3. **Agent** (`agent.py`): `recommend(invoice, memory_on: bool)` returns a Pydantic decision {channel, recipient, tone, lever, send_when, rationale, cited_memories[], confidence} plus a drafted message. Memory OFF: single LLM call with invoice + customer basics. Memory ON: `recall` (tags=customer, types all, include_source_facts) for the transparency panel and `reflect(query, response_schema=Decision, tags=customer)` for the decision; then LLM drafts the message from the decision and citations.
4. **Outcome logging**: form (reply text + resolution + date) → `retain` two items (agent action as experience; customer reply as world) → trigger consolidation → refresh mental model → UI reloads observations.
5. **Streamlit UI** (single page, three columns): overdue queue table; invoice detail with Memory ON/OFF toggle, "Recommend" button, side-by-side OFF vs ON cards, draft message, "Send (mock)"; memory panel listing observations (`list_memories(type="observation")` filtered by customer tag), the playbook mental model, directives, and raw recalled facts with scores.
6. **Reset / seed buttons** and a pre-seeded backup bank (export/clone) in case consolidation is slow on stage.

Explicitly out of scope: real email/WhatsApp sending, authentication, ERP integration, multi-user, payment-date prediction, dashboards beyond the queue.

---

## 17. Exact architecture and technology stack

```
User (collections specialist)
  → Streamlit UI (queue, invoice detail, ON/OFF toggle, memory panel, outcome form)
    → agent.py (orchestrator)
        → LLM API (Groq Llama-3.x / Gemini free tier / Anthropic if key): drafting + memory-OFF decision
        → tools: invoice/customer loader (local JSON), statutory calculator (MSMED interest, day-45 / 43B(h) flags), mock sender
        → hindsight_client wrapper: retain / retain_batch / recall / reflect / list observations / mental models / directives / trigger consolidation
            → Hindsight Cloud bank "payrecall-demo" (api.hindsight.vectorize.io)
  ← decision JSON + draft + citations; observations & playbook rendered live
Local storage: data/*.json (customers, invoices, seed history), outcomes appended to a local log for the demo
```

Stack: Python 3.11; `streamlit`; `hindsight-client`; `pydantic`; `groq` (or `google-genai` / `anthropic`); `pandas`; `python-dotenv`. Hindsight Cloud with free credits (fallback: `pip install hindsight-all` embedded with a paid LLM key; do not rely on Groq free tier for Hindsight's own retain LLM).

---

## 18. Exact demo flow (about 3.5 minutes) and the 60-second WOW moment

0:00 **Setup line.** "Collections is tacit knowledge. PayRecall makes the agent remember what worked and what backfired with each customer."

0:15 **Before memory.** Open the overdue queue. Select Meridian Retail, INV-2041, ₹4.2 lakh, 38 days overdue. Memory OFF → Recommend. The agent proposes a polite email to accounts@meridian with a standard reminder. Show the draft.

0:45 **Experience.** Click "Load 6 months of history". Twenty-five narrative records are retained (emails ignored, a call to AP head Ramesh that got payment, a firm email that triggered a dispute, a payment plan honoured). The memory panel fills with observations: "Meridian: emails to accounts@ ignored (0/4)", "Call to AP head Ramesh → paid within 3 days (3/3)", "Firm tone → dispute (1/1)", plus the auto-generated "Collections playbook: Meridian".

1:15 **After memory (the WOW moment).** Memory ON → Recommend on the same invoice. Side-by-side: the agent now recommends a WhatsApp message to Ramesh followed by a call, friendly tone, no firm language, and flags that day 45 is in 7 days so a 43B(h)/interest heads-up to Meridian's finance head is queued for day 46 if unpaid. Each element cites the memory it came from (`based_on`). Say out loud: "Same invoice, same LLM. The only difference is memory."

2:00 **New outcome.** Log the reply: "Ramesh: processed, ₹4.2L paid 30 Sep." Retain. The observation's proof count ticks 3/3 → 4/4; the playbook refreshes.

2:30 **Belief revision.** Log a second event: "Called Ramesh; number unreachable; reception says Ramesh left; new AP head is Kavita." Retain. The observation about Ramesh is superseded; the next recommendation switches to an introductory email plus WhatsApp to Kavita and lowers confidence. "Memory here is not a cache; it changes its mind with evidence."

3:00 **Generalisation and honesty.** Select a customer with no history. The agent falls back to the directives and the cross-customer observation ("distributors respond to reminders 5 days before month-end run") and says its confidence is low because it has no history with this customer.

3:20 **Close.** "Every cycle makes the next recommendation better, and the knowledge stays with the company when the collector leaves."

The single moment judges should remember: the side-by-side at 1:15 where the agent *refuses* the firm email because of a remembered dispute, cites the call that worked three times, and then, at 2:30, visibly revises that belief when the contact leaves.

---

## 19. Build plan (8-hour event; check organizer rules on pre-event preparation)

**Before the event (non-code prep, typically allowed):** create the Hindsight Cloud account and API key; test one retain/recall/reflect call and measure consolidation latency; get an LLM API key; write the synthetic dataset and the demo script; agree on the decision schema and the UI sketch; decide roles.

| Hour | Task | Owner |
|---|---|---|
| 0–1 | Repo skeleton, `.env`, `hindsight_client` wrapper (create bank, config, directives, seed, recall, reflect, retain outcome, list observations, mental models, trigger consolidation) | Dev A |
| 0–1 | Finalise synthetic data (5 customers, 6 invoices, ~30 narrative events, contradiction event) and seed script with backdated timestamps and speaker context | Dev B |
| 1–2 | Seed the bank; verify observations and the playbook mental model appear; tune `retain_mission`/`observations_mission` if beliefs are vague; export bank as backup | A + B |
| 2–4 | Agent: Pydantic decision schema, memory-OFF prompt, memory-ON reflect call with `response_schema`, draft generation, statutory calculator (day-45, interest, 43B(h) flags) | Dev A |
| 2–4 | Streamlit: queue table, invoice detail, ON/OFF toggle, side-by-side cards, draft, mock send | Dev B |
| 4–6 | Outcome form → retain → consolidation → refresh → memory panel updates; citations rendering; new-customer fallback | A + B |
| 6–7 | Belief-revision scenario, reset/seed buttons, spinners and error handling, caching of recall results, README | A + B |
| 7–8 | Full rehearsal twice, record a backup screen video, screenshots, pitch text | All |

**Risks and mitigations.** Consolidation latency: trigger manually, poll operations, keep a pre-seeded backup bank. Reflect latency: show a spinner and pre-warm on load. Credits: usage is tiny (a few hundred KB of text). "Why not SQL?": have the belief-revision moment and the free-text replies ready. Hackathon rules on prep: confirm whether pre-written code is allowed; if not, all prep stays non-code.

---

## 20. Sources (key)

Hindsight: https://hindsight.vectorize.io/ · https://github.com/vectorize-io/hindsight · https://arxiv.org/abs/2512.12818 · https://hindsight.vectorize.io/developer/retain · https://hindsight.vectorize.io/developer/retrieval · https://hindsight.vectorize.io/developer/reflect · https://hindsight.vectorize.io/developer/observations · https://hindsight.vectorize.io/developer/api/memory-banks · https://hindsight.vectorize.io/developer/api/mental-models · https://hindsight.vectorize.io/developer/api/recall · https://hindsight.vectorize.io/developer/api/reflect · https://hindsight.vectorize.io/developer/installation · https://hindsight.vectorize.io/developer/models · https://hindsight.vectorize.io/blog/2026/07/24/recall-vs-reflect · https://hindsight.vectorize.io/blog/2026/06/05/mental-models-deep-dive · https://github.com/vectorize-io/hindsight-cookbook · https://vectorize.io/pricing · https://docs.hindsight.vectorize.io/getting-started

Hackathon: https://devnovate.co/event/hack-with-hyderabad-30 · repos listed in section 3 (all github.com)

AR collections: https://www.highradius.com/resources/platform/automated-collections-software/ · https://www.kolleno.com/ai-collections-agents-vs-traditional-dunning-what-finance-leaders-need-to-know/ · https://www.chaserhq.com/features/recommended-chasing-times · https://www.growfin.ai/ · https://upflow.io/ai-agents · https://www.tesorio.com/product/collections · https://www.agentcollect.com/blog/agentic-ai-accounts-receivable · https://peakflo.co/ai-voice-agents · https://kapittx.com/accounts-receivable-automation-in-india/ · https://aisel.aisnet.org/icis2020/hci_artintel/hci_artintel/18/ · https://arxiv.org/abs/2607.25218 · https://github.com/Sudarshan-812/collections-agent · MSME law: https://www.corplawupdates.in/tools/fee-calculator/msme · https://samadhaan.msme.gov.in/ · https://taxupdate.in/income-tax/893/section-43bh-msme-payment-disallowance-tax-audit-2026-section-37-income-tax-act-2025/

AP: https://ramp.com/blog/ap-agent-processes-invoices · https://fragment.ai/wiki/tax-and-freight-discrepancies · https://www.highradius.com/resources/Blog/agentic-ai-invoice-matching/ · https://github.com/Gowravsharma/ap-invoice-exception-agent

Change risk: https://www.servicenow.com/community/itsm-blog/change-success-score-gamification/ba-p/2294799 · https://community.atlassian.com/forums/Jira-Service-Management-articles/AI-Risk-Assessment-is-now-generally-available-in-Jira-Service/ba-p/3214684 · https://patents.google.com/patent/US12294503B2/en · https://arxiv.org/html/2604.13462v1 · https://arxiv.org/pdf/2608.21203 · https://www.lansweeper.com/blog/itsm/the-change-manager-agent-how-agentic-ai-can-transform-change-enablement/

Audit: https://www.vanta.com/resources/vanta-delivers-compliance-agent · https://help.vanta.com/en/articles/11345427-audit-evidence · https://secureframe.com/newsroom/ai-evidence-validation · https://www.thoropass.com/company/newsroom/introducing-first-pass-ai-driven-evidence-verification · https://www.fieldpie.com/blog/repeat-audit-findings/ · https://github.com/akshayavanga/AuditMind

Healthcare / CAPA: https://theleaphealth.com/ai-agents/insurance-tpa · https://www.develophealth.ai/blog/ai-prior-authorization · https://www.tennr.com/ · https://github.com/Sumasri05/CAPAloop-Outcome-Aware-Supplier-Corrective-Action-Agent-for-Hack-With-Hyderabad-3.0 · https://github.com/D0D0D0D/HCR-C2-062 · https://quality.veevavault.help/en/lr/1006459

Recruiting / procurement: https://www.metaview.ai/application-review · https://arxiv.org/html/2512.16532 · https://pactum.com/product/ · https://arkestro.com/predictive-procurement/ · https://github.com/vishwaj-eet/AI-Purchasing-Agent

Logistics / field service: https://www.fourkites.ai/platform/loft · https://freightscout.ai/ · https://www.aquant.ai/platform · https://mem0.ai/blog/memory-for-the-trades-persistent-memory-for-field-service-ai-agents · https://github.com/Manjusha321-art/Machine-Memory-Agent · https://github.com/ravirepswal108-lgtm/memory-engineer
