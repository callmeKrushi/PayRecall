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

def render_invoice(customer: dict[str, Any], invoice: dict[str, Any]) -> None:
    st.subheader("Selected invoice")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Customer", customer["name"])
    c2.metric("Invoice", invoice["invoice_id"])
    c3.metric("Amount", money(invoice.get("balance_due", invoice.get("amount"))))
    c4.metric("Due date", invoice.get("due_date", "-"))
    c5.metric("Days overdue", invoice.get("days_overdue", "-"))
    c6.metric("Status", str(invoice.get("status", "-")).title())
    if invoice.get("description"):
        st.caption(invoice["description"])


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
        if view[0] == "single":
            rec = st.session_state.get(result_key(invoice["invoice_id"], view[2]))
            if rec:
                render_recommendation(rec)
                if rec.memory_used:
                    st.divider()
                    render_memories(rec, customer["id"])
        else:
            off = st.session_state.get(result_key(invoice["invoice_id"], False))
            on = st.session_state.get(result_key(invoice["invoice_id"], True))
            if off and on:
                st.markdown("### MEMORY OFF vs MEMORY ON — same invoice, same LLM")
                render_comparison(off, on, customer["id"])
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
