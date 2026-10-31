"""Scenario accounting only; all money remains Decimal until integer-paise output."""
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field


def D(value):
    return Decimal(str(value))


def paise(value):
    return int((D(value)*100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    prepaid_acceptance: float = Field(default=.3, ge=0, le=1)
    processing_fee_fraction: float = Field(default=.02, ge=0, le=1)
    processing_fee_fixed_paise: int = Field(default=0, ge=0, le=100000)
    brand: str = Field(default="Root & Ritual", min_length=1, max_length=60)


def project(records, cfg, scenario):
    zero = Decimal(0)
    totals = {k: zero for k in ["baseline", "avoided_rto", "foregone_margin", "messages", "discounts", "processing"]}
    included = 0
    for r in records:
        risk = r["decision"]["predicted_rto_probability"]
        if risk is None:
            continue  # Cannot invent address-HOLD risk; report coverage explicitly.
        included += 1
        p, value = D(risk), D(r["order"]["order_value"])
        margin = D(cfg.gross_margin)*value
        loss = D(cfg.forward_shipping)+D(cfg.return_shipping)+D(cfg.packaging)+D(cfg.damage_probability)*D(cfg.product_cost)
        a, b, cost = D(cfg.confirmation_prevention), D(cfg.confirmation_genuine_loss), D(cfg.message_cost)
        totals["baseline"] += (1-p)*margin-p*loss
        action = r["decision"]["primary_action"]
        # Discounts and initial episode economics are frozen with the initial decision.
        # a/b/q/acceptance/cost are current scenario assumptions for sensitivity.
        if action == "SHIP_AFTER_CONFIRMATION":
            totals["avoided_rto"] += p*a*loss
            totals["foregone_margin"] += (1-p)*b*margin
            totals["messages"] += cost
        elif action == "HOLD_CANCEL":
            totals["avoided_rto"] += p*loss
            totals["foregone_margin"] += (1-p)*margin
        elif action == "NUDGE_TO_PREPAID":
            accept, q = D(scenario.prepaid_acceptance), D(cfg.converted_prepaid_rto)
            discount = D(r["offer_paise"])/100
            totals["avoided_rto"] += accept*(p-q)*loss+(1-accept)*p*a*loss
            totals["foregone_margin"] += accept*(q-p)*margin+(1-accept)*(1-p)*b*margin
            totals["messages"] += (2-accept)*cost
            totals["discounts"] += accept*(1-q)*discount
            totals["processing"] += accept*((value-discount)*D(scenario.processing_fee_fraction)+D(scenario.processing_fee_fixed_paise)/100)
    output = {key+"_paise": paise(value) for key, value in totals.items()}
    # Sum rounded displayed components so the UI reconciles exactly to the paise.
    output["intervention_costs_paise"] = output["messages_paise"]+output["discounts_paise"]+output["processing_paise"]
    output["net_paise"] = output["avoided_rto_paise"]-output["foregone_margin_paise"]-output["intervention_costs_paise"]
    output["policy_contribution_paise"] = output["baseline_paise"]+output["net_paise"]
    return {**output, "modeled_count": included, "unavailable_count": len(records)-included,
            "label": "Scenario estimate", "basis": "Initial decisions and stored modeled risks; simulated operational replies do not establish causal savings.",
            "discount_basis": "Only delivered converted-prepaid orders; initial offer frozen.",
            "processing_basis": "Every assumed accepted prepaid transaction, including assumed RTO; fee on discounted order value.",
            "hold_basis": "Unshipped through scenario horizon; address holds with unknown risk excluded.",
            "acquisition_cost": "Sunk; excluded", "realized_savings": "Unavailable: no observed counterfactual outcomes."}
