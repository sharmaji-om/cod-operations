from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from cod_engine.api import app, model
from cod_engine import store
from cod_engine.projections import Scenario, project
from cod_engine.schema import Settings


@pytest.fixture
def ops(tmp_path, monkeypatch):
    monkeypatch.setenv("COD_DB", str(tmp_path/"test.sqlite3"))
    with TestClient(app) as client:
        response = client.get("/dashboard")
        assert response.status_code == 200
        client.demo = response.json()
        client.day = client.demo["date"]
        client.rows = client.get("/orders", params={"day": client.day, "page_size": 100}).json()["items"]
        yield client


def row(client, suffix):
    return next(r for r in client.rows if r["id"].endswith(suffix))


def event(client, r, kind, **body):
    current = client.get('/simulator/'+r['id']).json()
    response = client.post(f"/simulator/{r['id']}/{kind}", json={"event_id": str(uuid4()), "generation": current["generation"], "expected_revision": current["revision"], **body})
    assert response.status_code == 200, response.text
    return response.json()


def test_initial_counts_and_exact_accounting(ops):
    d = ops.demo
    assert d["eligible_count"] == 16 == sum(d["buckets"].values())
    assert d["metrics"]["modeled_count"] == 15 and d["metrics"]["unavailable_count"] == 1
    m = d["metrics"]
    assert all(isinstance(v, int) for k,v in m.items() if k.endswith('_paise'))
    assert m["net_paise"] == m["avoided_rto_paise"]-m["foregone_margin_paise"]-m["intervention_costs_paise"]
    assert m["policy_contribution_paise"]-m["baseline_paise"] == m["net_paise"]


def test_confirmation_yes_dashboard_state_preserves_bucket(ops):
    r = event(ops, row(ops,'001'), 'reply', text=' yes ')
    assert r["status"] == 'COD_CONFIRMED'
    updated = ops.get('/dashboard').json()
    assert updated['buckets'] == ops.demo['buckets']
    assert updated['latest_states']['COD_CONFIRMED'] == 1
    r = event(ops, r, 'reply', text='NO')
    assert r['status'] == 'COD_CONFIRMED'


def test_random_reminder_expiry_no_late_yes(ops):
    r = row(ops,'002')
    r = event(ops,r,'reply',text='sure 😊')
    r = event(ops,r,'reply',text='yes please')
    assert r['status'] == 'CONFIRM_PENDING'
    assert sum(m['tag']=='clarification' for m in r['messages']) == 1
    r = event(ops,r,'advance',hours=24)
    assert r['status'] == 'REMINDER_SENT'
    start = r['confirmation_started_at']
    r = event(ops,r,'advance',hours=1)
    assert sum(m['tag']=='reminder' for m in r['messages']) == 1
    assert r['confirmation_started_at'] == start
    r = event(ops,r,'advance',hours=23)
    assert r['status'] == 'HELD_EXPIRED'
    r = event(ops,r,'reply',text='YES')
    assert r['status'] == 'HELD_EXPIRED'


def test_prepaid_accept_payment_context_discount(ops):
    r = event(ops,row(ops,'003'),'reply',text='YES')
    assert r['status'] == 'PAYMENT_PENDING' and r['offer_paise'] == 5000
    assert not r['payment_verified']
    r = event(ops,r,'reply',text='PAYMENT_SUCCESS')
    assert r['status'] == 'PAYMENT_PENDING' and not r['payment_verified']
    r = event(ops,r,'payment',outcome='failure')
    assert r['payment_failed'] and r['status'] == 'PAYMENT_PENDING'
    r = event(ops,r,'payment',outcome='success')
    assert r['status'] == 'PREPAID_CONFIRMED' and r['payment_verified']
    assert ops.get('/dashboard').json()['metrics']['discounts_paise'] > 0
    assert ops.post(f"/simulator/{r['id']}/payment",json={'outcome':'success','event_id':'late','generation':r['generation'],'expected_revision':r['revision']}).status_code == 409


