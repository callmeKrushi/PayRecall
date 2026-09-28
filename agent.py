"""PayRecall decision agent.

Given an overdue invoice and its customer, produce a structured collections
recommendation answering WHO to contact, HOW, in WHAT tone, WHEN, with WHAT
approach, and WHY.

Two paths, same invoice, same LLM:

    MEMORY OFF -> generic recommendation from the invoice and a basic customer
                  profile only. Hindsight is never called.
    MEMORY ON  -> Hindsight recall (customer-scoped memories), the customer's
                  learned playbook mental model, and Hindsight reflect for an
                  evidence-based assessment; the LLM then composes the final
                  recommendation with citations to those memories.

The LLM layer is Groq. All Hindsight API calls stay inside hindsight_memory.py.

Run the local demo (does not write to the dataset or the Hindsight bank):

    python agent.py                # Meridian Retail INV-2041, OFF then ON
    python agent.py INV-2047       # another invoice
    python agent.py INV-2041 --off-only
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import textwrap
from dataclasses import asdict, dataclass, field
from typing import Any

from dotenv import load_dotenv

import hindsight_memory as hm

log = logging.getLogger("payrecall.agent")

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
LLM_TEMPERATURE = 0.2
LLM_MAX_TOKENS = 1200
MAX_MEMORIES_IN_PROMPT = 15
MAX_SUPPORTING_MEMORIES = 8

VALID_CHANNELS = ("email", "call", "whatsapp")
VALID_TONES = ("friendly", "polite", "neutral", "firm")


class AgentError(RuntimeError):
    """Base class for agent failures. Messages never contain secrets."""


class AgentConfigError(AgentError):
    """Missing Groq or Hindsight credentials."""


class AgentDataError(AgentError):
    """Customer or invoice not found in the dataset."""


class AgentMemoryError(AgentError):
    """Hindsight recall/reflect failed while memory was enabled."""


class AgentLLMError(AgentError):
    """The LLM call failed or returned unusable output."""


def _load_groq_key() -> str:
    """Return the Groq API key from GROQ_API_KEY, falling back to LLM_API_KEY."""
    load_dotenv(hm.ENV_PATH, override=False)
    key = (os.getenv("GROQ_API_KEY") or os.getenv("LLM_API_KEY") or "").strip()
    if not key:
        raise AgentConfigError(
            "Groq API key not found. Set GROQ_API_KEY (or LLM_API_KEY) in .env."
        )
    return key


def groq_model() -> str:
    load_dotenv(hm.ENV_PATH, override=False)
    return (os.getenv("GROQ_MODEL") or DEFAULT_GROQ_MODEL).strip()


_groq_client: Any = None


def _get_groq() -> Any:
    """Lazily build the Groq client (import kept local so the module loads without groq)."""
    global _groq_client
    if _groq_client is None:
        try:
            from groq import Groq
        except ImportError as exc:  # pragma: no cover
            raise AgentConfigError("The 'groq' package is not installed. Run: pip install -r requirements.txt") from exc
        _groq_client = Groq(api_key=_load_groq_key())
    return _groq_client


# --------------------------------------------------------------------------- #
# Output structure
# --------------------------------------------------------------------------- #

@dataclass
class Recommendation:
    customer: str
    invoice: str
    channel: str
    recipient: str
    tone: str
    approach: str
    suggested_timing: str
    rationale: str
    confidence: float
    supporting_memories: list[dict[str, Any]] = field(default_factory=list)
    memory_used: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


# --------------------------------------------------------------------------- #
# Dataset lookups
# --------------------------------------------------------------------------- #

def _dataset() -> dict[str, Any]:
    try:
        return hm.load_dataset()
    except (FileNotFoundError, ValueError) as exc:
        raise AgentDataError(str(exc)) from exc


def load_customer(customer: str | dict[str, Any]) -> dict[str, Any]:
    """Accept a customer dict, a customer id (CUST-001) or a customer name."""
    if isinstance(customer, dict):
        if "id" not in customer or "name" not in customer:
            raise AgentDataError("Customer dict must contain at least 'id' and 'name'.")
        return customer
    key = str(customer).strip().lower()
    for c in _dataset()["customers"]:
        if c["id"].lower() == key or c["name"].lower() == key:
            return c
    raise AgentDataError(f"Customer not found: {customer!r}")


def load_invoice(invoice: str | dict[str, Any]) -> dict[str, Any]:
    """Accept an invoice dict or an invoice id (INV-2041)."""
    if isinstance(invoice, dict):
        if "invoice_id" not in invoice:
            raise AgentDataError("Invoice dict must contain 'invoice_id'.")
        return invoice
    key = str(invoice).strip().lower()
    for inv in _dataset()["invoices"]:
        if inv["invoice_id"].lower() == key:
            return inv
    raise AgentDataError(f"Invoice not found: {invoice!r}")


def basic_profile(customer: dict[str, Any]) -> dict[str, Any]:
    """The customer facts a CRM would hold, with no collections history.

    Deliberately excludes free-text notes, stated payment habits and per-contact
    notes, because those encode learned history that only the memory path may use.
    """
    contacts = []
    for c in customer.get("contacts", []):
        if c.get("status", "active") != "active":
            continue
        contacts.append(
            {
                "name": c.get("name"),
                "role": c.get("role"),
                "email": c.get("email"),
                "has_phone": bool(c.get("phone")),
                "has_whatsapp": bool(c.get("whatsapp")),
            }
        )
    return {
        "id": customer["id"],
        "name": customer["name"],
        "industry": customer.get("industry"),
        "city": customer.get("city"),
        "customer_since": customer.get("customer_since"),
        "payment_terms_days": customer.get("payment_terms_days"),
        "msme_udyam_registered": customer.get("msme_udyam_registered"),
        "contacts": contacts,
    }


def reference_date() -> str:
    """The 'today' the agent reasons from, with weekday: dataset as_of date, else the real date."""
    import datetime as _dt

    try:
        raw = str(_dataset().get("meta", {}).get("as_of") or "")
        day = _dt.date.fromisoformat(raw) if raw else _dt.date.today()
    except (AgentDataError, ValueError):
        day = _dt.date.today()
    return f"{day.isoformat()} ({day.strftime('%A')})"


def invoice_summary(invoice: dict[str, Any]) -> dict[str, Any]:
    keys = ("invoice_id", "amount", "amount_paid", "balance_due", "invoice_date", "due_date", "days_overdue", "status", "description")
    return {k: invoice.get(k) for k in keys if k in invoice}


# --------------------------------------------------------------------------- #
# LLM layer (Groq)
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = textwrap.dedent(
    """
    You are PayRecall, a collections advisor for a B2B supplier in India.
    You recommend the single best next action to collect one overdue invoice.

    Rules:
    - Answer with ONE JSON object and nothing else. No prose, no markdown fences.
    - Keys (all required):
        "channel": one of "email", "call", "whatsapp"
        "recipient": the specific person or mailbox to contact
        "tone": one of "friendly", "polite", "neutral", "firm"
        "approach": the collection approach in one or two sentences (what you will ask for or offer)
        "suggested_timing": when to make contact, concrete (day/time window) where evidence allows
        "rationale": 3-6 sentences explaining WHO, HOW, TONE, WHEN, WHAT and WHY
        "confidence": number between 0 and 1
        "evidence_ids": list of the evidence ids (e.g. "M3") you relied on; [] if none were given
    - Never invent contacts, preferences or history. Use only what is provided.
    - Never threaten legal action; be commercially reasonable.
    - With no evidence about the customer, default to a polite tone and a standard
      reminder; reserve "firm" for cases where evidence shows softer approaches failed
      and firmness did not backfire.
    - If newer evidence contradicts older evidence, follow the newer evidence and say so.
    """
).strip()


def _extract_json(text: str) -> dict[str, Any]:
    """Parse the model output as JSON, tolerating code fences or leading prose."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        return json.loads(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("no JSON object found in response")


