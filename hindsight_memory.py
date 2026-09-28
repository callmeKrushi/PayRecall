"""Hindsight memory wrapper for PayRecall.

All Hindsight-specific API calls live in this module. The rest of the app
(agent, Streamlit UI) talks to these plain functions and never imports the
hindsight-client package directly.

Public surface
--------------
- initialize_memory()        -> MemoryStatus   (loads .env, builds client, checks the bank)
- retain_interaction(...)    -> dict           (stores one interaction as a memory)
- recall_customer_memory(...)-> list[dict]     (recalls memories tagged to one customer)
- seed_customer_history(...) -> dict           (seeds data/customers.json history, idempotent)
- get_bank_status()          -> dict           (document / memory counts)
- load_dataset()             -> dict           (parsed data/customers.json)
- close_memory()             -> None

Nothing is seeded on import. Seeding only happens when
``seed_customer_history`` is called explicitly.

Secrets are never logged or returned by any function here. ``MemoryStatus``
reports whether the API key is present, never its value.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

try:  # Imported lazily-tolerant so a missing package gives a clear message.
    from hindsight_client import Hindsight
    from hindsight_client_api.exceptions import ApiException
except ImportError as exc:  # pragma: no cover - environment problem
    raise ImportError(
        "hindsight-client is not installed. Run: pip install -r requirements.txt"
    ) from exc

log = logging.getLogger("payrecall.hindsight")

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

PROJECT_DIR = Path(__file__).resolve().parent
ENV_PATH = PROJECT_DIR / ".env"
DATA_PATH = PROJECT_DIR / "data" / "customers.json"

DEFAULT_BASE_URL = "https://api.hindsight.vectorize.io"
REQUEST_TIMEOUT_SECONDS = 120.0

# Every seeded historical interaction is stored as its own Hindsight document
# with a deterministic id, so re-running the seed can never create duplicates.
SEED_DOC_PREFIX = "payrecall-hist-"
LIVE_DOC_PREFIX = "payrecall-live-"


class HindsightConfigError(RuntimeError):
    """Raised when required environment variables are missing."""


class HindsightAPIError(RuntimeError):
    """Raised when a Hindsight API call fails. Message never contains secrets."""


@dataclass
class MemoryConfig:
    base_url: str
    bank_id: str
    api_key: str = field(repr=False)  # never printed via repr()

    def __repr__(self) -> str:  # defensive: keep the key out of any log line
        return f"MemoryConfig(base_url={self.base_url!r}, bank_id={self.bank_id!r}, api_key=<hidden>)"


@dataclass
class MemoryStatus:
    base_url: str
    bank_id: str
    api_key_present: bool
    api_version: str | None
    bank_reachable: bool
    observations_enabled: bool | None
    auto_consolidation_enabled: bool | None
    document_count: int | None
    memory_count: int | None


def load_config(env_path: Path | None = None) -> MemoryConfig:
    """Load HINDSIGHT_* variables from .env (explicit path, so it works from any cwd).

    Raises HindsightConfigError if the API key or bank id is missing.
    """
    load_dotenv(env_path or ENV_PATH, override=False)

    api_key = (os.getenv("HINDSIGHT_API_KEY") or "").strip()
    bank_id = (os.getenv("HINDSIGHT_BANK_ID") or "").strip()
    base_url = (os.getenv("HINDSIGHT_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")

    missing = [name for name, val in (("HINDSIGHT_API_KEY", api_key), ("HINDSIGHT_BANK_ID", bank_id)) if not val]
    if missing:
        raise HindsightConfigError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            f"Copy .env.example to .env and fill them in."
        )
    return MemoryConfig(base_url=base_url, bank_id=bank_id, api_key=api_key)


# --------------------------------------------------------------------------- #
# Background event loop
# --------------------------------------------------------------------------- #
# The Hindsight client owns an aiohttp session that is bound to the event loop it
# first runs on. Streamlit (and any threaded host) calls us from a different thread
# on every rerun, so every call is executed on one long-lived private loop.

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="payrecall-hindsight-loop", daemon=True).start()
        return _loop


def _run(coro, timeout: float | None = None):
    """Run a coroutine on the private loop from any thread and return its result."""
    return asyncio.run_coroutine_threadsafe(coro, _ensure_loop()).result(timeout)


# --------------------------------------------------------------------------- #
# Client lifecycle
# --------------------------------------------------------------------------- #

_client: Hindsight | None = None
_config: MemoryConfig | None = None


def _wrap_api_error(action: str, exc: Exception) -> HindsightAPIError:
    """Convert client exceptions into a HindsightAPIError with a safe message."""
    if isinstance(exc, ApiException):
        detail = ""
        try:
            body = json.loads(exc.body) if exc.body else {}
            detail = body.get("detail") or ""
        except Exception:  # noqa: BLE001 - body may not be JSON
            detail = (exc.body or "")[:200] if isinstance(exc.body, str) else ""
        status = exc.status
        if status in (401, 403):
            hint = "Authentication failed. Check HINDSIGHT_API_KEY."
        elif status == 404:
            hint = "Resource not found. Check HINDSIGHT_BANK_ID."
        elif status in (429, 503):
            hint = "Hindsight is rate limiting or at capacity. Retry shortly."
        else:
            hint = ""
        msg = f"{action} failed (HTTP {status}). {hint} {detail}".strip()
        return HindsightAPIError(msg)
    return HindsightAPIError(f"{action} failed: {type(exc).__name__}: {exc}")


def get_client() -> Hindsight:
    """Return the cached Hindsight client, creating it on first use."""
    global _client, _config
    if _client is None:
        _config = load_config()
        cfg = _config

        async def _make() -> Hindsight:  # constructed on the private loop
            return Hindsight(
                base_url=cfg.base_url,
                api_key=cfg.api_key,
                timeout=REQUEST_TIMEOUT_SECONDS,
                user_agent="payrecall/0.1",
            )

        _client = _run(_make())
        log.info("Hindsight client created for bank %r at %s", _config.bank_id, _config.base_url)
    return _client


def bank_id() -> str:
    get_client()
    assert _config is not None
    return _config.bank_id


def close_memory() -> None:
    """Close the underlying HTTP session (safe to call multiple times)."""
    global _client, _config
    if _client is not None:
        try:
            _run(_client.aclose())
        except Exception as exc:  # noqa: BLE001 - closing is best-effort
            log.debug("Ignoring error while closing Hindsight client: %s", type(exc).__name__)
        _client = None
        _config = None


def get_bank_status() -> dict[str, int | None]:
    """Return document and memory-unit counts for the configured bank."""
    client = get_client()
    bid = bank_id()
    try:
        docs = _run(client.documents.list_documents(bid, limit=1))
        mems = _run(client.alist_memories(bid, limit=1))
    except Exception as exc:  # noqa: BLE001
        raise _wrap_api_error("Bank status check", exc) from exc
    return {
        "document_count": getattr(docs, "total", None),
        "memory_count": getattr(mems, "total", None),
    }


def initialize_memory(verify: bool = True) -> MemoryStatus:
    """Load credentials, build the client and (optionally) verify the bank is reachable.

    Never prints or returns the API key. Raises HindsightConfigError for missing
    credentials and HindsightAPIError if the server or bank cannot be reached.
    """
    client = get_client()
    assert _config is not None
    status = MemoryStatus(
        base_url=_config.base_url,
        bank_id=_config.bank_id,
        api_key_present=bool(_config.api_key),
        api_version=None,
        bank_reachable=False,
        observations_enabled=None,
        auto_consolidation_enabled=None,
        document_count=None,
        memory_count=None,
    )
    if not verify:
        return status

    try:
        version = _run(client.aget_version())
        status.api_version = getattr(version, "api_version", None)
    except Exception as exc:  # noqa: BLE001
        raise _wrap_api_error("Hindsight version check", exc) from exc

    try:
        cfg = _run(client.aget_bank_config(_config.bank_id))
    except Exception as exc:  # noqa: BLE001
        raise _wrap_api_error(f"Access to bank {_config.bank_id!r}", exc) from exc

    inner = cfg.get("config", cfg) if isinstance(cfg, dict) else {}
    status.bank_reachable = True
    status.observations_enabled = inner.get("enable_observations")
    status.auto_consolidation_enabled = inner.get("enable_auto_consolidation")

    counts = get_bank_status()
    status.document_count = counts["document_count"]
    status.memory_count = counts["memory_count"]
    return status


# --------------------------------------------------------------------------- #
# Dataset helpers
# --------------------------------------------------------------------------- #

def load_dataset(path: Path | None = None) -> dict[str, Any]:
    """Load data/customers.json (customers, invoices, interactions)."""
    p = path or DATA_PATH
    if not p.exists():
        raise FileNotFoundError(f"Dataset not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    for key in ("customers", "invoices", "interactions"):
        if key not in data:
            raise ValueError(f"Dataset {p} is missing the '{key}' array")
    return data


def customer_name_lookup(data: dict[str, Any]) -> dict[str, str]:
    return {c["id"]: c["name"] for c in data["customers"]}


def _to_timestamp(value: str | date | datetime | None) -> datetime:
    """Normalise an ISO date/datetime (or None = now) to a UTC-aware datetime."""
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time(hour=12), tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        if parsed.time() == time(0):
            parsed = parsed.replace(hour=12)  # midday so it lands on the right date in any tz
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def build_memory_item(
    *,
    customer_id: str,
    customer_name: str,
    invoice_id: str | None,
    interaction_date: str | date | datetime | None,
    channel: str,
    contact: str | None,
    narrative: str,
    outcome: str | None,
    actor: str = "agent",
    tone: str | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    """Build one retain item that preserves the narrative plus structured fields.

    The narrative is kept verbatim inside ``content``; the structured fields are
    repeated in ``metadata`` and ``tags`` so recall/reflect can filter on them.
    """
    ts = _to_timestamp(interaction_date)
    day = ts.date().isoformat()
    actor_label = "PayRecall collections agent" if actor == "agent" else f"{customer_name} (customer)"

    header_lines = [
        f"Customer: {customer_name} ({customer_id})",
        f"Date: {day}",
        f"Invoice: {invoice_id or 'n/a'}",
        f"Channel: {channel}",
        f"Contact: {contact or 'n/a'}",
        f"Actor: {actor_label}",
    ]
    if tone:
        header_lines.append(f"Tone: {tone}")
    header_lines.append(f"Outcome: {outcome or 'none'}")
    content = "\n".join(header_lines) + "\n\n" + narrative.strip()

    if actor == "agent":
        context = (
            f"Collections action taken by the PayRecall agent on {day} for {customer_name}, "
            f"invoice {invoice_id or 'n/a'}, via {channel} to {contact or 'unknown contact'}. "
            f"Result: {outcome or 'none'}."
        )
    else:
        context = (
            f"Response or payment event from the customer {customer_name} on {day} "
            f"for invoice {invoice_id or 'n/a'}, via {channel}, from {contact or 'unknown contact'}. "
            f"Result: {outcome or 'none'}."
        )

    tags = [f"customer:{customer_id}", f"channel:{channel}", f"actor:{actor}"]
    if invoice_id:
        tags.append(f"invoice:{invoice_id}")
    if outcome:
        tags.append(f"outcome:{outcome}")

    metadata = {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "interaction_date": day,
        "channel": channel,
        "contact": contact or "",
        "invoice_id": invoice_id or "",
        "outcome": outcome or "",
        "actor": actor,
        "tone": tone or "",
    }

    item: dict[str, Any] = {
        "content": content,
        "timestamp": ts,
        "context": context,
        "metadata": metadata,
        "tags": tags,
    }
    if document_id:
        item["document_id"] = document_id
    return item


def _interaction_to_item(rec: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    return build_memory_item(
        customer_id=rec["customer_id"],
        customer_name=names.get(rec["customer_id"], rec["customer_id"]),
        invoice_id=rec.get("invoice_id"),
        interaction_date=rec.get("date"),
        channel=rec.get("channel", "unknown"),
        contact=rec.get("contact"),
        narrative=rec.get("content", ""),
        outcome=rec.get("outcome"),
        actor=rec.get("actor", "agent"),
        tone=rec.get("tone"),
        document_id=f"{SEED_DOC_PREFIX}{rec['id']}",
    )


# --------------------------------------------------------------------------- #
# Retain
# --------------------------------------------------------------------------- #

def retain_interaction(
    *,
    customer_id: str,
    channel: str,
    narrative: str,
    outcome: str | None = None,
    invoice_id: str | None = None,
    contact: str | None = None,
    interaction_date: str | date | datetime | None = None,
    actor: str = "agent",
    tone: str | None = None,
    customer_name: str | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    """Store a single interaction (agent action or customer reply) in Hindsight.

    ``document_id`` defaults to a fresh ``payrecall-live-<uuid>`` so live
    outcomes are always new documents. Pass an explicit id to make the call
    idempotent (re-sending replaces rather than duplicates).
    """
    client = get_client()
    bid = bank_id()
    if customer_name is None:
        try:
            customer_name = customer_name_lookup(load_dataset()).get(customer_id, customer_id)
        except (FileNotFoundError, ValueError):
            customer_name = customer_id

    doc_id = document_id or f"{LIVE_DOC_PREFIX}{uuid.uuid4().hex[:12]}"
    item = build_memory_item(
        customer_id=customer_id,
        customer_name=customer_name,
        invoice_id=invoice_id,
        interaction_date=interaction_date,
        channel=channel,
        contact=contact,
        narrative=narrative,
        outcome=outcome,
        actor=actor,
        tone=tone,
        document_id=doc_id,
    )
    try:
        resp = _run(client.aretain(
            bank_id=bid,
            content=item["content"],
            timestamp=item["timestamp"],
            context=item["context"],
            document_id=doc_id,
            metadata=item["metadata"],
            tags=item["tags"],
            update_mode="replace",
        ))
    except Exception as exc:  # noqa: BLE001
        raise _wrap_api_error("Retain", exc) from exc

    return {
        "success": bool(getattr(resp, "success", False)),
        "document_id": doc_id,
        "items_count": getattr(resp, "items_count", None),
        "tags": item["tags"],
    }


# --------------------------------------------------------------------------- #
# Recall
# --------------------------------------------------------------------------- #

def recall_customer_memory(
    customer_id: str,
    query: str | None = None,
    *,
    types: Iterable[str] | None = None,
    max_tokens: int = 4096,
    budget: str = "mid",
    invoice_id: str | None = None,
) -> list[dict[str, Any]]:
    """Recall memories tagged to one customer, returned as plain dicts.

    Uses strict tag matching so memories from other customers (and untagged
    memories) are never mixed in.
    """
    client = get_client()
    bid = bank_id()
    tags = [f"customer:{customer_id}"]
    if invoice_id:
        tags.append(f"invoice:{invoice_id}")
    q = query or (
        f"Everything we know about collecting overdue invoices from customer {customer_id}: "
        f"which channels and contacts worked, what backfired, disputes, promises and payments."
    )
    try:
        resp = _run(client.arecall(
            bank_id=bid,
            query=q,
            types=list(types) if types else None,
            max_tokens=max_tokens,
            budget=budget,
            tags=tags,
            tags_match="all_strict",
        ))
    except Exception as exc:  # noqa: BLE001
        raise _wrap_api_error("Recall", exc) from exc

    out: list[dict[str, Any]] = []
    for r in getattr(resp, "results", []) or []:
        out.append(
            {
                "id": getattr(r, "id", None),
                "type": getattr(r, "type", None),
                "text": getattr(r, "text", ""),
                "context": getattr(r, "context", None),
                "occurred_start": getattr(r, "occurred_start", None),
                "document_id": getattr(r, "document_id", None),
                "tags": list(getattr(r, "tags", None) or []),
                "metadata": dict(getattr(r, "metadata", None) or {}),
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Seeding (explicit only)
# --------------------------------------------------------------------------- #

def list_seeded_document_ids() -> set[str]:
    """Return the ids of historical documents already present in the bank."""
    client = get_client()
    bid = bank_id()
    found: set[str] = set()
    offset, page = 0, 200
    try:
        while True:
            resp = _run(client.documents.list_documents(bid, q=SEED_DOC_PREFIX, limit=page, offset=offset))
            items = getattr(resp, "items", None) or []
            found.update(d.id for d in items if str(d.id).startswith(SEED_DOC_PREFIX))
            if len(items) < page:
                break
            offset += page
    except Exception as exc:  # noqa: BLE001
        raise _wrap_api_error("Listing seeded documents", exc) from exc
    return found


def seed_customer_history(
    customer_id: str | None = None,
    *,
    dry_run: bool = False,
    force: bool = False,
    batch_size: int = 10,
) -> dict[str, Any]:
    """Seed historical interactions from data/customers.json into Hindsight.

    - ``customer_id=None`` seeds every customer; otherwise only that customer.
    - Idempotent: interactions whose document id already exists in the bank are
      skipped unless ``force=True`` (which replaces them).
    - ``dry_run=True`` reports what would be sent without calling retain.

    This function is never called on import.
    """
    data = load_dataset()
    names = customer_name_lookup(data)
    records = [r for r in data["interactions"] if customer_id is None or r["customer_id"] == customer_id]
    records.sort(key=lambda r: (r.get("date", ""), r.get("id", "")))

    existing = list_seeded_document_ids()
    items: list[dict[str, Any]] = []
    skipped: list[str] = []
    for rec in records:
        item = _interaction_to_item(rec, names)
        if item["document_id"] in existing and not force:
            skipped.append(item["document_id"])
            continue
        if force:
            item["update_mode"] = "replace"
        items.append(item)

    summary: dict[str, Any] = {
        "customer_id": customer_id or "ALL",
        "requested": len(records),
        "already_present": len(skipped),
        "to_send": len(items),
        "sent": 0,
        "dry_run": dry_run,
        "document_ids": [it["document_id"] for it in items],
    }
    if dry_run or not items:
        return summary

    client = get_client()
    bid = bank_id()
    sent = 0
    for start in range(0, len(items), batch_size):
        chunk = items[start : start + batch_size]
        try:
            resp = _run(client.aretain_batch(bank_id=bid, items=chunk))
        except Exception as exc:  # noqa: BLE001
            summary["sent"] = sent
            raise _wrap_api_error(f"Seeding batch starting at item {start}", exc) from exc
        sent += int(getattr(resp, "items_count", None) or len(chunk))
    summary["sent"] = sent
    return summary


def delete_document(document_id: str) -> bool:
    """Delete one document (and its memories) from the bank. Used for cleanup/tests."""
    client = get_client()
    bid = bank_id()
    try:
        _run(client.documents.delete_document(bid, document_id))
    except Exception as exc:  # noqa: BLE001
        raise _wrap_api_error(f"Deleting document {document_id!r}", exc) from exc
    return True


# --------------------------------------------------------------------------- #
# Learning layer: bank configuration, observations, customer playbooks
# --------------------------------------------------------------------------- #

OBSERVATIONS_MISSION = (
    "Identify reliable patterns in collection interactions for each customer, including which "
    "communication channels, contacts, tones, timing patterns and collection approaches have "
    "historically resulted in payment, no response, promises to pay, or disputes. Preserve "
    "contradictions and update beliefs when customer contacts or preferences change. Prefer the "
    "most recent evidence when older information conflicts, and say so explicitly. Count how many "
    "times an approach worked or failed. Never invent a customer preference that the evidence does "
    "not show."
)

REFLECT_MISSION = (
    "Help a B2B collections agent make evidence-based next-action recommendations using remembered "
    "customer history and outcomes. Be factual and cautious about uncertainty: cite the interactions "
    "that support each conclusion, distinguish what is known from what is assumed, prefer recent "
    "evidence when older information conflicts, and never invent customer preferences or contacts "
    "that the memories do not support. Say clearly when there is little or no history."
)

# Disposition traits are integers 1-5 (see Hindsight.update_bank_config docstring).
# skepticism 4: evidence-based, does not take claims at face value.
# literalism 4: sticks to what the record says instead of extrapolating preferences.
# empathy 3: keeps enough emotional context to notice tone backfires.
BANK_DISPOSITION = {
    "disposition_skepticism": 4,
    "disposition_literalism": 4,
    "disposition_empathy": 3,
}

PLAYBOOK_QUESTIONS = (
    "What communication methods have worked? "
    "What methods have failed? "
    "Which contacts are relevant, and has that changed? "
    "Which tones should be avoided, and why? "
    "What timing or channel preferences are known? "
    "What has changed recently? "
    "What evidence supports each conclusion (cite dates, invoices and outcomes)? "
    "Where evidence is thin or contradictory, say so rather than guessing."
)


def configure_bank() -> dict[str, Any]:
    """Apply PayRecall's observation mission, reflect mission and disposition to the bank.

    Returns the bank-level overrides Hindsight now holds (no secrets inside).
    """
    client = get_client()
    bid = bank_id()
    try:
        result = _run(client.aupdate_bank_config(
            bid,
            observations_mission=OBSERVATIONS_MISSION,
            reflect_mission=REFLECT_MISSION,
            **BANK_DISPOSITION,
        ))
    except Exception as exc:  # noqa: BLE001
        raise _wrap_api_error("Bank configuration update", exc) from exc
    return result.get("overrides", result) if isinstance(result, dict) else {}


def get_bank_overrides() -> dict[str, Any]:
    """Return the bank-level configuration overrides currently stored in Hindsight."""
    client = get_client()
    try:
        cfg = _run(client.aget_bank_config(bank_id()))
    except Exception as exc:  # noqa: BLE001
        raise _wrap_api_error("Reading bank configuration", exc) from exc
    return cfg.get("overrides", {}) if isinstance(cfg, dict) else {}


def wait_for_operation(operation_id: str | None, timeout: float = 300.0, poll: float = 3.0) -> dict[str, Any]:
    """Block until a background Hindsight operation finishes. Returns its final status dict."""
    import time as _time

    if not operation_id:
        return {"status": "none"}
    client = get_client()
    bid = bank_id()
    deadline = _time.monotonic() + timeout
    last: dict[str, Any] = {}
    while True:
        try:
            st = _run(client.operations.get_operation_status(bid, operation_id))
        except Exception as exc:  # noqa: BLE001
            raise _wrap_api_error(f"Checking operation {operation_id}", exc) from exc
        last = {
            "operation_id": operation_id,
            "status": getattr(st, "status", None),
            "type": getattr(st, "operation_type", None),
            "error": getattr(st, "error_message", None),
        }
        status = str(last["status"] or "").lower()
        if status in ("completed", "succeeded", "success", "done"):
            return last
        if status in ("failed", "error", "cancelled", "canceled"):
            raise HindsightAPIError(f"Operation {operation_id} ended with status {status}: {last['error']}")
        if _time.monotonic() > deadline:
            raise HindsightAPIError(f"Operation {operation_id} still {status or 'pending'} after {timeout:.0f}s")
        _time.sleep(poll)


def rebuild_observations(wait: bool = True) -> dict[str, Any]:
    """Clear existing observations and re-consolidate under the current observations mission.

    Raw world/experience facts are untouched; only the derived observation layer is rebuilt.
    """
    client = get_client()
    bid = bank_id()
    try:
        _run(client.banks.clear_observations(bid))
        resp = _run(client.banks.trigger_consolidation(bid))
    except Exception as exc:  # noqa: BLE001
        raise _wrap_api_error("Rebuilding observations", exc) from exc
    op_id = getattr(resp, "operation_id", None)
    out: dict[str, Any] = {"operation_id": op_id, "status": getattr(resp, "status", None)}
    if wait and op_id:
        out["final"] = wait_for_operation(op_id)
    return out


def playbook_model_id(customer_id: str) -> str:
    return f"playbook-{customer_id.lower()}"


def ensure_customer_playbook(customer_id: str, customer_name: str | None = None, wait: bool = True) -> dict[str, Any]:
    """Create the '<customer> collection playbook' mental model if it does not exist.

    The model's content is generated by Hindsight from the customer's memories via
    ``source_query``; nothing is hardcoded. It is tagged to the customer and set to
    refresh automatically after each consolidation.
    """
    client = get_client()
    bid = bank_id()
    mid = playbook_model_id(customer_id)
    if customer_name is None:
        try:
            customer_name = customer_name_lookup(load_dataset()).get(customer_id, customer_id)
        except (FileNotFoundError, ValueError):
            customer_name = customer_id

    try:
        existing = _run(client.alist_mental_models(bid, tags=[f"customer:{customer_id}"], detail="metadata"))
    except Exception as exc:  # noqa: BLE001
        raise _wrap_api_error("Listing mental models", exc) from exc
    for m in getattr(existing, "items", None) or []:
        if getattr(m, "id", None) == mid:
            return {"mental_model_id": mid, "created": False, "operation": None}

    source_query = (
        f"Build the collection playbook for {customer_name} ({customer_id}) from the remembered "
        f"collection interactions and their outcomes. {PLAYBOOK_QUESTIONS}"
    )
    # Tags double as the reflect scope: every tag must be present on the source
    # memories, so only the customer tag goes here (an extra "kind" tag would
    # leave reflect with no sources in scope).
    try:
        resp = _run(client.acreate_mental_model(
            bid,
            name=f"{customer_name} collection playbook",
            source_query=source_query,
            tags=[f"customer:{customer_id}"],
            trigger={"refresh_after_consolidation": True},
            id=mid,
        ))
    except Exception as exc:  # noqa: BLE001
        raise _wrap_api_error("Creating mental model", exc) from exc
    op_id = getattr(resp, "operation_id", None)
    out: dict[str, Any] = {"mental_model_id": mid, "created": True, "operation": op_id}
    if wait and op_id:
        out["final"] = wait_for_operation(op_id)
    return out


def refresh_customer_playbook(customer_id: str, wait: bool = True) -> dict[str, Any]:
    """Regenerate the customer's playbook from current memories."""
    client = get_client()
    bid = bank_id()
    mid = playbook_model_id(customer_id)
    try:
        resp = _run(client.arefresh_mental_model(bid, mid))
    except Exception as exc:  # noqa: BLE001
        raise _wrap_api_error(f"Refreshing mental model {mid!r}", exc) from exc
    op_id = getattr(resp, "operation_id", None)
    out: dict[str, Any] = {"mental_model_id": mid, "operation": op_id}
    if wait and op_id:
        out["final"] = wait_for_operation(op_id)
    return out