def test_prepaid_no_starts_new_cod_clock(ops):
    r = event(ops,row(ops,'004'),'advance',hours=20)
    r = event(ops,r,'reply',text='NO')
    assert r['status'] == 'CONFIRM_PENDING'
    assert r['clock'] == r['confirmation_started_at']
    r = event(ops,r,'reply',text='YES')
    assert r['status'] == 'COD_CONFIRMED' and not r['payment_verified']
    assert r['initial_action'] == 'NUDGE_TO_PREPAID'


def test_repeat_boundaries_and_no_whatsapp_direct(ops):
    direct = ops.get('/simulator/'+row(ops,'005')['id']).json()
    assert direct['status']=='DIRECT_READY' and direct['messages']==[]
    assert row(ops,'006')['initial_action']=='SHIP_AFTER_CONFIRMATION'
    assert row(ops,'007')['status']=='REJECT_REPEAT'
    assert row(ops,'009')['initial_action']=='SHIP_AFTER_CONFIRMATION'
    assert row(ops,'014')['initial_action']=='SHIP_AFTER_CONFIRMATION'  # exact .4


def test_prepaid_offer_timeout(ops):
    r = event(ops,row(ops,'003'),'advance',hours=24)
    assert r['status']=='PREPAID_OFFERED' and any(m['tag']=='reminder' for m in r['messages'])
    r = event(ops,r,'advance',hours=24)
    assert r['status']=='HELD_EXPIRED'
    assert event(ops,r,'reply',text='YES')['status']=='HELD_EXPIRED'


def test_retry_dedup_and_stale_revision_generation(ops):
    r = ops.get('/simulator/'+row(ops,'001')['id']).json()
    request={'text':'YES','event_id':'same','expected_revision':r['revision'],'generation':r['generation']}
    path=f"/simulator/{r['id']}/reply"
    first=ops.post(path,json=request).json()
    again=ops.post(path,json=request).json()
    assert first==again
    assert ops.post(path,json=request|{'text':'NO'}).status_code==409
    assert ops.post(path,json=request|{'event_id':'stale'}).status_code==409
    reset=event(ops,first,'reset')
    assert reset['generation']==1 and reset['status']=='CONFIRM_PENDING'
    assert ops.post(path,json=request|{'event_id':'old-callback'}).status_code==409
    assert len(reset['events'])>len(first['events'])


def test_concurrent_retry_once(ops):
    r=row(ops,'001')
    body={'text':'YES','event_id':'parallel','generation':0,'expected_revision':0}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:ops.post(f"/simulator/{r['id']}/reply",json=body),range(2)))
    assert [r.status_code for r in results]==[200,200]
    saved=ops.get('/simulator/'+r['id']).json()
    assert sum(e['id']=='parallel' for e in saved['events'])==1
    assert sum(m['tag']=='ready' for m in saved['messages'])==1


def test_explicit_operator_reopen_and_cancel_terminal(ops):
    r=event(ops,row(ops,'011'),'resend')
    assert r['status']=='CONFIRM_PENDING'
    r=event(ops,r,'reply',text='NO')
    assert r['status']=='CANCELLED'
    assert event(ops,r,'reply',text='YES')['status']=='CANCELLED'


def test_settings_recalculate_audit_without_changing_counts(ops):
    s=ops.get('/settings').json()
    response=ops.put('/settings',json={'expected_revision':s['revision'],'policy':{'confirmation_prevention':.75},'scenario':{'prepaid_acceptance':.6,'processing_fee_fraction':.03}})
    assert response.status_code==200
    assert len(response.json()['audit'])==1
    d=ops.get('/dashboard').json()
    assert d['buckets']==ops.demo['buckets']
    assert d['metrics']['net_paise']!=ops.demo['metrics']['net_paise']
    assert ops.get('/config').json()['settings']['confirmation_prevention']==.75
    assert ops.put('/settings',json={'expected_revision':0,'policy':{}}).status_code==409
    assert ops.put('/settings',json={'expected_revision':1,'scenario':{'prepaid_acceptance':2}}).status_code==422


