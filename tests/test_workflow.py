from datetime import datetime, timedelta, timezone

import pytest

from cod_engine.workflow import start, transition

T = datetime(2026, 10, 31, 8, tzinfo=timezone.utc)


@pytest.mark.parametrize("reply,status", [("YES","READY_TO_SHIP"), (" no ","CANCELLED"), ("yes please","CONFIRM_PENDING"), ("random","CONFIRM_PENDING"), ("DECLINE","CONFIRM_PENDING")])
def test_replies(cfg, reply, status):
    s = start("one", "SHIP_AFTER_CONFIRMATION", T)
    assert transition(s, "evt", reply, T+timedelta(hours=1), cfg).status == status
    assert s.status == "CONFIRM_PENDING"  # pure; input unchanged


def test_reminder_timeout_clock_and_retry(cfg):
    s = start("one", "SHIP_AFTER_CONFIRMATION", T)
    s = transition(s, "24", "TICK", T+timedelta(hours=24), cfg)
    assert s.status == "REMINDER_DUE" and s.confirmation_started_at == T
    retried = transition(s, "24", "TICK", T+timedelta(hours=30), cfg)
    assert retried == s
    s = transition(s, "47", "random", T+timedelta(hours=47), cfg)
    assert s.confirmation_started_at == T
    s = transition(s, "48", "YES", T+timedelta(hours=48), cfg)
    assert s.status == "HOLD_TIMEOUT"
    assert transition(s, "49", "YES", T+timedelta(hours=49), cfg).status == "HOLD_TIMEOUT"


def test_prepaid_accept_verified_payment(cfg):
    s = start("one", "NUDGE_TO_PREPAID", T)
    s = transition(s, "accept", "ACCEPT", T, cfg)
    assert s.status == "PAYMENT_PENDING"
    s = transition(s, "bad", "PAYMENT_SUCCESS", T, cfg)
    assert s.status == "PAYMENT_PENDING"
    s = transition(s, "verified", "PAYMENT_SUCCESS", T, cfg, verified_payment=True)
    assert s.status == "READY_TO_SHIP"
    assert transition(s, "verified", "PAYMENT_SUCCESS", T, cfg, verified_payment=True) == s


def test_prepaid_decline_is_not_cod_no(cfg):
    s = start("one", "NUDGE_TO_PREPAID", T)
    assert transition(s, "no", "NO", T, cfg).status == "OFFER_PENDING"
    s = transition(s, "decline", "DECLINE", T+timedelta(hours=30), cfg)
    assert s.status == "CONFIRM_PENDING" and s.confirmation_started_at == T+timedelta(hours=30)
    s = transition(s, "no", "NO", T+timedelta(hours=31), cfg)
    assert s.status == "CANCELLED"


def test_out_of_order_and_naive_time(cfg):
    s = start("one", "SHIP_AFTER_CONFIRMATION", T)
    with pytest.raises(ValueError):
        transition(s, "old", "YES", T-timedelta(seconds=1), cfg)
    with pytest.raises(ValueError):
        start("one", "SHIP_AFTER_CONFIRMATION", T.replace(tzinfo=None))
