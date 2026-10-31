"""Reproducible chronological model selection and scenario backtest."""
import argparse
from collections import Counter
from itertools import product
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from .data import chronological_split, load_data
from .policy import decide
from .risk import RiskModel
from .schema import ROOT, load_settings

ACTIONS = ["SHIP_AS_IS", "SHIP_AFTER_CONFIRMATION", "NUDGE_TO_PREPAID", "HOLD_CANCEL"]


def metrics(pairs, model):
    if not pairs:
        return {"n": 0}
    y = np.array([y for _, y in pairs])
    p = np.array([model.predict(o) for o, _ in pairs])
    positive = p >= .5
    return {"n": len(y), "observed_rto_rate": float(y.mean()), "mean_prediction": float(p.mean()),
            "brier": float(brier_score_loss(y, p)), "log_loss": float(log_loss(y, p, labels=[0, 1])),
            "roc_auc": float(roc_auc_score(y, p)) if len(set(y)) == 2 else None,
            "confusion_at_0_5": {"tn": int(sum((y == 0) & ~positive)), "fp": int(sum((y == 0) & positive)), "fn": int(sum((y == 1) & ~positive)), "tp": int(sum((y == 1) & positive))},
            "calibration": [{"lower": lo/10, "upper": (lo+1)/10, "n": int(sum(mask)),
                              "mean_prediction": float(p[mask].mean()) if sum(mask) else None,
                              "observed_rto_rate": float(y[mask].mean()) if sum(mask) else None}
                             for lo in range(10) for mask in [(p >= lo/10) & (p < (lo+1)/10)]]}


def scenario(pairs, decisions, cfg, a, b, acceptance):
    avoided = lost = messages = discounts = baseline = 0.
    for (o, y), decision in zip(pairs, decisions):
        margin, loss = cfg.gross_margin*o.order_value, cfg.rto_loss
        baseline += (1-y)*margin-y*loss
        action = decision["primary_action"]
        if action == "SHIP_AFTER_CONFIRMATION":
            avoided += y*a*loss
            lost += (1-y)*b*margin
            messages += cfg.message_cost
        elif action == "HOLD_CANCEL":
            # Address holds also assumed unshipped through the scenario horizon.
            avoided += y*loss
            lost += (1-y)*margin
        elif action == "NUDGE_TO_PREPAID":
            q = cfg.converted_prepaid_rto
            discount = decision["prepaid_offer"]["discount"]
            avoided += acceptance*(y-q)*loss + (1-acceptance)*y*a*loss
            # Converted delivery rate is a scenario, not this customer's known outcome.
            lost += acceptance*((1-y)-(1-q))*margin + (1-acceptance)*(1-y)*b*margin
            discounts += acceptance*(1-q)*discount
            messages += (2-acceptance)*cfg.message_cost
    net = avoided-lost-messages-discounts
    return {"confirmation_prevention": a, "genuine_loss": b, "prepaid_acceptance": acceptance,
            "gross_avoided_rto_cost": round(avoided, 2), "net_foregone_delivered_margin": round(lost, 2),
            "messaging_cost": round(messages, 2), "discount_cost": round(discounts, 2),
            "net_incremental_contribution": round(net, 2), "ship_all_historical_contribution": round(baseline, 2),
            "scenario_contribution": round(baseline+net, 2)}


