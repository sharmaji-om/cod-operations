from functools import lru_cache
import os

from fastapi import FastAPI, HTTPException
import joblib
from pydantic import ValidationError

from .policy import decide
from .schema import ROOT, Order, load_settings
from .operations import current_settings, router, ensure_seed
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="COD Operations", version="2.0.0", description="Decision engine, persistent WhatsApp mock and founder ledger. No real messages, payments or shipments.")


@lru_cache
def model():
    path = ROOT / os.getenv("COD_MODEL", "artifacts/model.joblib")
    if not path.is_file():
        raise HTTPException(status_code=503, detail={"code": "MODEL_NOT_TRAINED", "message": "Run python -m cod_engine.train first."})
    # Local trusted artifacts only; never load an uploaded pickle/joblib file.
    return joblib.load(path)


def settings():
    try:
        return current_settings()[0]
    except (OSError, ValueError, ValidationError) as error:
        raise HTTPException(status_code=503, detail={"code": "INVALID_CONFIG", "message": str(error)}) from error


@app.get("/health")
def health():
    return {"status": "ok", "model_version": model().version}


@app.get("/config")
def config():
    cfg = settings()
    return {"settings": cfg.model_dump(), "derived_rto_loss": cfg.rto_loss,
            "risk_training_settings": model().cfg.model_dump(),
            "note": "Policy/economics reload per request. Retrain after changing risk smoothing, city cap or model version."}


@app.post("/decide")
def decision(order: Order):
    cfg, predictor = settings(), model()
    result = decide(order, predictor, cfg)
    if any(getattr(cfg, key) != getattr(predictor.cfg, key) for key in ("source_smoothing", "pincode_smoothing", "pincode_min_samples", "city_smoothing", "city_max_adjustment", "model_version")):
        result["warnings"].append("Model settings changed; retrain to apply them. Reported model version is the actual artifact version.")
    if order.order_datetime.isoformat() <= predictor.trained_through:
        result["warnings"].append("Order predates model training cutoff; this API result is not an out-of-time evaluation.")
    return result


app.include_router(router)
app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "web/index.html")
