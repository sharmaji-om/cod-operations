import json

from pydantic import ValidationError
import pytest

from cod_engine.address import assess
from cod_engine.economics import estimates
from cod_engine.policy import decide
from cod_engine.schema import Order, Settings, load_settings


class Fixed:
    version = "test"

    def __init__(self, p):
        self.p = p

    def predict(self, order):
        return self.p


@pytest.mark.parametrize("prior,rto,expected", [(0,0,"NUDGE_TO_PREPAID"), (1,1,"SHIP_AFTER_CONFIRMATION"),
    (2,2,"HOLD_CANCEL"), (3,3,"HOLD_CANCEL"), (4,3,"SHIP_AFTER_CONFIRMATION"),
    (3,2,"SHIP_AFTER_CONFIRMATION"), (1,0,"SHIP_AFTER_CONFIRMATION"), (2,1,"SHIP_AFTER_CONFIRMATION"),
    (2,0,"SHIP_AS_IS"), (4,1,"SHIP_AS_IS")])
def test_trust_precedence(payload, cfg, prior, rto, expected):
    order = Order(**(payload | {"customer_prior_orders": prior, "customer_prior_rto": rto}))
    decision = decide(order, Fixed(.9), cfg)
    assert decision["primary_action"] == expected
    assert decision["trust_score"] == prior-2*rto
    assert decision["prior_successes"] == prior-rto


@pytest.mark.parametrize("p,action", [(.4,"SHIP_AFTER_CONFIRMATION"), (.400001,"NUDGE_TO_PREPAID"), (.02,"SHIP_AS_IS"), (1.,"NUDGE_TO_PREPAID")])
def test_new_cutoff(order, cfg, p, action):
    assert decide(order, Fixed(p), cfg)["primary_action"] == action


def test_financial_boundary(order, cfg):
    threshold = estimates(649, .2, cfg)["confirmation_break_even_probability"]
    assert threshold == pytest.approx(.13507, abs=.0001)
    assert estimates(649, .2, cfg)["rto_loss"] == pytest.approx(169.4)
    assert decide(order, Fixed(threshold), cfg)["primary_action"] == "SHIP_AS_IS"
    assert decide(order, Fixed(threshold+1e-7), cfg)["primary_action"] == "SHIP_AFTER_CONFIRMATION"
    expensive = estimates(2000, .2, cfg)["confirmation_break_even_probability"]
    assert expensive > threshold


@pytest.mark.parametrize("value", [0, -2, float("inf"), float("nan"), None, "garbage"])
def test_invalid_prices(payload, value):
    with pytest.raises(ValidationError):
        Order(**(payload | {"order_value": value}))


def test_missing_price(payload):
    del payload["order_value"]
    with pytest.raises(ValidationError):
        Order(**payload)


@pytest.mark.parametrize("change", [{"customer_prior_orders": 0, "customer_prior_rto": 1}, {"customer_prior_orders": -1},
    {"customer_prior_rto": .5}, {"num_items": 0}, {"pincode": 411001}, {"final_status": "RTO"}, {"payment_method": "PREPAID"}])
def test_input_contract(payload, change):
    with pytest.raises(ValidationError):
        Order(**(payload | change))


@pytest.mark.parametrize("change", [{"address": ""}, {"city": ""}, {"state": ""}, {"pincode": ""}, {"pincode": "abc123"}, {"address": "test"}])
def test_hard_address_overrides_trust(payload, cfg, change):
    order = Order(**(payload | {"customer_prior_orders": 5} | change))
    d = decide(order, Fixed(.99), cfg)
    assert d["primary_action"] == "HOLD_CANCEL" and d["sub_action"] == "HOLD_ADDRESS"
    assert d["predicted_rto_probability"] is None


def test_city_alone_cannot_reject(order, cfg):
    assert decide(order.model_copy(update={"city": "some city"}), Fixed(.99), cfg)["primary_action"] == "NUDGE_TO_PREPAID"


def test_suspicious_name_not_fraud_rejection(order, cfg):
    d = decide(order.model_copy(update={"customer_name": "test"}), Fixed(.1), cfg)
    assert d["primary_action"] != "HOLD_CANCEL"


def test_llm_failure_fallback(order):
    def failure(_):
        raise RuntimeError("provider down")
    order = order.model_copy(update={"address": "mandir ke paas, mg nagar"})
    result = assess(order, reviewer=failure)
    assert result["category"] == "INCOMPLETE"
    assert result["review"]["error"] == "RuntimeError"


def test_llm_cannot_cancel(order):
    order = order.model_copy(update={"address": "mandir ke paas, mg nagar"})
    result = assess(order, reviewer=lambda _: {"category": "BAD_UNDELIVERABLE", "rationale": "guess"})
    assert result["category"] == "INCOMPLETE" and not result["review"]["applied"]


@pytest.mark.parametrize("change", [{"confirmation_prevention": 2}, {"message_cost": -1}, {"deadline_hours": 24},
    {"discount_fraction": 1.1}, {"city_max_adjustment": .8}, {"pincode_smoothing": 0}, {"llm_mode": "live"},
    {"converted_prepaid_rto": -1}, {"reject_trust_max": 0}, {"unknown_setting": 1}])
def test_bad_config(change):
    with pytest.raises(ValidationError):
        Settings(**change)


def test_config_edits(tmp_path, order, cfg):
    path = tmp_path/"config.json"
    path.write_text(json.dumps(cfg.model_dump() | {"prepaid_risk_cutoff": .8}))
    assert decide(order, Fixed(.6), load_settings(path))["primary_action"] == "SHIP_AFTER_CONFIRMATION"
    repeat = order.model_copy(update={"customer_prior_orders": 2, "customer_prior_rto": 2})
    assert decide(repeat, Fixed(.6), cfg.model_copy(update={"reject_repeat_enabled": False}))["primary_action"] == "SHIP_AFTER_CONFIRMATION"


def test_economics_no_denominator(order, cfg):
    cfg = cfg.model_copy(update={"confirmation_prevention": 0, "confirmation_genuine_loss": 0})
    assert estimates(649, .3, cfg)["confirmation_break_even_probability"] is None
    assert decide(order, Fixed(.3), cfg)["primary_action"] == "SHIP_AS_IS"


def test_discount_cap(order, cfg):
    d = decide(order.model_copy(update={"order_value": 2000}), Fixed(.8), cfg)
    assert d["prepaid_offer"]["discount"] == 50


@pytest.mark.parametrize("p", [-.1, 1.1, float("nan")])
def test_invalid_prediction(order, cfg, p):
    with pytest.raises(ValueError):
        decide(order, Fixed(p), cfg)
