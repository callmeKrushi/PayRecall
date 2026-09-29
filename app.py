"""PayRecall Streamlit demo UI.

Same invoice, two paths:
    MEMORY OFF -> generic recommendation (Hindsight never called)
    MEMORY ON  -> personalised recommendation from Hindsight memory

agent.py is the single source of truth for recommendations; this file only
selects inputs, calls the agent, and renders results.

Run:  streamlit run app.py
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Any

import streamlit as st

import agent
import hindsight_memory as hm

log = logging.getLogger("payrecall.app")

st.set_page_config(page_title="PayRecall", page_icon="🧠", layout="wide")

COMPARE_FIELDS = (
    ("channel", "Channel"),
    ("recipient", "Recipient"),
    ("tone", "Tone"),
    ("suggested_timing", "Timing"),
    ("approach", "Approach"),
)

# Outcome form choices -> the outcome tag stored in Hindsight (same vocabulary as the seed data)
RESOLUTIONS = {
    "Promise to Pay": "promise",
    "Paid": "paid",
    "Disputed": "dispute",
    "Ignored": "ignored",
    "Partial Payment": "partial",
    "Other": "none",
}
NEW_MEMORY_POLL_ATTEMPTS = 4
NEW_MEMORY_POLL_SECONDS = 2.0

# --------------------------------------------------------------------------- #
# Data helpers (read-only)
# --------------------------------------------------------------------------- #

@st.cache_data(show_spinner=False)
def load_data() -> dict[str, Any]:
    return hm.load_dataset()


def money(amount: Any) -> str:
    try:
        return f"₹{int(amount):,}"
    except (TypeError, ValueError):
        return str(amount)


@st.cache_data(show_spinner=False, ttl=300)
def load_playbook(customer_id: str) -> dict[str, Any] | None:
    """Learned playbook mental model for the customer, or None if none exists yet."""
    try:
        hm.initialize_memory(verify=False)
        pb = hm.get_customer_playbook(customer_id)
        return pb if pb.get("content") else None
    except (hm.HindsightConfigError, hm.HindsightAPIError) as exc:
        log.info("No playbook for %s: %s", customer_id, type(exc).__name__)
        return None


# --------------------------------------------------------------------------- #
# Agent calls with user-friendly error handling
# --------------------------------------------------------------------------- #

def run_agent(customer: dict[str, Any], invoice: dict[str, Any], memory_enabled: bool) -> agent.Recommendation | None:
    """Call the agent; show a friendly message (never a trace or a secret) on failure."""
    label = "MEMORY ON" if memory_enabled else "MEMORY OFF"
    try:
        with st.spinner(f"Generating {label} recommendation..."):
            return agent.recommend(customer, invoice, memory_enabled=memory_enabled)
    except agent.AgentConfigError as exc:
        st.error(f"Configuration problem: {exc}")
    except agent.AgentDataError as exc:
        st.error(f"Data problem: {exc}")
    except agent.AgentMemoryError as exc:
        st.error(f"Hindsight memory could not be reached. {exc}")
    except agent.AgentLLMError as exc:
        st.error(f"The language model call failed. {exc}")
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to the UI
        log.exception("Unexpected error in run_agent")
        st.error(f"Unexpected error ({type(exc).__name__}). Please try again.")
    return None


def result_key(invoice_id: str, memory_enabled: bool) -> str:
    return f"rec::{invoice_id}::{'on' if memory_enabled else 'off'}"


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

INVOICE_CARD_CSS = """
<style>
.pr-grid {display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.75rem; margin: 0.25rem 0 0.75rem 0;}
@media (max-width: 900px) {.pr-grid {grid-template-columns: repeat(2, minmax(0, 1fr));}}
.pr-card {background: var(--secondary-background-color); border: 1px solid rgba(128, 128, 128, 0.25);
          border-radius: 0.5rem; padding: 0.7rem 0.9rem; min-width: 0;}