def _call_llm(user_prompt: str) -> dict[str, Any]:
    """Call Groq and return the parsed JSON object. Retries once without JSON mode."""
    client = _get_groq()
    model = groq_model()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}]
    last_error: Exception | None = None
    for attempt, use_json_mode in enumerate((True, False), start=1):
        kwargs: dict[str, Any] = {}
        if use_json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS,
                **kwargs,
            )
            content = resp.choices[0].message.content or ""
            return _extract_json(content)
        except Exception as exc:  # noqa: BLE001 - normalised below
            last_error = exc
            log.warning("LLM attempt %d failed: %s", attempt, type(exc).__name__)
    raise AgentLLMError(f"LLM call failed ({type(last_error).__name__}): {str(last_error)[:300]}")


def _coerce(raw: dict[str, Any], *, customer: str, invoice: str, memory_used: bool,
            evidence: list[dict[str, Any]], warnings: list[str]) -> Recommendation:
    """Validate and normalise the LLM JSON into a Recommendation."""
    def s(key: str, default: str = "") -> str:
        v = raw.get(key, default)
        return str(v).strip() if v is not None else default

    channel = s("channel").lower()
    if channel not in VALID_CHANNELS:
        warnings.append(f"LLM returned channel {channel!r}; defaulted to 'email'.")
        channel = "email"
    tone = s("tone").lower()
    if tone not in VALID_TONES:
        warnings.append(f"LLM returned tone {tone!r}; defaulted to 'polite'.")
        tone = "polite"
    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
        warnings.append("LLM confidence was not numeric; set to 0.")
    confidence = max(0.0, min(1.0, confidence))
    if not memory_used:
        confidence = min(confidence, 0.4)  # no evidence: never more than a guess
    elif not evidence:
        confidence = min(confidence, 0.35)  # memory on but nothing known about this customer

    cited = {str(e).upper() for e in (raw.get("evidence_ids") or [])}
    by_ref = {e["ref"]: e for e in evidence}
    supporting = [by_ref[r] for r in cited if r in by_ref]
    if memory_used and not supporting:
        supporting = evidence[:MAX_SUPPORTING_MEMORIES]  # fall back to what was shown to the LLM
    supporting = [{k: v for k, v in m.items()} for m in supporting[:MAX_SUPPORTING_MEMORIES]]

    return Recommendation(
        customer=customer,
        invoice=invoice,
        channel=channel,
        recipient=s("recipient", "accounts payable"),
        tone=tone,
        approach=s("approach"),
        suggested_timing=s("suggested_timing"),
        rationale=s("rationale"),
        confidence=round(confidence, 2),
        supporting_memories=supporting,
        memory_used=memory_used,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# MEMORY OFF
# --------------------------------------------------------------------------- #

def recommend_without_memory(customer: dict[str, Any], invoice: dict[str, Any]) -> Recommendation:
    """Baseline: invoice + basic profile only. Hindsight is never touched."""
    prompt = textwrap.dedent(
        f"""
        Today is {reference_date()}. No interaction history is available for this customer.
        Recommend a sensible first collections action from the facts below only.

        CUSTOMER (basic profile):
        {json.dumps(basic_profile(customer), indent=2)}

        INVOICE:
        {json.dumps(invoice_summary(invoice), indent=2)}

        EVIDENCE: none provided. Set "evidence_ids" to [] and keep confidence modest.
        """
    ).strip()
    raw = _call_llm(prompt)
    return _coerce(raw, customer=customer["name"], invoice=invoice["invoice_id"],
                   memory_used=False, evidence=[], warnings=[])


# --------------------------------------------------------------------------- #
# MEMORY ON
# --------------------------------------------------------------------------- #

def _memory_query(customer: dict[str, Any], invoice: dict[str, Any]) -> str:
    return (
        f"We need to collect invoice {invoice['invoice_id']} "
        f"(balance {invoice.get('balance_due', invoice.get('amount'))}, "
        f"{invoice.get('days_overdue', '?')} days overdue) from {customer['name']}. "
        f"Which channel, contact, tone, timing and approach have worked or failed with this customer, "
        f"and has the right contact or their preference changed recently?"
    )


def gather_memory_context(customer: dict[str, Any], invoice: dict[str, Any]) -> dict[str, Any]:
    """Pull recall results, the playbook mental model and a reflect assessment for the customer."""
    cid = customer["id"]
    query = _memory_query(customer, invoice)
    warnings: list[str] = []

    try:
        hm.initialize_memory(verify=False)
    except hm.HindsightConfigError as exc:
        raise AgentConfigError(str(exc)) from exc

    try:
        recalled = hm.recall_customer_memory(cid, query=query, budget="mid", max_tokens=3500)
    except hm.HindsightAPIError as exc:
        raise AgentMemoryError(f"Hindsight recall failed: {exc}") from exc

    # Observations (consolidated beliefs) first, then raw facts in relevance order.
    recalled.sort(key=lambda m: 0 if m.get("type") == "observation" else 1)
    recalled = recalled[:MAX_MEMORIES_IN_PROMPT]

    playbook = ""
    try:
        pb = hm.get_customer_playbook(cid)
        playbook = pb.get("content") or ""
    except hm.HindsightAPIError as exc:
        warnings.append(f"No playbook mental model available for {cid} ({str(exc)[:80]}).")

    reflection: dict[str, Any] = {"text": "", "based_on": []}
    if recalled:
        # Reflect occasionally fails server-side mid-generation; one retry is usually enough.
        for attempt in (1, 2):
            try:
                reflection = hm.reflect_customer(
                    cid,
                    query,
                    context=f"Invoice under collection: {json.dumps(invoice_summary(invoice))}",
                    budget="mid",
                    max_tokens=700,
                )
                break
            except hm.HindsightAPIError as exc:
                if attempt == 2:
                    warnings.append(f"Hindsight reflect unavailable; used recall and playbook only ({str(exc)[:80]}).")

    # Evidence list shown to the LLM, each with a short ref id it can cite.
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in recalled:
        text = (m.get("text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        evidence.append(
            {
                "ref": f"M{len(evidence) + 1}",
                "id": m.get("id"),
                "type": m.get("type"),
                "date": (m.get("occurred_start") or "")[:10] or None,
                "text": text,
            }
        )
    for f in reflection.get("based_on", []):
        text = (f.get("text") or "").strip()
        ftype = str(f.get("type") or "").lower()
        if not text or text in seen or "mental" in ftype or "directive" in ftype:
            continue  # the playbook and rules are supplied separately, not cited as memories
        seen.add(text)
        evidence.append(
            {
                "ref": f"M{len(evidence) + 1}",
                "id": f.get("id"),
                "type": f.get("type"),
                "date": (f.get("occurred_start") or "")[:10] or None,
                "text": text,
            }
        )

    return {
        "query": query,
        "evidence": evidence,
        "playbook": playbook,
        "reflection": reflection.get("text", ""),
        "warnings": warnings,
    }


def recommend_with_memory(customer: dict[str, Any], invoice: dict[str, Any]) -> Recommendation:
    """Personalised recommendation grounded in Hindsight memories for this customer."""
    ctx = gather_memory_context(customer, invoice)
    evidence, warnings = ctx["evidence"], ctx["warnings"]

    if not evidence and not ctx["playbook"]:
        warnings.append("No memories found for this customer; treated as a new customer.")

    evidence_block = "\n".join(
        f"[{e['ref']}] ({e['type']}{', ' + e['date'] if e['date'] else ''}) {e['text']}" for e in evidence
    ) or "none"
    prompt = textwrap.dedent(
        f"""
        Today is {reference_date()}. Recommend the next collections action using the
        remembered history below. Cite the evidence ids you rely on. Newer evidence overrides
        older evidence. Make suggested_timing a real calendar date/time on or after today.

        CUSTOMER (basic profile):
        {json.dumps(basic_profile(customer), indent=2)}

        INVOICE:
        {json.dumps(invoice_summary(invoice), indent=2)}

        LEARNED PLAYBOOK for this customer (from memory; may be empty):
        {ctx['playbook'] or 'none'}

        MEMORY ASSESSMENT (Hindsight reflect; may be empty):
        {ctx['reflection'] or 'none'}

        EVIDENCE (remembered facts and observations, newest dates matter most):
        {evidence_block}

        If the evidence is empty, recommend a cautious default and keep confidence low.
        """
    ).strip()
    raw = _call_llm(prompt)
    return _coerce(raw, customer=customer["name"], invoice=invoice["invoice_id"],
                   memory_used=True, evidence=evidence, warnings=warnings)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def recommend(customer: str | dict[str, Any], invoice: str | dict[str, Any], memory_enabled: bool = True) -> Recommendation:
    """Produce a recommendation for one invoice.

    ``customer`` and ``invoice`` may be ids, names (customer only) or dicts.
    With ``memory_enabled=False`` Hindsight is never contacted.
    """
    cust = load_customer(customer)
    inv = load_invoice(invoice)
    if inv.get("customer_id") and inv["customer_id"] != cust["id"]:
        raise AgentDataError(f"Invoice {inv['invoice_id']} belongs to {inv['customer_id']}, not {cust['id']}.")
    _load_groq_key()  # fail early and clearly if the LLM key is missing
    if memory_enabled:
        return recommend_with_memory(cust, inv)
    return recommend_without_memory(cust, inv)


# --------------------------------------------------------------------------- #
# Local demo / test
# --------------------------------------------------------------------------- #

def format_recommendation(rec: Recommendation) -> str:
    lines = [
        f"Customer : {rec.customer}    Invoice: {rec.invoice}    Memory: {'ON' if rec.memory_used else 'OFF'}",
        f"WHO      : {rec.recipient}",
        f"HOW      : {rec.channel}",
        f"TONE     : {rec.tone}",
        f"WHEN     : {rec.suggested_timing}",
        f"WHAT     : {rec.approach}",
        f"WHY      : {rec.rationale}",
        f"Confidence: {rec.confidence}",
    ]
    if rec.supporting_memories:
        lines.append("Supporting memories:")
        for m in rec.supporting_memories:
            when = f" {m['date']}" if m.get("date") else ""
            lines.append(f"  - [{m['ref']}] ({m['type']}{when}) {m['text'][:160]}")
    if rec.warnings:
        lines.append("Warnings: " + "; ".join(rec.warnings))
    return "\n".join(lines)


def demo(invoice_id: str = "INV-2041", run_off: bool = True, run_on: bool = True) -> dict[str, Recommendation]:
    """Run MEMORY OFF and MEMORY ON for one invoice and print both. Read-only."""
    inv = load_invoice(invoice_id)
    cust = load_customer(inv["customer_id"])
    out: dict[str, Recommendation] = {}
    print(f"=== PayRecall demo: {cust['name']} / {inv['invoice_id']} (LLM: {groq_model()}) ===\n")
    if run_off:
        out["off"] = recommend(cust, inv, memory_enabled=False)
        print("---- MEMORY OFF ----")
        print(format_recommendation(out["off"]), "\n")
    if run_on:
        out["on"] = recommend(cust, inv, memory_enabled=True)
        print("---- MEMORY ON ----")
        print(format_recommendation(out["on"]), "\n")
    if run_off and run_on:
        a, b = out["off"], out["on"]
        changed = [k for k in ("channel", "recipient", "tone") if getattr(a, k) != getattr(b, k)]
        print("Changed by memory:", ", ".join(changed) if changed else "nothing (same channel/recipient/tone)")
    return out


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="PayRecall decision agent demo")
    parser.add_argument("invoice_id", nargs="?", default="INV-2041")
    parser.add_argument("--off-only", action="store_true")
    parser.add_argument("--on-only", action="store_true")
    parser.add_argument("--json", action="store_true", help="print recommendations as JSON")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        result = demo(args.invoice_id, run_off=not args.on_only, run_on=not args.off_only)
    except AgentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        hm.close_memory()
    if args.json:
        print(json.dumps({k: v.to_dict() for k, v in result.items()}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
