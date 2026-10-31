import csv
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
from pathlib import Path

from pydantic import ValidationError

from .schema import Order


def load_data(path):
    raw = list(csv.DictReader(Path(path).open(encoding="utf-8-sig", newline="")))
    if not raw or set(raw[0]) != set(Order.model_fields) | {"final_status"}:
        raise ValueError("CSV header must match the supplied dataset contract exactly")
    # Quarantine ALL copies of duplicated IDs, including conflicting outcomes.
    counts = Counter(r["order_id"].strip().lower() for r in raw)
    accepted, audit = [], []
    for line, row in enumerate(raw, start=2):
        outcome = row.pop("final_status").strip().lower()
        problems = []
        if counts[row["order_id"].strip().lower()] > 1:
            problems.append("duplicate_order_id_all_copies_quarantined")
        if outcome not in {"delivered", "rto"}:
            problems.append("unresolved_or_invalid_outcome:" + outcome)
        try:
            order = Order.model_validate(row)
        except ValidationError as error:
            problems.extend("invalid:" + ".".join(map(str, e["loc"])) + ":" + e["msg"] for e in error.errors())
            order = None
        if problems:
            audit.append({"csv_line": line, "order_id": row["order_id"], "reasons": problems})
        else:
            accepted.append((order, int(outcome == "rto")))
    accepted.sort(key=lambda pair: (pair[0].order_datetime, pair[0].order_id))
    summary = {"input_rows": len(raw), "accepted_rows": len(accepted), "excluded_rows": len(audit),
               "duplicate_id_groups": sum(n > 1 for n in counts.values()),
               "duplicate_rows_quarantined": sum(n for n in counts.values() if n > 1),
               "exclusion_reason_counts": dict(Counter(reason for entry in audit for reason in entry["reasons"])),
               "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
    return accepted, audit, summary


def chronological_split(pairs):
    # Day boundaries ensure no equal timestamps leak across partitions.
    days = sorted({o.order_datetime.date() for o, _ in pairs})
    train_end = days[int(len(days)*.6)]
    validation_end = days[int(len(days)*.8)]
    train = [p for p in pairs if p[0].order_datetime.date() < train_end]
    validation = [p for p in pairs if train_end <= p[0].order_datetime.date() < validation_end]
    test = [p for p in pairs if p[0].order_datetime.date() >= validation_end]
    return train, validation, test