def get_customer_playbook(customer_id: str) -> dict[str, Any]:
    """Return the playbook mental model (id, name, content, freshness) as a plain dict."""
    client = get_client()
    bid = bank_id()
    mid = playbook_model_id(customer_id)
    try:
        m = _run(client.aget_mental_model(bid, mid, detail="content"))
    except Exception as exc:  # noqa: BLE001
        raise _wrap_api_error(f"Reading mental model {mid!r}", exc) from exc
    content = (getattr(m, "content", None) or "").strip()
    if content.lower().startswith("generating content"):
        content = ""  # Hindsight's placeholder while a refresh is still running
    return {
        "id": getattr(m, "id", mid),
        "name": getattr(m, "name", None),
        "content": content,
        "source_query": getattr(m, "source_query", None),
        "tags": list(getattr(m, "tags", None) or []),
        "last_refreshed_at": getattr(m, "last_refreshed_at", None),
        "is_stale": getattr(m, "is_stale", None),
    }


def reflect_customer(
    customer_id: str,
    query: str,
    *,
    context: str | None = None,
    budget: str = "mid",
    max_tokens: int | None = None,
    response_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run Hindsight reflect scoped to one customer's memories (strict tag match).

    Returns {"text", "structured_output", "structured_output_error", "based_on": [facts]}.
    ``based_on`` lists the memories/mental models the answer was built from, each as
    {"id", "type", "text", "occurred_start"}.
    """
    client = get_client()
    bid = bank_id()
    try:
        resp = _run(client.areflect(
            bank_id=bid,
            query=query,
            budget=budget,
            context=context,
            max_tokens=max_tokens,
            response_schema=response_schema,
            tags=[f"customer:{customer_id}"],
            tags_match="all_strict",
            include_facts=True,
        ))
    except Exception as exc:  # noqa: BLE001
        raise _wrap_api_error("Reflect", exc) from exc

    based_on: list[dict[str, Any]] = []
    raw = getattr(resp, "based_on", None)
    groups = raw if isinstance(raw, dict) else (getattr(raw, "model_dump", lambda: {})() or {})
    for ftype, facts in (groups or {}).items():
        for f in facts or []:
            get = (lambda k, _f=f: _f.get(k) if isinstance(_f, dict) else getattr(_f, k, None))
            based_on.append(
                {
                    "id": get("id"),
                    "type": get("type") or ftype,
                    "text": get("text") or get("content") or get("name") or "",
                    "occurred_start": get("occurred_start"),
                }
            )
    return {
        "text": getattr(resp, "text", "") or "",
        "structured_output": getattr(resp, "structured_output", None),
        "structured_output_error": getattr(resp, "structured_output_error", None),
        "based_on": based_on,
    }


def list_customer_observations(customer_id: str, query: str | None = None, max_tokens: int = 6000) -> list[dict[str, Any]]:
    """Return consolidated observations tagged to one customer."""
    q = query or (
        f"Patterns in collecting overdue payments from {customer_id}: channels, contacts, tones, "
        f"timing, promises, disputes, payments, and any changes in contact or preference."
    )
    return recall_customer_memory(customer_id, query=q, types=["observation"], max_tokens=max_tokens, budget="high")


__all__ = [
    "BANK_DISPOSITION",
    "HindsightAPIError",
    "HindsightConfigError",
    "MemoryConfig",
    "MemoryStatus",
    "OBSERVATIONS_MISSION",
    "REFLECT_MISSION",
    "build_memory_item",
    "close_memory",
    "configure_bank",
    "delete_document",
    "ensure_customer_playbook",
    "get_bank_overrides",
    "get_bank_status",
    "get_customer_playbook",
    "initialize_memory",
    "list_customer_observations",
    "list_seeded_document_ids",
    "load_config",
    "load_dataset",
    "playbook_model_id",
    "rebuild_observations",
    "recall_customer_memory",
    "reflect_customer",
    "refresh_customer_playbook",
    "retain_interaction",
    "seed_customer_history",
    "wait_for_operation",
]
