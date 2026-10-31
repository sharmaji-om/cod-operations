"""Persistent mock operations around the existing decision/workflow engine."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import store
from .policy import decide
from .projections import D, Scenario, paise, project
from .schema import ROOT, Order, Settings, load_settings
from .workflow import Workflow, start, transition

IST = ZoneInfo("Asia/Kolkata")
router = APIRouter()
ACTIONS = ["SHIP_AS_IS", "SHIP_AFTER_CONFIRMATION", "NUDGE_TO_PREPAID", "HOLD_CANCEL"]
TERMINAL = {"HOLD_TIMEOUT", "READY_TO_SHIP", "CANCELLED"}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def current_settings(db=None):
    own = db is None
    db = db or store.connect()
    try:
        row = db.execute("SELECT snapshot,revision FROM settings WHERE id=1").fetchone()
        base = load_settings(ROOT / os.getenv("COD_CONFIG", "config.json"))
        saved = json.loads(row[0]) if row else {"policy": {}, "scenario": {}}
        policy = Settings.model_validate(base.model_dump() | saved["policy"])
        scenario = Scenario.model_validate(saved["scenario"])
        return policy, scenario, row[1] if row else 0
    finally:
        if own:
            db.close()


def predictor():
    from .api import model
    return model()


def status(r):
    if r["workflow"]:
        state = r["workflow"]["status"]
        if state == "READY_TO_SHIP":
            return "PREPAID_CONFIRMED" if r["payment_verified"] else "COD_CONFIRMED"
        return {"OFFER_PENDING": "PREPAID_OFFERED", "REMINDER_DUE": "REMINDER_SENT", "HOLD_TIMEOUT": "HELD_EXPIRED"}.get(state, state)
    return "DIRECT_READY" if r["decision"]["primary_action"] == "SHIP_AS_IS" else r["decision"]["sub_action"]


def add_message(r, text, kind="outgoing", tag="message"):
    r["messages"].append({"id": f"{r['generation']}:{len(r['messages'])}", "text": text, "direction": kind,
                          "at": r["clock"], "tag": tag, "state": "simulated_sent" if kind == "outgoing" else "received"})


def money(paise_value):
    return f"{D(paise_value)/100:,.2f}"


def copy_for(r, key, cfg, scenario):
    first = r["order"]["customer_name"].split()[0].title() if r["order"]["customer_name"] else "there"
    oid, amount = r["id"].upper(), money(r["value_paise"])
    remaining = cfg.deadline_hours
    if r["workflow"] and r["workflow"]["confirmation_started_at"]:
        remaining = max(0, cfg.deadline_hours-(datetime.fromisoformat(r["clock"])-datetime.fromisoformat(r["workflow"]["confirmation_started_at"])).total_seconds()/3600)
    texts = {
        "confirmation": f"Hi {first}, thanks for ordering from {scenario.brand}! Please confirm your COD order #{oid} for INR {amount}. Reply YES to confirm or NO to cancel. We will hold it for up to {cfg.deadline_hours:g} hours.",
        "offer": f"Hi {first}! You can switch order #{oid} to prepaid and save INR {money(r['offer_paise'])}. Would you like to pay online? Reply YES for the mock payment link, or NO to keep COD and confirm your order.",
        "reminder": f"Quick reminder: we are waiting for confirmation of order #{oid}. Reply YES to confirm or NO to cancel. Your confirmation window ends in {remaining:g} hours.",
        "offer_reminder": f"Quick reminder for #{oid}: reply YES for a mock prepaid payment link, or NO to start COD confirmation. The offer window ends at the displayed deadline.",
        "cod_ready": f"Thanks! Your COD order #{oid} is confirmed and ready for processing. Confirmation does not guarantee delivery.",
        "cancelled": f"Understood. Order #{oid} has been cancelled. If this was a mistake, please contact support.",
        "fallback": f"No problem - you can continue with COD. Reply YES to confirm order #{oid} or NO to cancel. A new {cfg.deadline_hours:g}-hour confirmation window starts now.",
        "payment": f"Here is your simulated payment action for #{oid}. No money will be charged. Use 'Simulate payment success' to complete the mock payment, or choose COD fallback.",
        "paid": f"Mock payment verified. Order #{oid} is now prepaid and ready for processing. You saved INR {money(r['offer_paise'])}.",
        "failed": "The simulated payment failed. You can retry the mock payment or choose COD fallback. Your order has not been released.",
        "expired": f"The response window for #{oid} has ended. The order is held and will not ship. Please contact support for manual review.",
        "clarify": "Please reply YES or NO so we can process the current request. Other replies do not confirm your order.",
    }
    return texts[key]


def initialize(r, cfg, scenario):
    action = r["decision"]["primary_action"]
    r["workflow"] = start(r["id"], action, datetime.fromisoformat(r["clock"])).model_dump(mode="json") if action in {"SHIP_AFTER_CONFIRMATION", "NUDGE_TO_PREPAID"} else None
    r.update(messages=[], payment_verified=False, payment_failed=False, clarified=False, reminder_sent=False)
    if r["workflow"]:
        add_message(r, copy_for(r, "confirmation" if action == "SHIP_AFTER_CONFIRMATION" else "offer", cfg, scenario), tag="initial")


def make_record(order, model, cfg, scenario, fixture=False, note=""):
    decision = decide(order, model, cfg, now=order.order_datetime)
    offer = min(D(cfg.discount_fraction)*D(order.order_value), D(cfg.discount_cap))
    r = {"id": order.order_id, "day": order.order_datetime.astimezone(IST).date().isoformat(), "order": order.model_dump(mode="json"),
         "decision": decision, "policy_snapshot": cfg.model_dump(), "value_paise": paise(order.order_value), "offer_paise": paise(offer),
         "created_at": order.order_datetime.isoformat(), "clock": order.order_datetime.isoformat(),
         "revision": 0, "generation": 0, "events": [], "fixture": fixture, "scenario_note": note, "updated_at": utcnow()}
    initialize(r, cfg, scenario)
    r["events"].append({"id": "initial", "generation": 0, "at": r["clock"], "recorded_at": utcnow(), "source": "engine", "from": None, "to": status(r), "reason": decision["reason"], "kind": "INITIAL_DECISION"})
    return r


class FixtureRisk:
    version = "demo/controlled-risk-fixture"

    def __init__(self, p):
        self.p = p

    def predict(self, order):
        return self.p


def ensure_seed():
    # Fail visibly if the real engine artifact is unavailable, even for fixture demos.
    try:
        predictor()
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(503, "Decision engine unavailable; demo initialization cannot be verified.") from error
    with store.transaction() as db:
        if db.execute("SELECT 1 FROM records LIMIT 1").fetchone():
            return
        cfg, scenario, _ = current_settings(db)
        yesterday = datetime.now(IST).date()-timedelta(days=1)
        names = ["Asha Demo", "Neha Demo", "Tara Demo", "Mira Demo", "Kavya Demo", "Anika Demo", "Isha Demo", "Riya Demo"]
        recipes = [(.22,0,0,649,"Confirmation / explicit YES"), (.28,0,0,899,"Random reply, reminder and expiry"),
                   (.58,0,0,1499,"Prepaid / capped discount"), (.49,0,0,649,"Prepaid decline / COD fallback"),
                   (.18,3,0,1199,"Trusted repeat / direct"), (.35,1,1,799,"Repeat score -1 / mandatory confirmation"),
                   (.65,2,2,999,"Zero successes, score -2 / reject"), (.07,0,0,499,"New low risk / direct"),
                   (.32,4,3,1299,"One success, score -2 / confirm"), (.5,0,0,1699,"Mock payment failure"),
                   (.3,0,0,649,"Expired confirmation"), (.2,0,0,999,"Address correction / risk unavailable"),
                   (.25,0,0,699,"Landmark address / review"), (.4,0,0,749,"Exactly 40% / confirmation"),
                   (.18,2,1,549,"Repeat score 0 / financial rule"), (.12,1,0,449,"Repeat score 1 / financial rule")]
        for offset, count in [(1,16),(2,12)]:
            day = yesterday-timedelta(days=offset-1)
            for i, (p, prior, rto, value, note) in enumerate(recipes[:count]):
                oid = f"demo-{day.strftime('%m%d')}-{i+1:03d}"
                at = datetime.combine(day, datetime.min.time(), IST)+timedelta(hours=8, minutes=i*18)
                order = Order(order_id=oid, order_datetime=at, customer_name=names[i%len(names)], phone="9000000000",
                              address="" if i == 11 else "Mandir ke paas, MG Nagar" if i == 12 else "12 MG Road, near school",
                              city="Pune", state="Maharashtra", pincode="411001", order_value=value, items="Haircare demo kit",
                              customer_prior_orders=prior, customer_prior_rto=rto, utm_source="meta_ads", courier="Delhivery")
                r = make_record(order, FixtureRisk(p), cfg, scenario, True, note)
                def seed_event(kind, body):
                    previous, reason = apply_event(r, kind, body, cfg, scenario)
                    r["revision"] += 1
                    r["events"].append({"id": f"seed-{r['revision']}", "generation": 0, "kind": kind, "at": r["clock"], "recorded_at": utcnow(), "source": "seeded_demo", "from": previous, "to": status(r), "reason": reason})
                if i == 9:
                    seed_event("reply", {"text": "YES"})
                    seed_event("payment", {"outcome": "failure"})
                elif i == 10:
                    seed_event("advance", {"hours": 48})
                store.save(db, r)


def public(r, detailed=False):
    out = {k: r[k] for k in ["id", "day", "value_paise", "offer_paise", "created_at", "clock", "revision", "generation", "fixture", "scenario_note", "updated_at", "payment_failed"]}
    out.update(customer_name=r["order"]["customer_name"].title(), initial_action=r["decision"]["primary_action"], status=status(r),
               risk=r["decision"]["predicted_rto_probability"], reason=r["decision"]["reason"], customer_type=r["decision"]["customer_type"],
               address_category=r["decision"]["address"]["category"], model_version=r["decision"]["model_version"],
               required_next_step=r["decision"]["required_next_step"], observed_rto=None)
    out["confirmation_started_at"] = r["workflow"]["confirmation_started_at"] if r["workflow"] else None
    cfg = Settings(**r["policy_snapshot"])
    clock_start = (out["confirmation_started_at"] or r["created_at"]) if out["status"] in {"CONFIRM_PENDING", "REMINDER_SENT", "PREPAID_OFFERED", "HELD_EXPIRED"} else None
    out["deadline"] = (datetime.fromisoformat(clock_start)+timedelta(hours=cfg.deadline_hours)).isoformat() if clock_start else None
    out["hours_remaining"] = max(0, (datetime.fromisoformat(out["deadline"])-datetime.fromisoformat(r["clock"])).total_seconds()/3600) if out["deadline"] else None
    if detailed:
        out.update(messages=r["messages"], events=r["events"], decision=r["decision"], policy_snapshot=r["policy_snapshot"], order=r["order"], payment_verified=r["payment_verified"])
    return out


def apply_event(r, kind, body, cfg, scenario):
    """Adapt stored prompt semantics; initial decision is never mutated."""
    previous = status(r)
    reason = "No matching state transition."
    wf = Workflow.model_validate(r["workflow"]) if r["workflow"] else None
    if kind == "reset":
        r["generation"] += 1
        r["clock"] = r["created_at"]
        initialize(r, cfg, scenario)
        reason = "Operator reset to initial scenario; earlier generations remain in audit history."
    elif kind == "resend":
        if not wf or wf.status != "HOLD_TIMEOUT":
            raise HTTPException(409, "Only expired conversations can be reopened by explicit operator action.")
        wf = start(r["id"], "SHIP_AFTER_CONFIRMATION", datetime.fromisoformat(r["clock"]))
        r["workflow"] = wf.model_dump(mode="json")
        r.update(reminder_sent=False, clarified=False, payment_failed=False)
        add_message(r, copy_for(r, "confirmation", cfg, scenario), tag="operator_resend")
        reason = "Operator explicitly reopened held conversation with a new COD confirmation clock."
    elif not wf:
        raise HTTPException(409, "This initial decision requires no WhatsApp conversation.")
    else:
        at = datetime.fromisoformat(r["clock"])
        event = "TICK"
        if kind == "advance":
            at += timedelta(hours=body["hours"])
            r["clock"] = at.isoformat()
        elif kind == "reply":
            text = body["text"].strip()
            add_message(r, text, "incoming", "customer_reply")
            event = text.upper()
            if wf.status == "OFFER_PENDING":
                event = {"YES": "ACCEPT", "NO": "DECLINE"}.get(event, "OTHER")
            elif wf.status == "PAYMENT_PENDING":
                event = "OTHER"  # Customer text can never impersonate a payment callback.
            elif event not in {"YES", "NO"}:
                event = "OTHER"
        elif kind == "payment":
            if wf.status != "PAYMENT_PENDING":
                raise HTTPException(409, "Payment callback requires the current mock payment step.")
            event = "PAYMENT_SUCCESS" if body["outcome"] == "success" else "PAYMENT_FAILURE"
        elif kind == "fallback":
            if wf.status != "PAYMENT_PENDING":
                raise HTTPException(409, "COD fallback is available from the pending payment step.")
            event = "DECLINE"
        else:
            raise HTTPException(422, "Unsupported simulator action")
        old = wf.status
        # The engine handles confirmation clocks; this adapter adds offer-stage clocks.
        offer_age = (at-datetime.fromisoformat(r["created_at"])).total_seconds()/3600
        if old == "OFFER_PENDING" and offer_age >= cfg.deadline_hours:
            next_wf = wf.model_copy(update={"status": "HOLD_TIMEOUT", "last_event_at": at})
            reason = "Prepaid offer response deadline reached; late interest cannot release shipment."
        else:
            next_wf = transition(wf, str(uuid4()), event, at, cfg, verified_payment=kind == "payment" and body.get("outcome") == "success")
            reason = next_wf.events[-1]["reason"]
        r["workflow"] = next_wf.model_dump(mode="json")
        new = next_wf.status
        if new == "HOLD_TIMEOUT" and old != "HOLD_TIMEOUT":
            add_message(r, copy_for(r, "expired", cfg, scenario), tag="expiry")
        elif new == "READY_TO_SHIP" and old != "READY_TO_SHIP":
            r["payment_verified"] = event == "PAYMENT_SUCCESS"
            r["payment_failed"] = False
            add_message(r, copy_for(r, "paid" if r["payment_verified"] else "cod_ready", cfg, scenario), tag="ready")
        elif new == "CANCELLED" and old != "CANCELLED":
            add_message(r, copy_for(r, "cancelled", cfg, scenario), tag="cancelled")
        elif new == "PAYMENT_PENDING" and old == "OFFER_PENDING":
            add_message(r, copy_for(r, "payment", cfg, scenario), tag="mock_payment")
        elif new == "CONFIRM_PENDING" and old in {"OFFER_PENDING", "PAYMENT_PENDING"}:
            r.update(reminder_sent=False, clarified=False, payment_failed=False)
            add_message(r, copy_for(r, "fallback", cfg, scenario), tag="cod_fallback")
        elif event == "PAYMENT_FAILURE" and new == "PAYMENT_PENDING":
            r["payment_failed"] = True
            add_message(r, copy_for(r, "failed", cfg, scenario), tag="payment_failure")
        elif old not in TERMINAL and kind == "reply" and event == "OTHER" and not r["clarified"]:
            r["clarified"] = True
            add_message(r, copy_for(r, "clarify", cfg, scenario), tag="clarification")
        reminder = new == "REMINDER_DUE" or (new == "OFFER_PENDING" and offer_age >= cfg.reminder_hours)
        if reminder and not r["reminder_sent"]:
            r["reminder_sent"] = True
            add_message(r, copy_for(r, "offer_reminder" if new == "OFFER_PENDING" else "reminder", cfg, scenario), tag="reminder")
        if kind == "payment" and body.get("outcome") == "failure":
            reason = "Simulated payment failed; pending, with explicit retry or COD fallback."
    r["updated_at"] = utcnow()
    return previous, reason


class EventBody(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    event_id: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=0)
    generation: int = Field(ge=0)


class Reply(EventBody):
    text: str = Field(min_length=1, max_length=1000)


class Advance(EventBody):
    hours: float = Field(ge=0, le=720)


class Payment(EventBody):
    outcome: str = Field(pattern="^(success|failure)$")


def execute(identifier, kind, body):
    with store.transaction() as db:
        r = store.get(db, identifier)
        if not r:
            raise HTTPException(404, "Conversation not found")
        if body.generation is not None and body.generation != r["generation"]:
            raise HTTPException(409, "Stale scenario generation; reload before retrying.")
        data = body.model_dump(exclude={"event_id", "expected_revision", "generation"})
        fingerprint = hashlib.sha256(json.dumps([kind, data], sort_keys=True).encode()).hexdigest()
        duplicate = next((e for e in r["events"] if e["id"] == body.event_id), None)
        if duplicate:
            if duplicate.get("fingerprint") != fingerprint:
                raise HTTPException(409, "Event ID already used for a different request")
            return public(r, True)
        if body.expected_revision is not None and body.expected_revision != r["revision"]:
            raise HTTPException(409, "Conversation changed; reload to use the current prompt.")
        cfg = Settings(**r["policy_snapshot"])
        _, scenario, _ = current_settings(db)
        previous, reason = apply_event(r, kind, data, cfg, scenario)
        r["revision"] += 1
        r["events"].append({"id": body.event_id, "generation": r["generation"], "kind": kind, "at": r["clock"], "recorded_at": utcnow(),
                            "source": "mock_payment" if kind == "payment" else "operator" if kind in {"advance", "reset", "resend"} else "simulated_customer",
                            "from": previous, "to": status(r), "reason": reason, "fingerprint": fingerprint})
        store.save(db, r)
        return public(r, True)


@router.get("/simulator/conversations")
def conversations(search: str = "", state: str = ""):
    ensure_seed()
    with store.transaction() as db:
        records = store.all_records(db)
    rows = [public(r) for r in records if (not search or search.lower() in (r["id"]+r["order"]["customer_name"]+r["scenario_note"]).lower()) and (not state or status(r) == state)]
    return {"items": rows, "total": len(rows), "demo": True}


@router.get("/simulator/{identifier}")
def conversation(identifier: str):
    with store.transaction() as db:
        r = store.get(db, identifier)
    if not r:
        raise HTTPException(404, "Conversation not found")
    return public(r, True)


@router.post("/simulator/{identifier}/reply")
def reply(identifier: str, body: Reply):
    return execute(identifier, "reply", body)


@router.post("/simulator/{identifier}/advance")
def advance(identifier: str, body: Advance):
    return execute(identifier, "advance", body)


@router.post("/simulator/{identifier}/payment")
def payment(identifier: str, body: Payment):
    return execute(identifier, "payment", body)


@router.post("/simulator/{identifier}/reset")
def reset(identifier: str, body: EventBody):
    return execute(identifier, "reset", body)


@router.post("/simulator/{identifier}/resend")
def resend(identifier: str, body: EventBody):
    return execute(identifier, "resend", body)


@router.post("/simulator/{identifier}/fallback")
def fallback(identifier: str, body: EventBody):
    return execute(identifier, "fallback", body)


@router.post("/orders", status_code=201)
def create_order(order: Order):
    if order.order_datetime.utcoffset() is None:
        raise HTTPException(422, "Operations order_datetime requires an explicit timezone")
    if D(order.order_value) != D(order.order_value).quantize(Decimal("0.01")):
        raise HTTPException(422, "Operations order_value supports at most two decimal places")
    cfg, scenario, _ = current_settings()
    try:
        r = make_record(order, predictor(), cfg, scenario)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(503, "Decision engine unavailable; no order was created.") from error
    with store.transaction() as db:
        if store.get(db, order.order_id):
            raise HTTPException(409, "Order ID already exists; initial decisions are immutable")
        store.save(db, r)
    return public(r, True)


@router.get("/orders")
def orders(decision: str = "", status_filter: str = Query(default="", alias="status"), day: date | None = None,
           page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100)):
    ensure_seed()
    if decision and decision not in ACTIONS:
        raise HTTPException(422, "Unknown decision bucket")
    with store.transaction() as db:
        rows = [public(r) for r in store.all_records(db) if (not decision or r["decision"]["primary_action"] == decision) and (not status_filter or status(r) == status_filter) and (not day or r["day"] == day.isoformat())]
    return {"items": rows[(page-1)*page_size:page*page_size], "total": len(rows), "page": page, "page_size": page_size}


def exceptions(records):
    result = []
    for r in records:
        s = status(r)
        reason = action = None
        priority = 9
        if s == "HELD_EXPIRED":
            priority, reason, action = 0, "Response window expired", "Review or reopen confirmation"
        elif r["decision"]["address"]["category"] in {"BAD_UNDELIVERABLE", "INCOMPLETE", "SUSPICIOUS"} and s not in {"COD_CONFIRMED", "PREPAID_CONFIRMED", "CANCELLED"}:
            priority, reason, action = 1, "Delivery details need review", "Check address with customer"
        elif r["decision"]["primary_action"] == "HOLD_CANCEL" and r["value_paise"] >= 90000:
            priority, reason, action = 2, "High-value held order", "Review decision and customer history"
        elif r["payment_failed"]:
            priority, reason, action = 3, "Mock payment failed", "Retry or offer COD fallback"
        if reason:
            result.append({**public(r), "exception_reason": reason, "next_action": action, "priority": priority,
                           "age_hours": (datetime.fromisoformat(r["clock"])-datetime.fromisoformat(r["created_at"])).total_seconds()/3600})
    return sorted(result, key=lambda r: (r["priority"], -r["age_hours"], r["id"]))


@router.get("/dashboard")
def dashboard(day: date | None = Query(default=None, alias="date")):
    ensure_seed()
    selected = day or datetime.now(IST).date()-timedelta(days=1)
    with store.transaction() as db:
        all_rows = store.all_records(db)
        cfg, scenario, revision = current_settings(db)
    rows = [r for r in all_rows if r["day"] == selected.isoformat()]
    prior = [r for r in all_rows if r["day"] == (selected-timedelta(days=1)).isoformat()]
    counts = {action: sum(r["decision"]["primary_action"] == action for r in rows) for action in ACTIONS}
    previous_confirm = sum(r["decision"]["primary_action"] == "SHIP_AFTER_CONFIRMATION" for r in prior)
    delta = counts["SHIP_AFTER_CONFIRMATION"]-previous_confirm
    return {"date": selected.isoformat(), "timezone": "Asia/Kolkata", "last_updated": utcnow(), "data_updated": max((r["updated_at"] for r in rows), default=None),
            "demo": True, "eligible_count": len(rows), "buckets": counts, "metrics": project(rows, cfg, scenario),
            "assumptions": {"policy": cfg.model_dump(), "scenario": scenario.model_dump(), "revision": revision},
            "comparison": {"available": bool(prior), "previous_count": len(prior), "confirmation_count_delta": delta if prior else None,
                           "text": f"{abs(delta)} {'more' if delta >= 0 else 'fewer'} orders entered confirmation than the previous day ({previous_confirm} to {counts['SHIP_AFTER_CONFIRMATION']})." if prior else "No comparison available for the previous day."},
            "exceptions": exceptions(rows), "available_dates": sorted({r["day"] for r in all_rows}, reverse=True),
            "latest_states": {key: sum(status(r) == key for r in rows) for key in sorted({status(r) for r in rows})}}


class SettingsEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    policy: dict = Field(default_factory=dict)
    scenario: dict = Field(default_factory=dict)


@router.get("/settings")
def read_settings():
    cfg, scenario, revision = current_settings()
    with store.transaction() as db:
        audit = [dict(r) for r in db.execute("SELECT id,at,before_json,after_json FROM settings_audit ORDER BY id DESC LIMIT 20")]
    return {"policy": cfg.model_dump(), "scenario": scenario.model_dump(), "revision": revision, "audit": audit,
            "note": "Edits affect future initial decisions and current scenario projections. Existing decisions, offers and workflow clocks are preserved."}


@router.put("/settings")
def edit_settings(body: SettingsEdit):
    from pydantic import ValidationError
    with store.transaction() as db:
        cfg, scenario, revision = current_settings(db)
        if revision != body.expected_revision:
            raise HTTPException(409, "Settings changed; reload before saving")
        try:
            updated_cfg = Settings.model_validate(cfg.model_dump() | body.policy)
            updated_scenario = Scenario.model_validate(scenario.model_dump() | body.scenario)
        except ValidationError as error:
            raise HTTPException(422, str(error)) from error
        previous = {"policy": cfg.model_dump(), "scenario": scenario.model_dump()}
        updated = {"policy": updated_cfg.model_dump(), "scenario": updated_scenario.model_dump()}
        db.execute("INSERT INTO settings VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,snapshot=excluded.snapshot", (revision+1, json.dumps(updated)))
        db.execute("INSERT INTO settings_audit(at,before_json,after_json) VALUES (?,?,?)", (utcnow(), json.dumps(previous), json.dumps(updated)))
    return read_settings()
