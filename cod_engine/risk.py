"""Train-only aggregates and a small, explicitly bounded city adjustment."""
from collections import defaultdict
import math

import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression

from .address import assess


class RiskModel:
    def __init__(self, kind, cfg):
        self.kind, self.cfg, self.version = kind, cfg, f"{cfg.model_version}/{kind}"

    def fit(self, pairs):
        self.rate = float(np.mean([y for _, y in pairs]))
        self.trained_through = max(o.order_datetime for o, _ in pairs).isoformat()
        self.maps = {}
        for field, smoothing, minimum in [("utm_source", self.cfg.source_smoothing, 1),
                                           ("pincode", self.cfg.pincode_smoothing, self.cfg.pincode_min_samples)]:
            buckets = defaultdict(list)
            for o, y in pairs:
                buckets[getattr(o, field)].append(y)
            self.maps[field] = {key: (sum(v)+smoothing*self.rate)/(len(v)+smoothing) for key, v in buckets.items() if len(v) >= minimum}
        if self.kind == "logistic":
            self.vectorizer = DictVectorizer(sparse=True)
            # Avoid using each training row's target through its own pincode rate.
            # Logistic pincode input uses leave-one-out counts during training only.
            pin = defaultdict(list)
            for o, y in pairs:
                pin[o.pincode].append(y)
            features = []
            for o, y in pairs:
                f = self.features(o)
                v = pin[o.pincode]
                f["pincode_rate"] = (sum(v)-y+self.cfg.pincode_smoothing*self.rate)/(len(v)-1+self.cfg.pincode_smoothing) if len(v)-1 >= self.cfg.pincode_min_samples else self.rate
                features.append(f)
            x = self.vectorizer.fit_transform(features)
            self.model = LogisticRegression(C=.5, max_iter=2000, random_state=42)
            self.model.fit(x, [y for _, y in pairs])
        self.city_adjustments = {}
        if self.kind != "overall":
            residuals = defaultdict(list)
            for o, y in pairs:
                residuals[o.city].append(y-self.base_predict(o))
            cap = self.cfg.city_max_adjustment
            self.city_adjustments = {city: float(np.clip(sum(v)/(len(v)+self.cfg.city_smoothing), -cap, cap)) for city, v in residuals.items()}
        return self

    def features(self, o):
        category = assess(o)["category"]
        return {"source": o.utm_source, "courier": o.courier, "log_order_value": math.log(o.order_value),
                "address_category": category, "prior_orders": o.customer_prior_orders / 5,
                "prior_rto": o.customer_prior_rto / 5,
                "pincode_rate": self.maps["pincode"].get(o.pincode, self.rate)}

    def base_predict(self, o):
        if self.kind == "overall":
            return self.rate
        if self.kind == "segment":
            return self.maps["utm_source"].get(o.utm_source, self.rate)
        return float(self.model.predict_proba(self.vectorizer.transform([self.features(o)]))[0, 1])

    def predict(self, o):
        return float(np.clip(self.base_predict(o) + self.city_adjustments.get(o.city, 0), .001, .999))
