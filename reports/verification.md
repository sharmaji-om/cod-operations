# Engine-phase verification

For the subsequent 89-test simulator/dashboard verification, see operations-verification.md.

Run from `C:\Users\shash\OneDrive\Desktop\Om\BP` with the included Python 3.12 virtual environment.

```powershell
.\.venv\Scripts\python.exe -m cod_engine.train
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

Results on 2026-10-31:

- Training: 1,950 accepted historical orders; 68 audited exclusions. Logistic selected on validation Brier.
- Chronological holdout: 412 orders; action counts 120 ship, 260 confirm, 2 prepaid nudge, 30 hold/cancel.
- Test Brier: approximately 0.17433; ROC-AUC approximately 0.69390. Full precision is saved in evaluation.json.
- Tests: 70 passed, no warnings on final dependency set.
- Dependencies: `No broken requirements found.`
- API integration tests exercise POST /decide, GET /config, numeric/history/extra-field HTTP 422 errors and invalid-config HTTP 503. Actual full sample API responses are saved under examples/.

The default holdout scenario gives Rs 45.99 incremental contribution, using a=.5, b=.03, acceptance=.3 and converted-prepaid q=.04. This is an assumed counterfactual, not measured business savings. Some sensitivity scenarios lose money. See backtest.md for the component accounting and limitations.

The service run command is:

```powershell
.\.venv\Scripts\python.exe -m uvicorn cod_engine.api:app --host 127.0.0.1 --port 8000
```

No production messages, payment actions, shipments or public deployments were performed.
