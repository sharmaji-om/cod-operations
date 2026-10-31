"""Pure transitions; caller must persist returned state atomically by order/event ID."""
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Workflow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str
    status: Literal["OFFER_PENDING", "PAYMENT_PENDING", "CONFIRM_PENDING", "REMINDER_DUE", "HOLD_TIMEOUT", "READY_TO_SHIP", "CANCELLED"]
    created_at: datetime
    confirmation_started_at: datetime | None = None
    last_event_at: datetime
    processed_event_ids: list[str] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def check(self):
        for value in (self.created_at, self.last_event_at, self.confirmation_started_at):
            if value is not None and value.utcoffset() is None:
                raise ValueError("workflow timestamps require an explicit timezone")
        if self.last_event_at < self.created_at:
            raise ValueError("last_event_at precedes creation")
        if self.status in {"CONFIRM_PENDING", "REMINDER_DUE"} and self.confirmation_started_at is None:
            raise ValueError("confirmation clock is required")
        return self


def start(order_id, action, at):
    if action not in {"SHIP_AFTER_CONFIRMATION", "NUDGE_TO_PREPAID"}:
        raise ValueError("only confirmation/prepaid actions need a workflow")
    confirm = action == "SHIP_AFTER_CONFIRMATION"
    return Workflow(order_id=order_id, status="CONFIRM_PENDING" if confirm else "OFFER_PENDING",
                    created_at=at, last_event_at=at, confirmation_started_at=at if confirm else None)


def transition(state, event_id, event, at, cfg, verified_payment=False):
    if not event_id.strip():
        raise ValueError("event_id is required for idempotency")
    if at.utcoffset() is None:
        raise ValueError("event timestamp requires an explicit timezone")
    if event_id in state.processed_event_ids:
        return state.model_copy(deep=True)
    if at < state.last_event_at:
        raise ValueError("out-of-order event; reload and reconcile before retrying")
    result = state.model_copy(deep=True)
    event = event.strip().upper()
    previous = result.status
    reason = "No matching transition; unrecognized reply does not confirm."
    terminal = result.status in {"HOLD_TIMEOUT", "READY_TO_SHIP", "CANCELLED"}
    if terminal:
        reason = "Terminal state retained; manual review required to reopen."
    elif result.status in {"CONFIRM_PENDING", "REMINDER_DUE"}:
        elapsed = at - result.confirmation_started_at
        if elapsed >= timedelta(hours=cfg.deadline_hours):
            result.status, reason = "HOLD_TIMEOUT", "Confirmation deadline reached; late replies do not release shipment."
        elif event == "YES":
            result.status, reason = "READY_TO_SHIP", "Explicit COD YES; eligible to ship, delivery still uncertain."
        elif event == "NO":
            result.status, reason = "CANCELLED", "Explicit COD NO; cancel COD order."
        elif elapsed >= timedelta(hours=cfg.reminder_hours):
            result.status, reason = "REMINDER_DUE", f"{cfg.reminder_hours:g}-hour reminder due; original deadline retained."
    elif result.status == "OFFER_PENDING":
        if event == "ACCEPT":
            result.status, reason = "PAYMENT_PENDING", "Initiate prepaid payment; acceptance alone cannot release shipment."
        elif event == "DECLINE":
            result.status, result.confirmation_started_at = "CONFIRM_PENDING", at
            reason = "Prepaid declined; start mandatory COD confirmation with a fresh first-request clock."
    elif result.status == "PAYMENT_PENDING":
        if event == "PAYMENT_SUCCESS" and verified_payment:
            result.status, reason = "READY_TO_SHIP", "Payment success verified by trusted payment adapter."
        elif event == "PAYMENT_SUCCESS":
            reason = "Unverified payment callback ignored."
        elif event == "DECLINE":
            result.status, result.confirmation_started_at = "CONFIRM_PENDING", at
            reason = "Prepaid abandoned; first COD confirmation request starts now."
    result.last_event_at = at
    result.processed_event_ids.append(event_id)
    result.events.append({"event_id": event_id, "event": event, "at": at.isoformat(), "from": previous, "to": result.status, "reason": reason})
    return result
