from datetime import datetime
from pathlib import Path
import json
import math

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    gross_margin: float = Field(default=.62, gt=0, le=1)
    forward_shipping: float = Field(default=65, ge=0)
    return_shipping: float = Field(default=65, ge=0)
    packaging: float = Field(default=25, ge=0)
    damage_probability: float = Field(default=.08, ge=0, le=1)
    product_cost: float = Field(default=180, ge=0)
    confirmation_prevention: float = Field(default=.5, ge=0, le=1)
    confirmation_genuine_loss: float = Field(default=.03, ge=0, le=1)
    message_cost: float = Field(default=1, ge=0)
    reject_repeat_enabled: bool = True
    reject_trust_max: int = Field(default=-2, le=-2)
    trusted_score_min: int = Field(default=2, ge=2)
    prepaid_risk_cutoff: float = Field(default=.4, ge=0, le=1)
    discount_fraction: float = Field(default=.05, ge=0, le=1)
    discount_cap: float = Field(default=50, ge=0)
    converted_prepaid_rto: float = Field(default=.04, ge=0, le=1)
    reminder_hours: float = Field(default=24, gt=0)
    deadline_hours: float = Field(default=48, gt=0)
    source_smoothing: float = Field(default=30, gt=0)
    pincode_smoothing: float = Field(default=50, gt=0)
    pincode_min_samples: int = Field(default=15, ge=1)
    city_smoothing: float = Field(default=100, gt=0)
    city_max_adjustment: float = Field(default=.02, ge=0, le=.05)
    model_version: str = Field(default="cod-v1", min_length=1)
    llm_mode: str = "fallback"

    @model_validator(mode="after")
    def check(self):
        if self.reminder_hours >= self.deadline_hours:
            raise ValueError("reminder_hours must precede deadline_hours")
        if self.llm_mode not in {"fallback", "mock"}:
            raise ValueError("llm_mode must be fallback or mock; no external provider configured")
        return self

    @property
    def rto_loss(self):
        return self.forward_shipping + self.return_shipping + self.packaging + self.damage_probability * self.product_cost


def load_settings(path=None):
    return Settings.model_validate(json.loads(Path(path or ROOT / "config.json").read_text(encoding="utf-8")))


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    order_id: str = Field(min_length=1)
    order_datetime: datetime
    customer_name: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    pincode: str = ""
    order_value: float = Field(gt=0)
    items: str = ""
    num_items: int = Field(default=1, ge=1)
    customer_prior_orders: int = Field(ge=0)
    customer_prior_rto: int = Field(ge=0)
    utm_source: str = "unknown"
    courier: str = "unknown"
    payment_method: str = "cod"

    @field_validator("customer_prior_orders", "customer_prior_rto", "num_items", mode="before")
    @classmethod
    def integral(cls, value):
        if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) != int(float(value)):
            raise ValueError("must be a finite whole number")
        return int(float(value))

    @field_validator("order_id", "customer_name", "phone", "address", "city", "state", "pincode", "items", "utm_source", "courier", "payment_method", mode="before")
    @classmethod
    def normalize(cls, value):
        if not isinstance(value, str):
            raise ValueError("must be a string (pincode and phone must preserve leading zeros)")
        return " ".join(value.split()).lower()

    @model_validator(mode="after")
    def check(self):
        if self.customer_prior_rto > self.customer_prior_orders:
            raise ValueError("customer_prior_rto cannot exceed customer_prior_orders")
        if self.payment_method != "cod":
            raise ValueError("this engine accepts COD orders only")
        if not self.order_id:
            raise ValueError("order_id must not be blank")
        return self

    @property
    def successes(self):
        return self.customer_prior_orders - self.customer_prior_rto

    @property
    def trust(self):
        return self.customer_prior_orders - 2 * self.customer_prior_rto