def backtest(pairs, model, cfg):
    decisions = [decide(o, model, cfg) for o, _ in pairs]
    buckets = {}
    for action in ACTIONS:
        subset = [(o, y, d) for (o, y), d in zip(pairs, decisions) if d["primary_action"] == action]
        buckets[action] = {"count": len(subset), "historical_rto_count": sum(y for _, y, _ in subset),
                           "historical_rto_rate": sum(y for _, y, _ in subset)/len(subset) if subset else None}
    rejected = [(o, y) for (o, y), d in zip(pairs, decisions) if d["sub_action"] == "REJECT_REPEAT"]
    return {"buckets": buckets, "rejected_historically_delivered": sum(y == 0 for _, y in rejected),
            "rejected_total": len(rejected),
            "default_scenario": scenario(pairs, decisions, cfg, cfg.confirmation_prevention, cfg.confirmation_genuine_loss, .3),
            "sensitivity": [scenario(pairs, decisions, cfg, a, b, rate) for a, b, rate in product([.25, .5, .75], [.01, .03, .08], [.1, .3, .6])]}, decisions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT/"data/orders_sample.csv")
    parser.add_argument("--config", type=Path, default=ROOT/"config.json")
    args = parser.parse_args()
    cfg = load_settings(args.config)
    pairs, audit, quality = load_data(args.data)
    train, validation, test = chronological_split(pairs)
    kinds = ["overall", "segment", "logistic"]
    candidates = {kind: RiskModel(kind, cfg).fit(train) for kind in kinds}
    validation_metrics = {kind: metrics(validation, model) for kind, model in candidates.items()}
    best = min(v["brier"] for v in validation_metrics.values())
    # Simplicity tie-break fixed before seeing test outcomes; tolerance is documented.
    chosen = next(kind for kind in kinds if validation_metrics[kind]["brier"] <= best + .002)
    fitted = {kind: RiskModel(kind, cfg).fit(train+validation) for kind in kinds}
    model = fitted[chosen]
    result, decisions = backtest(test, model, cfg)
    earlier_phones = {o.phone for o, _ in train+validation if o.phone}
    unseen = [p for p in test if p[0].phone and p[0].phone not in earlier_phones]
    groups = {}
    for field in ["utm_source", "courier", "city"]:
        groups[field] = {value: metrics([p for p in test if getattr(p[0], field) == value], model)
                         for value in sorted({getattr(o, field) for o, _ in test})}
    groups["customer_type"] = {label: metrics([p for p in test if (p[0].customer_prior_orders == 0) == new], model) for label, new in [("NEW", True), ("REPEAT", False)]}
    latest_month = max(o.order_datetime.strftime("%Y-%m") for o, _ in test)
    last_month = [p for p in test if p[0].order_datetime.strftime("%Y-%m") == latest_month]
    month_result, _ = backtest(last_month, model, cfg)
    report = {"seed": 42, "data_quality": quality, "partitions": {key: {"n": len(value), "start": value[0][0].order_datetime.isoformat(), "end": value[-1][0].order_datetime.isoformat()} for key, value in [("train", train), ("validation", validation), ("test", test)]},
              "selection": {"chosen": chosen, "rule": "Simplest within 0.002 Brier of best validation model; no test tuning", "validation": validation_metrics},
              "test_models": {kind: metrics(test, model) for kind, model in fitted.items()},
              "validation_financial_comparison": {kind: backtest(validation, candidate, cfg)[0]["default_scenario"] for kind, candidate in candidates.items()},
              "test_financial_comparison": {kind: backtest(test, candidate, cfg)[0]["default_scenario"] for kind, candidate in fitted.items()},
              "test_segments": groups, "test_unseen_phones": metrics(unseen, model),
              "test_phones_also_in_earlier_partitions": len(test)-len(unseen), "backtest": result,
              "last_month": {"month": latest_month, "n": len(last_month), **month_result},
              "settings": cfg.model_dump()}
    for directory in [ROOT/"artifacts", ROOT/"reports"]:
        directory.mkdir(exist_ok=True)
    joblib.dump(model, ROOT/"artifacts/model.joblib")
    (ROOT/"reports/exclusions.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    (ROOT/"reports/evaluation.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    # Deliberately omit names, addresses and phone numbers from exported decisions.
    for row in decisions:
        row["address"].pop("review", None)
    (ROOT/"reports/holdout_decisions.json").write_text(json.dumps(decisions, indent=2, allow_nan=False), encoding="utf-8")
    findings = []
    for source in sorted({o.utm_source for o, _ in pairs}):
        ys = [y for o, y in pairs if o.utm_source == source]
        findings.append(f"| {source} | {len(ys)} | {sum(ys)} | {np.mean(ys):.2%} |")
    text = ["# Engine evaluation", "", "Generated by `python -m cod_engine.train`; seed 42. Historical associations and assumption-based scenarios, not measured intervention effects.", "", "## Data audit", "", f"Input: {quality['input_rows']}; accepted: {quality['accepted_rows']}; excluded: {quality['excluded_rows']}. All {quality['duplicate_rows_quarantined']} rows in {quality['duplicate_id_groups']} duplicate-ID groups quarantined. Full reasons: exclusions.json.", "", "Rows with usable numeric inputs but bad delivery fields remain eligible for address HOLD; they are not silently removed.", "", "## Chronological evaluation", ""]
    for key, part in report["partitions"].items():
        text.append(f"- {key}: {part['n']} orders, {part['start']} through {part['end']}.")
    text += ["", f"Selected **{chosen}**, using validation Brier and the fixed simplicity rule; refitted on train+validation. Test set never used for training/selection.", "", "| Model | Validation Brier | Test Brier | Test AUC |", "|---|---:|---:|---:|"]
    for kind in kinds:
        m = report["test_models"][kind]
        text.append(f"| {kind} | {validation_metrics[kind]['brier']:.5f} | {m['brier']:.5f} | {m['roc_auc']:.5f} |")
    text += ["", "## Holdout actions", "", "| Action | Count | Historical RTO | Historical rate |", "|---|---:|---:|---:|"]
    for action, bucket in result["buckets"].items():
        rate = f"{bucket['historical_rto_rate']:.2%}" if bucket["count"] else "n/a"
        text.append(f"| {action} | {bucket['count']} | {bucket['historical_rto_count']} | {rate} |")
    text += ["", f"Repeat-policy rejects: {result['rejected_total']}; **{result['rejected_historically_delivered']} were historically delivered**. Rejection is an explicit business policy, not a fraud classification.", "", "## Financial scenarios (Rs)", "", "No confirmation replies, conversion or offer-acceptance observations exist. Default acceptance 30% is illustrative. Policies stay fixed while a, b and acceptance vary. Converted prepaid RTO q=4% is assumed; discounts only on delivered converted orders. A single configured message cost covers each confirmation episode; nudges cost one offer plus a confirmation episode on decline. No payment fees are supplied, so none are included.", "", "| a | b | Acceptance | Avoided RTO | Foregone margin | Messages | Discounts | Net increment |", "|---|---|---|---:|---:|---:|---:|---:|"]
    for s in result["sensitivity"]:
        text.append(f"| {s['confirmation_prevention']} | {s['genuine_loss']} | {s['prepaid_acceptance']} | {s['gross_avoided_rto_cost']:.2f} | {s['net_foregone_delivered_margin']:.2f} | {s['messaging_cost']:.2f} | {s['discount_cost']:.2f} | {s['net_incremental_contribution']:.2f} |")
    text += ["", f"Default scenario: {json.dumps(result['default_scenario'])}", "", "Foregone delivered margin is signed: converted prepaid can create additional deliveries under the assumed q. Holds are assumed unshipped throughout the horizon, so delivered address-HOLD orders lose all margin here; correction/recovery is not observed. No causal effectiveness is inferred from labels.", "", f"## Latest historical month: {latest_month}", "", f"{len(last_month)} orders. Buckets: " + json.dumps(month_result["buckets"]), "", "Scenario: " + json.dumps(month_result["default_scenario"]), "", "## Descriptive acquisition-source findings (all accepted historical rows)", "", "| Source | Orders | RTO | Rate |", "|---|---:|---:|---:|", *findings, "", "These are descriptive, not causal channel effects. Calibration bins, confusion matrices, source/city/courier/customer-type metrics and candidate financial comparisons are in evaluation.json.", "", "## Leakage and limitations", "", f"Order IDs are quarantined before splitting. No identifiers, names, phone, exact street text, date or final_status enter model features. History fields are assumed to be pre-order snapshots supplied by the source; their chronology cannot be verified. {len(test)-len(unseen)} test phone occurrences also appeared earlier; unseen-phone test metrics cover {len(unseen)} rows and are in evaluation.json. Phone numbers are not reliable customer IDs, so this is only a sensitivity check.", "", "City uses train-only smoothed residuals capped at +/-2 percentage points by default; it cannot cause rejection. Pincode rates require minimum samples and shrink toward the training mean; unseen/sparse codes fall back. Logistic training uses leave-one-out pincode rates. No arbitrary feature percentages are called probabilities. Scores are statistical estimates with limited sample support, not certified calibration. Date timestamps in the CSV are treated as local business time; no future outcomes are used at inference.", "", "Run a prospective randomized pilot to measure a, b, acceptance, q, reminder costs and repeat-reject opportunity loss before claiming savings. Dataset sample is not extrapolated to 3,000 monthly orders."]
    (ROOT/"reports/backtest.md").write_text("\n".join(text)+"\n", encoding="utf-8")
    print(json.dumps({"accepted": len(pairs), "excluded": len(audit), "selected_model": chosen, "holdout": len(test), "buckets": result["buckets"], "default_scenario": result["default_scenario"]}, indent=2))


if __name__ == "__main__":
    main()
