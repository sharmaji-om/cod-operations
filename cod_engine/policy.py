from datetime import datetime, timezone
import math

from .address import assess
from .economics import estimates


def decide(order, predictor, cfg, now=None):
    address = assess(order, cfg.llm_mode)
    base = {"order_id": order.order_id, "customer_type": "NEW" if order.customer_prior_orders == 0 else "REPEAT",
            "prior_successes": order.successes, "trust_score": order.trust,
            "predicted_rto_probability": None, "model_version": predictor.version,
            "financial_estimates": None, "prepaid_offer": None, "address": address,
            "warnings": list(address["warnings"]), "audit_timestamp": (now or datetime.now(timezone.utc)).isoformat()}
    if address["category"] == "BAD_UNDELIVERABLE":
        rule, action, sub, reason, step = "R1", "HOLD_CANCEL", "HOLD_ADDRESS", address["reason"], "Request corrected delivery details; do not ship."
    else:
        p = float(predictor.predict(order))
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError("model produced an invalid probability")
        money = estimates(order.order_value, p, cfg)
        base.update(predicted_rto_probability=p, financial_estimates=money)
        if order.customer_prior_orders > 0 and order.successes == 0 and order.trust <= cfg.reject_trust_max and cfg.reject_repeat_enabled:
            rule, action, sub = "R2", "HOLD_CANCEL", "REJECT_REPEAT"
            reason = f"No successful deliveries and {order.customer_prior_rto} prior returns meet the configured repeat rejection policy."
            step = "Reject COD under repeat-history policy; retain audit and allow operations review."
        elif order.customer_prior_orders > 0 and order.trust >= cfg.trusted_score_min:
            rule, action, sub = "R3", "SHIP_AS_IS", "TRUSTED_REPEAT"
            reason, step = f"Repeat customer has trust score {order.trust} with {order.successes} successful deliveries.", "Release COD shipment."
        elif order.customer_prior_orders > 0 and order.trust < 0:
            rule, action, sub = "R4", "SHIP_AFTER_CONFIRMATION", "CONFIRM_COD"
            reason, step = f"Repeat customer has negative trust score {order.trust}; WhatsApp confirmation is required.", "Request explicit YES/NO confirmation."
            if order.successes == 0:
                base["warnings"].append("Unspecified repeat negative-history case defaults to confirmation when rejection does not apply.")
        elif order.customer_prior_orders == 0 and p > cfg.prepaid_risk_cutoff:
            rule, action, sub = "R6", "NUDGE_TO_PREPAID", "OFFER_PREPAID"
            reason, step = f"Estimated COD return risk {p:.1%} exceeds {cfg.prepaid_risk_cutoff:.1%}; offer prepaid without rejecting this new buyer.", "Offer prepaid; ship only after verified payment. Decline requires COD confirmation."
            base["prepaid_offer"] = {"discount": money["discount"], "fraction": cfg.discount_fraction, "cap": cfg.discount_cap,
                                    "payment_verification_required": True, "decline_action": "CONFIRM_COD"}
        else:
            rule = "R7" if order.customer_prior_orders == 0 else "R5"
            confirm = money["incremental_confirmation_contribution"] > 1e-10
            action, sub = ("SHIP_AFTER_CONFIRMATION", "CONFIRM_COD") if confirm else ("SHIP_AS_IS", "ECONOMIC_SHIP")
            reason = f"Estimated COD return risk {p:.1%}; confirmation changes expected contribution by Rs {money['incremental_confirmation_contribution']:.2f} under configured assumptions."
            step = "Request explicit YES/NO confirmation." if confirm else "Release COD shipment."
    base.update(primary_action=action, sub_action=sub, reason=reason, required_next_step=step, triggered_rule_ids=[rule])
    base["workflow"] = {"confirmation_required": action == "SHIP_AFTER_CONFIRMATION", "reminder_hours": cfg.reminder_hours,
                        "deadline_hours": cfg.deadline_hours, "clock_policy": "From first confirmation request; reminders never reset it.",
                        "delivery_guaranteed_by_yes": False}
    return base