.pr-label {font-size: 0.78rem; letter-spacing: 0.04em; text-transform: uppercase; opacity: 0.7; margin-bottom: 0.2rem;}
.pr-value {font-size: 1.35rem; font-weight: 600; line-height: 1.3; color: var(--text-color); overflow-wrap: anywhere;}
.pr-desc {font-size: 1.05rem; line-height: 1.55; color: var(--text-color); opacity: 0.92; margin: 0.25rem 0 0.5rem 0;}
</style>
"""


def render_invoice(customer: dict[str, Any], invoice: dict[str, Any]) -> None:
    """Six facts in a 3x2 grid of cards that wrap instead of truncating (st.metric clips long values)."""
    import html

    st.subheader("Selected invoice")
    fields = [
        ("Customer", customer["name"]),
        ("Invoice", invoice["invoice_id"]),
        ("Amount", money(invoice.get("balance_due", invoice.get("amount")))),
        ("Due date", invoice.get("due_date", "-")),
        ("Days overdue", invoice.get("days_overdue", "-")),
        ("Status", str(invoice.get("status", "-")).title()),
    ]
    cards = "".join(
        f'<div class="pr-card"><div class="pr-label">{html.escape(str(label))}</div>'
        f'<div class="pr-value">{html.escape(str(value))}</div></div>'
        for label, value in fields
    )
    st.markdown(INVOICE_CARD_CSS + f'<div class="pr-grid">{cards}</div>', unsafe_allow_html=True)
    if invoice.get("description"):
        st.markdown(f'<p class="pr-desc">{html.escape(invoice["description"])}</p>', unsafe_allow_html=True)


def render_recommendation(rec: agent.Recommendation, *, compact: bool = False) -> None:
    if rec.memory_used:
        st.markdown("#### Personalized Recommendation")
        st.success("Hindsight memory: **ON**", icon="🧠")
    else:
        st.markdown("#### Generic Recommendation")
        st.warning("Hindsight memory: **OFF**", icon="🚫")

    rows = [
        ("Channel", rec.channel.upper()),
        ("Recipient", rec.recipient),
        ("Tone", rec.tone.title()),
        ("Timing", rec.suggested_timing),
        ("Approach", rec.approach),
    ]
    for label, value in rows:
        a, b = st.columns([1, 3] if compact else [1, 5])
        a.markdown(f"**{label}**")
        b.write(value)

    st.markdown("**Rationale**")
    st.write(rec.rationale)
    st.markdown(f"**Confidence:** {rec.confidence:.0%}")
    st.progress(min(max(rec.confidence, 0.0), 1.0))
    for w in rec.warnings:
        st.caption(f"⚠️ {w}")


def render_memories(rec: agent.Recommendation, customer_id: str) -> None:
    st.markdown("#### What PayRecall remembered")
    if rec.supporting_memories:
        for m in rec.supporting_memories:
            when = f" · {m['date']}" if m.get("date") else ""
            with st.container(border=True):
                st.markdown(f"**[{m.get('ref', '?')}]** `{m.get('type', 'memory')}`{when}")
                st.write(m.get("text", ""))
    else:
        st.info("No memories were found for this customer, so the agent fell back to a cautious default.")

    pb = load_playbook(customer_id)
    with st.expander("Learned customer playbook (Hindsight mental model)", expanded=False):
        if pb:
            refreshed = str(pb.get("last_refreshed_at") or "")[:16].replace("T", " ")
            st.caption(f"{pb.get('name', 'Playbook')} · refreshed {refreshed} UTC" if refreshed else pb.get("name", "Playbook"))
            st.markdown(pb["content"])
        else:
            st.write("No playbook has been learned for this customer yet.")


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #

def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9@. ]+", " ", str(text or "").lower()).strip()


def _same_recipient(a: str, b: str) -> bool:
    """Loose match: same email, or a shared name token of 3+ letters."""
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return True
    ta = {t for t in re.findall(r"[a-z]{3,}", na) if t not in {"the", "and", "accounts", "payable", "team", "manager", "head"}}
    tb = {t for t in re.findall(r"[a-z]{3,}", nb) if t not in {"the", "and", "accounts", "payable", "team", "manager", "head"}}
    return bool(ta & tb)


def diff_recommendations(off: agent.Recommendation, on: agent.Recommendation) -> list[dict[str, Any]]:
    """Field-by-field comparison; nothing here is customer-specific."""
    out = []
    for key, label in COMPARE_FIELDS:
        a, b = getattr(off, key), getattr(on, key)
        if key == "recipient":
            changed = not _same_recipient(a, b)
        elif key in ("channel", "tone"):
            changed = _norm(a) != _norm(b)
        else:
            changed = _norm(a) != _norm(b)
        out.append({"field": label, "key": key, "off": a, "on": b, "changed": changed})
    return out


def render_comparison(off: agent.Recommendation, on: agent.Recommendation, customer_id: str) -> None:
    left, right = st.columns(2, gap="large")
    with left:
        render_recommendation(off, compact=True)
    with right:
        render_recommendation(on, compact=True)
        st.divider()
        render_memories(on, customer_id)

    st.divider()
    st.markdown("### What changed because of memory?")
    diffs = diff_recommendations(off, on)
    changed = [d for d in diffs if d["changed"]]
    core = [d["field"] for d in changed if d["key"] in ("channel", "recipient", "tone")]
    if core:
        st.success(f"Memory changed the **{', '.join(core)}** for {on.customer} / {on.invoice}.")
    elif changed:
        st.info("Memory kept the same channel, recipient and tone but adjusted the wording and timing.")
    else:
        st.info("Memory did not change this recommendation.")

    for d in diffs:
        icon = "🔁" if d["changed"] else "✅"
        c0, c1, c2 = st.columns([1, 3, 3])
        c0.markdown(f"{icon} **{d['field']}**")
        c1.caption("MEMORY OFF")
        c1.write(d["off"])
        c2.caption("MEMORY ON")
        c2.write(d["on"])
    st.caption(f"Confidence: OFF {off.confidence:.0%} → ON {on.confidence:.0%}")


# --------------------------------------------------------------------------- #
# Live outcome learning
# --------------------------------------------------------------------------- #

def learning_key(invoice_id: str) -> str:
    return f"learning::{invoice_id}"


def find_new_memories(customer_id: str, document_ids: list[str], probe_text: str) -> list[dict[str, Any]]:
    """Poll recall until the memories extracted from the new documents are retrievable."""
    wanted = set(document_ids)
    for attempt in range(NEW_MEMORY_POLL_ATTEMPTS):
        hits = hm.recall_customer_memory(customer_id, query=probe_text, budget="low", max_tokens=1500)
        found = [h for h in hits if h.get("document_id") in wanted]
        if found:
            return found
        if attempt < NEW_MEMORY_POLL_ATTEMPTS - 1:
            time.sleep(NEW_MEMORY_POLL_SECONDS)
    return []


def log_outcome(customer: dict[str, Any], invoice: dict[str, Any], rec: agent.Recommendation,
                reply_text: str, resolution: str, outcome_date: date) -> dict[str, Any]:
    """Retain the action and the customer's reply, refresh the playbook, re-recommend.

    Raises hm.HindsightConfigError / hm.HindsightAPIError / agent.AgentError; the caller
    turns those into friendly messages. Nothing here touches customers.json.
    """
    outcome = RESOLUTIONS.get(resolution, "none")
    cid, inv_id = customer["id"], invoice["invoice_id"]
    warnings: list[str] = []

    action_narrative = (
        f"Following PayRecall's recommendation, the collections agent contacted {rec.recipient} "
        f"via {rec.channel} using a {rec.tone} tone regarding invoice {inv_id}. "
        f"Approach: {rec.approach} Timing: {rec.suggested_timing}"
    )
    action_doc = hm.retain_interaction(
        customer_id=cid, customer_name=customer["name"], invoice_id=inv_id,
        channel=rec.channel, contact=rec.recipient, tone=rec.tone, actor="agent",
        interaction_date=outcome_date, outcome=outcome, narrative=action_narrative,
    )
    reply_doc = hm.retain_interaction(
        customer_id=cid, customer_name=customer["name"], invoice_id=inv_id,
        channel=rec.channel, contact=rec.recipient, actor="customer",
        interaction_date=outcome_date, outcome=outcome,
        narrative=f"Customer response ({resolution}): {reply_text.strip()}",
    )
    doc_ids = [action_doc["document_id"], reply_doc["document_id"]]

    new_memories = find_new_memories(cid, doc_ids, reply_text)
    if not new_memories:
        warnings.append("The new outcome was stored, but Hindsight had not finished indexing it when the recommendation was regenerated.")

    playbook_refreshed = False
    try:
        hm.refresh_customer_playbook(cid, wait=True)
        playbook_refreshed = True
    except hm.HindsightAPIError as exc:
        warnings.append(f"Playbook could not be refreshed ({str(exc)[:70]}).")

    # Drop anything cached for this customer/invoice so the re-run cannot show stale results.
    load_playbook.clear()
    st.session_state.pop(result_key(inv_id, True), None)

    after = agent.recommend(customer, invoice, memory_enabled=True)
    st.session_state[result_key(inv_id, True)] = after

    return {
        "before": rec,
        "after": after,
        "outcome": {"resolution": resolution, "outcome_tag": outcome, "date": outcome_date.isoformat(), "text": reply_text.strip()},
        "document_ids": doc_ids,
        "new_memories": new_memories,
        "playbook_refreshed": playbook_refreshed,
        "warnings": warnings,
    }


def render_outcome_form(customer: dict[str, Any], invoice: dict[str, Any], rec: agent.Recommendation) -> None:
    st.markdown("### Log Customer Outcome")
    st.caption("Record what happened after this action. PayRecall retains it in Hindsight and re-plans.")
    processing = st.session_state.get("outcome_processing", False)
    with st.form(key=f"outcome_form::{invoice['invoice_id']}", clear_on_submit=False):
        reply_text = st.text_area(
            "Customer reply / outcome",
            placeholder="e.g. Kavita confirmed that Meridian will pay the invoice on 5 October.",
            height=90,
        )
        c1, c2 = st.columns(2)
        resolution = c1.selectbox("Resolution", list(RESOLUTIONS.keys()), index=0)
        outcome_date = c2.date_input("Outcome date", value=date.today())
        submitted = st.form_submit_button("Submit outcome and re-plan", type="primary", disabled=processing)

    if not submitted:
        return
    if not reply_text.strip():
        st.warning("Please describe the customer's reply or outcome before submitting.")
        return
    fingerprint = f"{invoice['invoice_id']}|{reply_text.strip()}|{resolution}|{outcome_date.isoformat()}"
    if st.session_state.get("last_outcome_fingerprint") == fingerprint:
        st.info("This outcome was already recorded. Change the text or date to log a new one.")
        return

    st.session_state["outcome_processing"] = True
    try:
        with st.spinner("Retaining outcome in Hindsight, refreshing the playbook and re-planning..."):
            entry = log_outcome(customer, invoice, rec, reply_text, resolution, outcome_date)
        st.session_state["last_outcome_fingerprint"] = fingerprint
        st.session_state[learning_key(invoice["invoice_id"])] = entry
        st.session_state["view"] = ("learning", invoice["invoice_id"])
    except hm.HindsightConfigError as exc:
        st.error(f"Configuration problem: {exc}")
    except hm.HindsightAPIError as exc:
        st.error(f"Hindsight could not store or refresh the memory. {exc}")
    except agent.AgentError as exc:
        st.error(f"The outcome was stored, but the new recommendation failed. {exc}")
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace
        log.exception("Unexpected error while logging an outcome")
        st.error(f"Unexpected error ({type(exc).__name__}). The previous recommendation is still shown above.")
    finally:
        st.session_state["outcome_processing"] = False


def render_learning(entry: dict[str, Any], customer_id: str) -> None:
    before: agent.Recommendation = entry["before"]
    after: agent.Recommendation = entry["after"]
    outcome = entry["outcome"]
    new_ids = {m.get("id") for m in entry["new_memories"]}

    st.success("**PayRecall learned from this outcome**", icon="🎓")
    with st.container(border=True):
        st.markdown(f"**Recorded outcome:** {outcome['resolution']} · {outcome['date']}")
        st.write(outcome["text"])
        st.caption("Stored in Hindsight as documents: " + ", ".join(f"`{d}`" for d in entry["document_ids"]))
        if entry["new_memories"]:
            st.markdown("**New memories extracted from this outcome (now retrievable):**")
            for m in entry["new_memories"]:
                st.markdown(f"🆕 `{m.get('type', 'memory')}` {m.get('text', '')}")
        st.caption(
            "Playbook refreshed from memory." if entry["playbook_refreshed"] else "Playbook was not refreshed."
        )
        for w in entry["warnings"]:
            st.caption(f"⚠️ {w}")

    st.markdown("### Before vs after learning")
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("#### BEFORE LEARNING")
        st.caption("Recommendation from seeded history only")
        render_recommendation(before, compact=True)
    with right:
        st.markdown("#### AFTER LEARNING")
        st.caption("Recommendation after retaining the new outcome")
        render_recommendation(after, compact=True)
        used_new = [m for m in after.supporting_memories if m.get("id") in new_ids]
        if used_new:
            st.info(f"The updated recommendation cites {len(used_new)} memory(ies) created from the outcome you just logged.", icon="🆕")

    st.markdown("### What changed because PayRecall learned?")
    diffs = diff_recommendations(before, after)
    conf_changed = round(before.confidence, 2) != round(after.confidence, 2)
    diffs.append({"field": "Confidence", "key": "confidence", "off": f"{before.confidence:.0%}", "on": f"{after.confidence:.0%}", "changed": conf_changed})
    changed = [d["field"] for d in diffs if d["changed"]]
    if changed:
        st.success(f"Changed after learning: **{', '.join(changed)}**.")
    else:
        st.info("The recommendation did not change. The outcome confirmed what PayRecall already believed.")
    for d in diffs:
        icon = "🔁" if d["changed"] else "✅"
        c0, c1, c2 = st.columns([1, 3, 3])
        c0.markdown(f"{icon} **{d['field']}**")
        c1.caption("BEFORE")
        c1.write(d["off"])
        c2.caption("AFTER")
        c2.write(d["on"])

    st.divider()
    st.markdown("#### What PayRecall remembers now")
    for m in after.supporting_memories:
        badge = "🆕 " if m.get("id") in new_ids else ""
        when = f" · {m['date']}" if m.get("date") else ""
        with st.container(border=True):
            st.markdown(f"{badge}**[{m.get('ref', '?')}]** `{m.get('type', 'memory')}`{when}")
            st.write(m.get("text", ""))
    pb = load_playbook(customer_id)
    with st.expander("Updated customer playbook", expanded=False):
        st.markdown(pb["content"] if pb else "No playbook has been learned for this customer yet.")


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def main() -> None:
    st.title("PayRecall")
    st.markdown("**Memory-powered accounts receivable collection assistant**")
    st.write(
        "PayRecall learns from previous customer interactions and uses that memory to "
        "recommend the next collection action."
    )

    try:
        data = load_data()
    except (FileNotFoundError, ValueError) as exc:
        st.error(f"Could not load the dataset: {exc}")
        return

    customers = data["customers"]
    invoices = data["invoices"]

    with st.sidebar:
        st.header("Setup")
        cust_names = [c["name"] for c in customers]
        cust_name = st.selectbox("Customer", cust_names, index=0)
        customer = next(c for c in customers if c["name"] == cust_name)
        cust_invoices = [i for i in invoices if i["customer_id"] == customer["id"]]
        if not cust_invoices:
            st.warning("No overdue invoices for this customer.")
            return
        inv_labels = {f"{i['invoice_id']} · {money(i.get('balance_due', i.get('amount')))} · {i.get('days_overdue', '?')}d overdue": i for i in cust_invoices}
        inv_label = st.selectbox("Invoice", list(inv_labels.keys()), index=0)
        invoice = inv_labels[inv_label]
        mode = st.radio("Memory mode", ["MEMORY OFF", "MEMORY ON"], index=1)
        memory_enabled = mode == "MEMORY ON"
        st.caption(f"LLM: {agent.groq_model()}")

    render_invoice(customer, invoice)
    st.divider()

    b1, b2, _ = st.columns([2, 2, 4])
    generate = b1.button("Generate Recommendation", type="primary", use_container_width=True)
    compare = b2.button("Compare OFF vs ON", use_container_width=True)

    if generate:
        rec = run_agent(customer, invoice, memory_enabled)
        if rec:
            st.session_state[result_key(invoice["invoice_id"], memory_enabled)] = rec
            st.session_state["view"] = ("single", invoice["invoice_id"], memory_enabled)

    if compare:
        off = run_agent(customer, invoice, False)
        on = run_agent(customer, invoice, True) if off else None
        if off and on:
            st.session_state[result_key(invoice["invoice_id"], False)] = off
            st.session_state[result_key(invoice["invoice_id"], True)] = on
            st.session_state["view"] = ("compare", invoice["invoice_id"])

    view = st.session_state.get("view")
    if view and view[1] == invoice["invoice_id"]:
        on_rec = st.session_state.get(result_key(invoice["invoice_id"], True))
        if view[0] == "single":
            rec = st.session_state.get(result_key(invoice["invoice_id"], view[2]))
            if rec:
                render_recommendation(rec)
                if rec.memory_used:
                    st.divider()
                    render_memories(rec, customer["id"])
        elif view[0] == "compare":
            off = st.session_state.get(result_key(invoice["invoice_id"], False))
            if off and on_rec:
                st.markdown("### MEMORY OFF vs MEMORY ON — same invoice, same LLM")
                render_comparison(off, on_rec, customer["id"])
        elif view[0] == "learning":
            entry = st.session_state.get(learning_key(invoice["invoice_id"]))
            if entry:
                render_learning(entry, customer["id"])
                on_rec = entry["after"]
        # Outcome logging is offered whenever a MEMORY ON recommendation is on screen.
        if on_rec and (view[0] != "single" or view[2]):
            st.divider()
            render_outcome_form(customer, invoice, on_rec)
            # A successful submit switches the view; show it immediately without a manual rerun.
            if st.session_state.get("view", view) != view:
                st.rerun()
    else:
        st.info("Choose a customer and invoice, then generate a recommendation or compare both modes.")

    st.divider()
    with st.expander("Why this matters", expanded=False):
        st.write(
            "Collections knowledge is usually tacit: one customer only pays after a call to the "
            "AP head, another disputes anything with a firm tone, a third pays on the month-end run "
            "regardless. Without memory, every reminder is generic. With Hindsight memory, the same "
            "invoice can produce a different action, because the agent remembers what worked and what "
            "backfired with this customer, and updates that picture when contacts or preferences change."
        )


main()
