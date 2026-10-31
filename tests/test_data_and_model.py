import csv

import pytest

from cod_engine.data import chronological_split, load_data
from cod_engine.risk import RiskModel
from cod_engine.schema import ROOT
from cod_engine.train import backtest, metrics


def test_data_quarantine_and_time_order():
    pairs, audit, summary = load_data(ROOT/"data/orders_sample.csv")
    assert summary["input_rows"] == 2018
    assert len(pairs)+len(audit) == 2018
    ids = [o.order_id for o, _ in pairs]
    assert len(ids) == len(set(ids))
    assert any("duplicate_order_id_all_copies_quarantined" in a["reasons"] for a in audit)
    train, val, test = chronological_split(pairs)
    assert max(o.order_datetime for o, _ in train) < min(o.order_datetime for o, _ in val)
    assert max(o.order_datetime for o, _ in val) < min(o.order_datetime for o, _ in test)


def test_sparse_pincode_and_city_caps(cfg, order):
    pairs = [(order.model_copy(update={"order_id": str(i), "city": "a" if i < 20 else "b"}), i < 20) for i in range(40)]
    model = RiskModel("segment", cfg).fit(pairs)
    assert all(abs(v) <= cfg.city_max_adjustment for v in model.city_adjustments.values())
    features = model.features(order.model_copy(update={"pincode": "999999"}))
    assert features["pincode_rate"] == model.rate
    assert model.predict(order.model_copy(update={"city": "unseen"})) == model.base_predict(order)


def test_scenario_reconciles_and_never_uses_outcome_for_decisions(cfg):
    pairs, _, _ = load_data(ROOT/"data/orders_sample.csv")
    train, _, test = chronological_split(pairs)
    model = RiskModel("segment", cfg).fit(train)
    report, decisions = backtest(test, model, cfg)
    flipped, flipped_decisions = backtest([(o, 1-y) for o, y in test], model, cfg)
    assert [d["primary_action"] for d in decisions] == [d["primary_action"] for d in flipped_decisions]
    assert sum(b["count"] for b in report["buckets"].values()) == len(test)
    s = report["default_scenario"]
    assert s["net_incremental_contribution"] == pytest.approx(s["gross_avoided_rto_cost"]-s["net_foregone_delivered_margin"]-s["messaging_cost"]-s["discount_cost"], abs=.02)
