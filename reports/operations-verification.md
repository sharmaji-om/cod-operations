# Simulator and founder ledger verification

Date: 2026-10-31, Asia/Kolkata. Local-only implementation of all Parts 2+3 in the supplied brief. See INTEGRATION_PLAN.md for the integration map and wireframe.

## Automated results

From the BP folder:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --check .\web\app.js
.\.venv\Scripts\python.exe -m pip check
```

Actual final results: **89 passed**, no warnings; JavaScript syntax check exited successfully; `No broken requirements found.`

The suite retains all 70 original engine tests and adds 19 persistent operations/accounting tests. Coverage includes all six functional acceptance scenarios, semantic prompt context, separate payment verification, prepaid decline/fallback, random input, single clarification/reminder, exact expiry and late replies, operator reopen/reset, mandatory event metadata, duplicate/concurrent callbacks, conflicting IDs, stale revisions/generations, immutable buckets, settings validation/audit, prior clock/offer preservation, search/filter/pagination, unavailable engine, restart persistence and independent monetary hand calculations.

Independent calculation checks:

- Confirmation on a Rs 1,000 order at p=.5, a=.5, b=.03, C=1 gives Rs 42.35 avoided RTO, Rs 9.30 foregone margin and Rs 32.05 net increment.
- Fully accepted prepaid on the same order at q=.04, discount Rs 50 and processing fee 2% gives Rs 77.92 avoided RTO, Rs -285.20 net foregone margin, Rs 48 discount, Rs 19 processing and Rs 295.12 net increment after messaging. The negative margin-loss component represents modeled additional deliveries, not a measured gain.

## Browser walkthroughs performed

- 1440x1000 desktop: loaded the actual app; checked editorial ledger and three-pane studio. An explicit COD YES reached COD_CONFIRMED. A prepaid YES reached PAYMENT_PENDING; separate mock success reached PREPAID_CONFIRMED. Prepaid NO began a new COD confirmation; the following YES reached COD_CONFIRMED.
- Edited confirmation prevention from 50% to 75% through the UI: modeled daily impact changed from Rs 427.39 to Rs 576.42 while buckets remained 2/9/3/2 (16 orders). Restored the 50% assumption afterwards; settings audit retained both edits.
- 390x844: checked phone layout, visible coverage and single-column reading order. Found and corrected root horizontal overflow from a hidden table header. Verified document width 375px within the 390px viewport (15px scrollbar); table scrolling stays contained.
- On mobile: unrecognized reply sent clarification without confirmation; +24h produced REMINDER_SENT and exactly one reminder; advancing to the original deadline produced HELD_EXPIRED. Keyboard Enter opened the context drawer and exposed held state/history.
- Keyboard Enter opened a metric definition; Escape closed the native modal and returned focus. Buttons/selects/inputs expose accessible names. Reviewed reduced-motion CSS and text equivalents for segments. No full screen-reader certification is claimed.
- A separate QA server intentionally pointed at a missing model. The UI displayed a meaningful 503/unavailable state with a Retry button and hid financial content; no replacement success/metrics were fabricated.
- Browser console inspection after the successful flows returned no error entries. Syntax check also passed independently.

## Saved screenshots

- screenshots/ledger-desktop.jpg
- screenshots/simulator-desktop.jpg
- screenshots/ledger-mobile.jpg
- screenshots/simulator-mobile.jpg
- screenshots/engine-unavailable.jpg

The screenshots show fictional fixtures and scenario projections. They are not evidence of real business outcomes. The original historical evaluation remains unchanged in backtest.md/evaluation.json. Browser-driven examples retain their QA event history in the local database; Reset scenario restores the initial step without erasing history.

## Known limits

Default language is English; optional Hindi/Hinglish templates are not implemented. No real payment/WhatsApp/fulfillment integration exists. Payment-pending expiry is unspecified and not invented. Readiness does not create a shipment. Processing costs and intervention effectiveness are explicit scenarios; unknown address-hold risk is excluded from modeled totals with coverage shown. Financial snapshots inherited from the engine keep its original response contract; all dashboard aggregation and displayed totals use Decimal/integer paise. Persistent settings override file defaults after the first save. Model-training settings require retraining/restart. The app is a loopback local demo without production authentication or deployment.
