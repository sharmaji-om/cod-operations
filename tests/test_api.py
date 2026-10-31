from fastapi.testclient import TestClient

from cod_engine.api import app

client = TestClient(app)


def test_api_decision_and_config(payload):
    result = client.post("/decide", json=payload)
    assert result.status_code == 200
    body = result.json()
    assert body["primary_action"] in {"SHIP_AS_IS", "SHIP_AFTER_CONFIRMATION", "NUDGE_TO_PREPAID", "HOLD_CANCEL"}
    assert body["reason"] and body["audit_timestamp"] and body["model_version"]
    assert client.get("/config").json()["derived_rto_loss"] == 169.4


def test_api_structured_input_errors(payload):
    for change in [{"order_value": 0}, {"customer_prior_rto": 1}, {"final_status": "DELIVERED"}]:
        response = client.post("/decide", json=payload | change)
        assert response.status_code == 422 and response.json()["detail"]


def test_invalid_config_is_explicit_503(tmp_path, monkeypatch, payload):
    path = tmp_path/"broken.json"
    path.write_text('{"confirmation_prevention": 4}')
    monkeypatch.setenv("COD_CONFIG", str(path))
    response = client.post("/decide", json=payload)
    assert response.status_code == 503 and response.json()["detail"]["code"] == "INVALID_CONFIG"