def test_existing_clocks_offers_frozen_after_settings_edit(ops):
    r=ops.get('/simulator/'+row(ops,'003')['id']).json()
    ops.put('/settings',json={'expected_revision':0,'policy':{'deadline_hours':72,'discount_fraction':.1,'discount_cap':100}})
    changed=ops.get('/simulator/'+r['id']).json()
    assert changed['deadline']==r['deadline'] and changed['offer_paise']==r['offer_paise']


def test_search_filter_pagination_empty_date(ops):
    assert ops.get('/simulator/conversations',params={'search':'capped discount'}).json()['total']==2
    assert ops.get('/orders',params={'day':ops.day,'decision':'NUDGE_TO_PREPAID'}).json()['total']==3
    assert len(ops.get('/orders',params={'day':ops.day,'page_size':2,'page':2}).json()['items'])==2
    empty=ops.get('/dashboard?date=2001-01-01').json()
    assert empty['eligible_count']==0 and not empty['comparison']['available']
    assert ops.get('/dashboard?date=invalid').status_code==422


def test_custom_model_order_and_engine_failure(ops, payload, monkeypatch):
    payload['order_id']='real-model-demo'
    response=ops.post('/orders',json=payload)
    assert response.status_code==201
    assert not response.json()['fixture'] and response.json()['model_version'].startswith('cod-v1/')
    assert ops.post('/orders',json=payload).status_code==409
    from cod_engine import operations
    def unavailable():
        raise RuntimeError('offline')
    monkeypatch.setattr(operations,'predictor',unavailable)
    assert ops.post('/orders',json=payload|{'order_id':'failed'}).status_code==503
    assert ops.get('/simulator/failed').status_code==404


def test_disk_persistence_across_clients(ops):
    r=event(ops,row(ops,'001'),'reply',text='YES')
    with TestClient(app) as second:
        assert second.get('/simulator/'+r['id']).json()['status']=='COD_CONFIRMED'


def test_failed_payment_cod_fallback_and_malformed_events(ops):
    r=event(ops,row(ops,'010'),'fallback')
    assert r['status']=='CONFIRM_PENDING' and not r['payment_failed']
    assert event(ops,r,'reply',text='YES')['status']=='COD_CONFIRMED'
    assert ops.post(f"/simulator/{r['id']}/advance",json={'hours':-1}).status_code==422
    assert ops.post(f"/simulator/{r['id']}/payment",json={'outcome':'unknown'}).status_code==422
    assert ops.post('/simulator/missing/reply',json={'text':'YES','event_id':'missing','generation':0,'expected_revision':0}).status_code==404


def test_event_metadata_required_and_fractional_paise_rejected(ops,payload):
    r=row(ops,'001')
    assert ops.post(f"/simulator/{r['id']}/reply",json={'text':'YES'}).status_code==422
    assert ops.post('/orders',json=payload|{'order_value':649.001}).status_code==422


def test_confirmation_money_independent_hand_calculation():
    record={'order':{'order_value':1000},'offer_paise':5000,'decision':{'predicted_rto_probability':.5,'primary_action':'SHIP_AFTER_CONFIRMATION'}}
    m=project([record],Settings(),Scenario())
    assert m['avoided_rto_paise']==4235  # .5 * .5 * 169.40
    assert m['foregone_margin_paise']==930  # .5 * .03 * 620
    assert m['messages_paise']==100
    assert m['net_paise']==3205


def test_prepaid_money_independent_hand_calculation():
    record={'order':{'order_value':1000},'offer_paise':5000,'decision':{'predicted_rto_probability':.5,'primary_action':'NUDGE_TO_PREPAID'}}
    m=project([record],Settings(),Scenario(prepaid_acceptance=1))
    assert m['avoided_rto_paise']==7792  # (.5 - .04) * 169.40
    assert m['foregone_margin_paise']==-28520  # (.04 - .5) * 620
    assert m['discounts_paise']==4800  # .96 * 50
    assert m['processing_paise']==1900  # .02 * (1000 - 50)
    assert m['net_paise']==29512
