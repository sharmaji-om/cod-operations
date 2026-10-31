"""Conservative delivery checks. Semantic review cannot cancel a person."""
import re


def assess(order, mode="fallback", reviewer=None):
    missing = [k for k in ("address", "city", "state") if not getattr(order, k).strip()]
    if not re.fullmatch(r"[1-9][0-9]{5}", order.pincode):
        missing.append("valid six-digit Indian pincode")
    if order.address in {"test", "asdf", "na", "n/a", "none", "unknown"} or len(order.address) < 5:
        missing.append("usable street/locality")
    if missing:
        return {"category": "BAD_UNDELIVERABLE", "quality_score": 0, "reason": "Correct: " + ", ".join(missing), "review": None, "warnings": []}
    suspicious = order.customer_name in {"test", "asdf", "fake", "abc"}
    incomplete = not bool(re.search(r"\d", order.address))
    category = "SUSPICIOUS" if suspicious else "INCOMPLETE" if incomplete else "VALID"
    result = {"category": category, "quality_score": {"VALID": 1, "INCOMPLETE": .5, "SUSPICIOUS": 0}[category],
              "reason": "Deterministic format check; deliverability is not verified.", "review": None, "warnings": []}
    if category != "VALID":
        result["warnings"].append("Address/name may need human review; this is not a fraud finding.")
        if mode == "mock" or reviewer:
            # Only street text, no phone/name/order identifier is passed to a future provider.
            try:
                output = reviewer({"address": order.address}) if reviewer else {"category": category, "rationale": "Mock semantic review; no external call."}
                if output.get("category") not in {"VALID", "INCOMPLETE", "SUSPICIOUS", "BAD_UNDELIVERABLE"} or not isinstance(output.get("rationale"), str):
                    raise ValueError("malformed semantic response")
                result["review"] = {"output": output, "applied": False, "reason": "Advisory only; deterministic fallback retained."}
            except Exception as exc:
                result["review"] = {"error": type(exc).__name__, "fallback": category}
                result["warnings"].append("Semantic review failed; deterministic checks used.")
    return result
