'use strict';
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cash = (paise) => new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format((paise ?? 0)/100);
const pct = (v) => v == null ? 'Unavailable' : `${(v*100).toFixed(1)}%`;
const time = (v, date = false) => v ? new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata', ...(date ? {day:'numeric',month:'short'} : {}),hour:'2-digit',minute:'2-digit',hour12:true}).format(new Date(v)) : '—';
const human = (v) => String(v ?? '').toLowerCase().replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
const buckets = {
  SHIP_AS_IS:{label:'Ship directly', color:'#35665e', note:'Ready without a message'},
  SHIP_AFTER_CONFIRMATION:{label:'WhatsApp confirmation', color:'#8ca593', note:'An explicit YES before dispatch'},
  NUDGE_TO_PREPAID:{label:'Prepaid nudge', color:'#b7c5ac', note:'An offer, never a rejection'},
  HOLD_CANCEL:{label:'Hold / cancel', color:'#c4a36c', note:'Correction or history review'}
};
const state = {dashboard:null, date:'', decision:'', status:'', page:1, conversations:[], conversation:null, settings:null, busy:false, view:'ledger'};
const drawer = $('drawer');
let previousFocus;

async function api(path, options = {}) {
  const response = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
  let body;
  try { body = await response.json(); } catch { throw new Error('The service returned an unreadable response. Please retry.'); }
  if (!response.ok) {
    const detail = body.detail;
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(e=>`${e.loc?.slice(1).join('.')}: ${e.msg}`).join('; ') : detail?.message || 'The operation could not be completed.';
    throw new Error(`${message} (${response.status})`);
  }
  return body;
}
function showError(id, error, retry) {
  const box = $(id); box.hidden = false;
  box.innerHTML = `<strong>Service unavailable or request could not be completed.</strong><br>${esc(error.message)} ${retry ? '<button class="secondary" id="retry-action">Retry</button>' : ''}`;
  if (retry) $('retry-action').onclick = retry;
}
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('toast').hidden=true,4000); }
function openDrawer(title, body, label='OPERATIONS DESK') {
  previousFocus=document.activeElement;
  $('drawer-title').textContent=title; $('drawer-eyebrow').textContent=label; $('drawer-body').innerHTML=body;
  if (!drawer.open) drawer.showModal();
  $('close-drawer').focus();
}
function closeDrawer(){drawer.close();if(previousFocus?.isConnected)previousFocus.focus();}
$('close-drawer').onclick=closeDrawer;
drawer.addEventListener('click',e=>{if(e.target===drawer && e.clientX<drawer.getBoundingClientRect().left)closeDrawer();});
drawer.addEventListener('cancel',()=>{if(previousFocus?.isConnected)previousFocus.focus();});
function badge(value) {
  const good=['DIRECT_READY','COD_CONFIRMED','PREPAID_CONFIRMED'].includes(value);
  const bad=['CANCELLED'].includes(value);
  const review=['HELD_EXPIRED','HOLD_ADDRESS','REJECT_REPEAT','PAYMENT_PENDING'].includes(value);
  return `<span class="status ${good?'good':bad?'bad':review?'review':''}">${esc(human(value))}</span>`;
}
function detailList(rows){return `<dl class="detail-list">${rows.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join('')}</dl>`;}

async function navigate(view) {
  state.view=view; location.hash=view;
  $('ledger').hidden=view!=='ledger'; $('studio').hidden=view!=='studio';
  document.querySelectorAll('[data-nav]').forEach(b=>{b.classList.toggle('active',b.dataset.nav===view);b.setAttribute('aria-current',b.dataset.nav===view?'page':'false');});
  if(view==='ledger') await loadDashboard(); else await loadConversations();
}
document.querySelectorAll('[data-nav]').forEach(b=>b.onclick=()=>navigate(b.dataset.nav));
window.addEventListener('hashchange',()=>{const view=location.hash.slice(1);if(['ledger','studio'].includes(view)&&view!==state.view)navigate(view);});
async function loadDashboard() {
  $('ledger-error').hidden=true; $('ledger-content').setAttribute('aria-busy','true');
  try {
    const d=await api('/dashboard'+(state.date?`?date=${state.date}`:''));
    state.dashboard=d;state.date=d.date;
    $('ledger-content').hidden=false;
    renderDashboard(d);await loadOrders();
  } catch(error) { $('ledger-content').hidden=true;showError('ledger-error',error,loadDashboard); }
  finally {$('ledger-content').setAttribute('aria-busy','false');}
}
function renderDashboard(d) {
  const m=d.metrics;
  $('date-select').value=d.date;
  const isYesterday=d.date===new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(Date.now()-86400000));
  $('ledger-title').innerHTML=`COD operations <span>/ ${isYesterday?'Yesterday':'Daily ledger'}</span>`;
  $('date-caption').textContent=`${new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',weekday:'long',day:'numeric',month:'long',year:'numeric'}).format(new Date(d.date+'T12:00:00+05:30'))} · Asia/Kolkata`;
  $('net-value').className='hero-number'+(m.net_paise<0?' negative':'');
  $('net-value').textContent=d.eligible_count ? (m.modeled_count ? `${m.net_paise>0?'+':''}${cash(m.net_paise)}` : 'Unavailable') : '—';
  $('baseline-caption').textContent=d.eligible_count ? `Expected contribution ${cash(m.policy_contribution_paise)} vs ${cash(m.baseline_paise)} shipping all modeled COD orders. ${m.modeled_count}/${d.eligible_count} modeled · ${m.unavailable_count} unavailable.` : 'No eligible orders for this date. Choose a seeded date below.';
  $('avoided-value').textContent=m.modeled_count?cash(m.avoided_rto_paise):'—';
  $('margin-value').textContent=m.modeled_count?cash(m.foregone_margin_paise):'—';
  $('costs-value').textContent=m.modeled_count?cash(m.intervention_costs_paise):'—';
  $('coverage-label').textContent=`${m.modeled_count} of ${d.eligible_count} orders modeled · ${m.unavailable_count} unavailable`;
  $('order-total').textContent=`${d.eligible_count} eligible orders · demo`;
  $('bucket-bar').innerHTML=Object.entries(buckets).filter(([key])=>d.buckets[key]).map(([key,b])=>`<button class="bar-segment" style="flex:${d.buckets[key]};background:${b.color}" data-bucket="${key}" aria-label="${b.label}: ${d.buckets[key]} orders, ${pct(d.buckets[key]/d.eligible_count)}. ${b.note}" title="${b.label}: ${d.buckets[key]} · ${pct(d.buckets[key]/d.eligible_count)}"></button>`).join('');
  $('bucket-strip').innerHTML=Object.entries(buckets).map(([key,b])=>`<button class="bucket-card ${state.decision===key?'active':''}" data-bucket="${key}" aria-pressed="${state.decision===key}"><span class="bucket-label"><i class="bucket-dot" style="background:${b.color}"></i>${b.label}</span><strong class="bucket-count">${d.buckets[key]}</strong><span class="bucket-percentage">${d.eligible_count?pct(d.buckets[key]/d.eligible_count):'0%'}</span><small class="bucket-note">${b.note} ↗</small></button>`).join('');
  document.querySelectorAll('[data-bucket]').forEach(b=>b.onclick=()=>selectBucket(b.dataset.bucket));
  $('insight-heading').textContent=d.comparison.available ? d.comparison.confirmation_count_delta===0?'Confirmation volume held steady.':`${Math.abs(d.comparison.confirmation_count_delta)} ${d.comparison.confirmation_count_delta>0?'more':'fewer'} conversations to start.` : 'No comparison available.';
  $('insight-text').textContent=d.comparison.text+' Counts reflect initial decisions. Operational replies are shown separately.';
  $('operational-summary').innerHTML=Object.entries(d.latest_states).slice(0,5).map(([k,v])=>`<span class="quiet-chip">${v} ${esc(human(k))}</span>`).join('');
  $('exception-count').textContent=d.exceptions.length;
  $('exception-list').innerHTML=d.exceptions.length?d.exceptions.slice(0,5).map(exceptionRow).join(''):`<div class="empty-state">No exceptions for this date.${!d.eligible_count?`<br>Demo dates: ${d.available_dates.map(date=>`<button class="text-button seed-date" data-date="${date}">${date}</button>`).join(' · ')}`:''}</div>`;
  wireOrderButtons($('exception-list'));
  document.querySelectorAll('.seed-date').forEach(b=>b.onclick=()=>{state.date=b.dataset.date;state.page=1;loadDashboard();});
  $('updated-label').textContent=`Updated ${time(d.last_updated,true)} IST · ${m.modeled_count}/${d.eligible_count} orders modeled · not realized cash savings`;
}
function exceptionRow(r){return `<button class="exception-row" data-order="${esc(r.id)}"><span><strong>${esc(r.id.toUpperCase())}</strong><span class="exception-label">${esc(r.exception_reason)} · ${r.age_hours.toFixed(0)}h simulated age</span><small>${esc(r.next_action)}</small></span><span class="exception-arrow" aria-hidden="true">↗</span></button>`;}
function wireOrderButtons(parent){parent.querySelectorAll('[data-order]').forEach(b=>b.onclick=()=>openOrder(b.dataset.order));}
$('date-select').onchange=e=>{state.date=e.target.value;state.page=1;loadDashboard();};
$('review-button').onclick=()=>$('exceptions').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});
$('view-exceptions').onclick=()=>{const list=state.dashboard?.exceptions||[];openDrawer('The exceptions queue',list.length?list.map(exceptionRow).join(''):'<p class="empty-state">No exceptions for this date.</p>','REVIEW / SIMULATED OPERATIONS');wireOrderButtons($('drawer-body'));};
async function loadOrders(){
  const q=new URLSearchParams({day:state.date,page:String(state.page),decision:state.decision,status:state.status});
  try {
    const data=await api('/orders?'+q);
    $('orders-body').innerHTML=data.items.length?data.items.map(r=>`<tr><td><strong>${esc(r.id.toUpperCase())}</strong><small>${esc(r.customer_name)}</small></td><td>${cash(r.value_paise)}</td><td><span class="bucket-dot" style="background:${buckets[r.initial_action].color}"></span> ${buckets[r.initial_action].label}</td><td>${badge(r.status)}</td><td>${pct(r.risk)}<small> ${r.fixture?'fixture':'model'}</small></td><td><button class="text-button" data-order="${esc(r.id)}" aria-label="View ${esc(r.id)}">Details ↗</button></td></tr>`).join(''):'<tr><td colspan="6" class="empty-state">No orders match these filters.</td></tr>';
    wireOrderButtons($('orders-body'));
    $('page-label').textContent=data.total?`${(state.page-1)*10+1}–${Math.min(state.page*10,data.total)} of ${data.total} orders`:'0 orders';
    $('prev-page').disabled=state.page===1;$('next-page').disabled=state.page*10>=data.total;
  }catch(error){$('orders-body').innerHTML=`<tr><td colspan="6" role="alert">${esc(error.message)}</td></tr>`;}
}
$('decision-filter').onchange=e=>{state.decision=e.target.value;state.page=1;loadOrders();document.querySelectorAll('.bucket-card').forEach(b=>{b.classList.toggle('active',b.dataset.bucket===state.decision);b.setAttribute('aria-pressed',String(b.dataset.bucket===state.decision));});};
$('status-filter').onchange=e=>{state.status=e.target.value;state.page=1;loadOrders();};
$('prev-page').onclick=()=>{state.page--;loadOrders();};$('next-page').onclick=()=>{state.page++;loadOrders();};
async function selectBucket(key){
  state.decision=key;state.page=1;$('decision-filter').value=key;await loadOrders();
  document.querySelectorAll('.bucket-card').forEach(b=>{b.classList.toggle('active',b.dataset.bucket===key);b.setAttribute('aria-pressed',String(b.dataset.bucket===key));});
  const data=await api(`/orders?day=${state.date}&decision=${key}&page_size=100`);
  openDrawer(buckets[key].label,`<p class="drawer-intro">${data.total} initial decisions on ${esc(state.date)}. ${esc(buckets[key].note)}. The latest operational state never changes this original bucket.</p>${data.items.map(r=>`<button class="exception-row" data-order="${esc(r.id)}"><span><strong>${esc(r.id.toUpperCase())} · ${cash(r.value_paise)}</strong><small>${esc(r.reason)}</small><small>Risk: ${pct(r.risk)} · ${esc(r.fixture?'controlled demo fixture':'trained model')} · observed RTO: unavailable</small></span><span>↗</span></button>`).join('')||'<p class="empty-state">No orders in this bucket.</p>'}`,'DECISION BREAKDOWN');
  wireOrderButtons($('drawer-body'));
}
async function openOrder(id){try{const r=await api('/simulator/'+encodeURIComponent(id));openDrawer(r.id.toUpperCase(),orderDetails(r)+`<div class="drawer-actions"><button class="primary" id="open-conversation">Open in message studio →</button></div>`,'ORDER / INITIAL DECISION');$('open-conversation').onclick=async()=>{closeDrawer();state.conversation=r;await navigate('studio');await selectConversation(r.id);};}catch(e){toast(e.message);}}
function orderDetails(r){return `<p class="drawer-intro">${esc(r.customer_name)} · ${r.fixture?'Fictional seeded order / controlled risk fixture':'Custom order / trained model'}</p>${detailList([['Order value',cash(r.value_paise)],['Initial decision',esc(buckets[r.initial_action].label)],['Latest state',badge(r.status)],['Estimated risk',pct(r.risk)],['Observed delivery outcome','Unavailable'],['Prior successes / trust',`${r.decision.prior_successes} / ${r.decision.trust_score}`],['Policy rule',esc(r.decision.triggered_rule_ids.join(', '))],['Address check',esc(human(r.address_category))],['Model version',esc(r.model_version)],['Discount offered',r.initial_action==='NUDGE_TO_PREPAID'?cash(r.offer_paise):'Not applicable']])}<div class="detail-reason">${esc(r.reason)}</div><p class="muted">Next: ${esc(r.required_next_step)}</p>`;}

const infos={net:['Net estimated impact','Expected policy contribution minus shipping-all-COD contribution. For the selected business date and modeled orders only. Scenario, not realized savings.'],avoided:['RTO loss avoided','Sum of modeled prevented returns × configured RTO loss. Converted prepaid has its own assumed RTO rate. Includes only orders with stored risk; scenario estimate.'],margin:['Net foregone delivered margin','Margin lost when interventions block otherwise delivered orders, less modeled conversion delivery gains. It may be negative. Gross margin × order value; assumptions, not observed loss.'],costs:['Intervention costs','Estimated message episodes, delivered prepaid discounts and processing fees on assumed accepted payments. Uses the selected date’s initial decisions and editable assumptions.']};
document.querySelectorAll('[data-info]').forEach(b=>{b.title=infos[b.dataset.info][1];b.onclick=()=>{const [title,text]=infos[b.dataset.info];openDrawer(title,`<p class="tooltip-card">${esc(text)}</p><p class="muted">Window: ${esc(state.date)}, 00:00–23:59 Asia/Kolkata. Denominator: ${state.dashboard?.metrics.modeled_count||0} modeled orders of ${state.dashboard?.eligible_count||0} eligible orders.</p><button class="text-button" id="info-calculation">View calculation →</button>`,'METRIC DEFINITION');$('info-calculation').onclick=showCalculation;};});
function showCalculation(){const d=state.dashboard;if(!d)return;const m=d.metrics;openDrawer('A contribution ledger',`<p class="drawer-intro">${esc(d.date)} · Asia/Kolkata. A scenario over immutable initial decisions, not realized savings. ${m.modeled_count}/${d.eligible_count} orders modeled; ${m.unavailable_count} unavailable because no risk estimate exists.</p>${detailList([['Ship-all COD contribution',cash(m.baseline_paise)],['RTO loss avoided',cash(m.avoided_rto_paise)],['Less: net foregone margin',cash(m.foregone_margin_paise)],['Less: message episodes',cash(m.messages_paise)],['Less: delivered discounts',cash(m.discounts_paise)],['Less: payment processing',cash(m.processing_paise)],['Net estimated increment',`<strong>${cash(m.net_paise)}</strong>`],['Policy contribution',cash(m.policy_contribution_paise)]])}<p class="formula">M = margin × order value<br>L = forward + return + packaging + damage × product cost<br>COD = (1 − p)M − pL<br>Confirm increment = paL − (1 − p)bM − C<br>Net = avoided RTO − foregone margin − intervention costs</p><p class="drawer-intro">${esc(m.discount_basis)}<br>${esc(m.processing_basis)}<br>${esc(m.hold_basis)}<br>Acquisition spend is sunk. Signed foregone margin includes modeled converted-delivery gains. All displayed totals reconcile to integer paise.</p><button class="primary" id="calculation-assumptions">Edit scenario assumptions</button>`,'CALCULATION / SCENARIO');$('calculation-assumptions').onclick=openSettings;}
$('calculation-button').onclick=showCalculation;$('assumptions-link').onclick=openSettings;$('settings-button').onclick=openSettings;
const assumptionFields=[['confirmation_prevention','Potential RTOs prevented','%',100],['confirmation_genuine_loss','Genuine deliveries blocked','%',100],['converted_prepaid_rto','Converted prepaid RTO','%',100],['message_cost','Message cost per episode','₹',1],['gross_margin','Delivered gross margin','%',100]];
const policyFields=[['prepaid_risk_cutoff','New-buyer prepaid cutoff','%',100],['discount_fraction','Prepaid discount','%',100],['discount_cap','Maximum discount','₹',1],['reminder_hours','Reminder after','hours',1],['deadline_hours','Response deadline','hours',1],['trusted_score_min','Trusted repeat score','score',1],['reject_trust_max','Zero-success reject cutoff','score',1],['forward_shipping','Forward shipping','₹',1],['return_shipping','Return shipping','₹',1],['packaging','Packaging / handling','₹',1],['damage_probability','Damage probability','%',100],['product_cost','Product cost','₹',1]];
function numberField(group,key,label,unit,scale,values){return `<label class="field"><span>${esc(label)} (${unit})</span><input type="number" step="any" required name="${group}.${key}" data-scale="${scale}" value="${Number((values[key]*scale).toFixed(6))}"></label>`;}
async function openSettings(){
  try{
    const s=await api('/settings');state.settings=s;
    openDrawer('Make the assumptions visible.',`<p class="drawer-intro">Changing these values runs a scenario. Observed initial bucket counts remain unchanged. Policy edits apply to future orders; existing offers and clocks are preserved.</p><form id="settings-form"><h3 class="form-section-title">Scenario economics</h3><div class="form-grid">${assumptionFields.map(f=>numberField('policy',...f,s.policy)).join('')}${numberField('scenario','prepaid_acceptance','Prepaid offer acceptance','%',100,s.scenario)}${numberField('scenario','processing_fee_fraction','Payment processing fee','%',100,s.scenario)}${numberField('scenario','processing_fee_fixed_paise','Fixed processing fee','paise',1,s.scenario)}</div><details><summary class="form-section-title">Policy & offer settings</summary><div class="form-grid">${policyFields.map(f=>numberField('policy',...f,s.policy)).join('')}<label class="field full"><span>Repeat rejection with zero successes</span><select name="policy.reject_repeat_enabled"><option value="true" ${s.policy.reject_repeat_enabled?'selected':''}>Enabled under configured negative trust cutoff</option><option value="false" ${!s.policy.reject_repeat_enabled?'selected':''}>Disabled; require confirmation instead</option></select></label><label class="field full"><span>Demo brand in future messages</span><input name="scenario.brand" maxlength="60" required value="${esc(s.scenario.brand)}"></label></div></details><p class="drawer-intro">Acceptance, confirmation effectiveness, genuine loss and converted-prepaid risk are unmeasured assumptions. Processing is charged per assumed accepted transaction on discounted order value. Live LLMs and WhatsApp are not connected.</p><p id="settings-feedback" class="form-feedback" role="alert"></p><button class="primary" type="submit">Apply scenario & save settings →</button></form><details><summary class="form-section-title">Settings audit (${s.audit.length} recent)</summary><ul class="audit-list">${s.audit.map(a=>`<li>Revision event #${a.id}<small>${time(a.at,true)} IST · before/after snapshots persisted</small></li>`).join('')||'<li>No saved edits yet.</li>'}</ul></details>`,'ASSUMPTIONS / SIMULATION');
    $('settings-form').onsubmit=async(e)=>{e.preventDefault();const body={expected_revision:s.revision,policy:{},scenario:{}};new FormData(e.target).forEach((value,key)=>{const [group,name]=key.split('.');const input=e.target.elements.namedItem(key);body[group][name]=name==='brand'?value:name==='reject_repeat_enabled'?value==='true':Number(value)/Number(input.dataset.scale||1);});const btn=e.target.querySelector('[type=submit]');btn.disabled=true;try{await api('/settings',{method:'PUT',body:JSON.stringify(body)});closeDrawer();toast('Settings saved. Scenario estimates recalculated.');if(state.view==='ledger')await loadDashboard();else await loadConversations();}catch(error){$('settings-feedback').textContent=error.message;btn.disabled=false;}};
  }catch(error){toast(error.message);}
}

async function loadConversations(){
  $('studio-error').hidden=true;
  try{const data=await api('/simulator/conversations');state.conversations=data.items;renderConversations();if(state.conversation){const fresh=data.items.find(r=>r.id===state.conversation.id);if(fresh)await selectConversation(fresh.id);}else if(data.items.length)await selectConversation(data.items.find(r=>r.status==='CONFIRM_PENDING')?.id||data.items[0].id);}
  catch(error){$('conversation-list').innerHTML='';$('messages').innerHTML='<div class="chat-empty"><h3>The engine is unavailable.</h3>Orders are unavailable while the decision service is offline. Retry when the service is ready.</div>';$('chat-controls').innerHTML='';showError('studio-error',error,loadConversations);}
}
function renderConversations(){const search=$('conversation-search').value.toLowerCase();const list=state.conversations.filter(r=>(r.id+r.customer_name+r.scenario_note).toLowerCase().includes(search));$('conversation-count').textContent=`${list.length} orders`;$('conversation-list').innerHTML=list.length?list.map(r=>`<button class="conversation-item ${state.conversation?.id===r.id?'selected':''}" data-conversation="${esc(r.id)}" aria-pressed="${state.conversation?.id===r.id}"><div><strong>${esc(r.customer_name)}</strong><small>${time(r.created_at)}</small></div><p>${esc(r.scenario_note||buckets[r.initial_action].label)}</p><div class="conv-bottom"><span>${esc(r.id.toUpperCase())}</span><span>${r.hours_remaining!=null?`${r.hours_remaining.toFixed(0)}h left`:esc(human(r.status))} <i class="small-dot" aria-hidden="true"></i></span></div></button>`).join(''):'<p class="empty-state">No conversations match your search.</p>';document.querySelectorAll('[data-conversation]').forEach(b=>b.onclick=()=>selectConversation(b.dataset.conversation));}
$('conversation-search').oninput=renderConversations;
async function selectConversation(id){try{state.conversation=await api('/simulator/'+encodeURIComponent(id));renderConversations();renderChat();}catch(error){showError('studio-error',error,()=>selectConversation(id));}}
function contextContent(r){return `<p class="eyebrow">ORDER CONTEXT</p><h2>${esc(r.id.toUpperCase())}</h2>${detailList([['Value',cash(r.value_paise)],['Initial decision',esc(buckets[r.initial_action].label)],['Current state',badge(r.status)],['Risk',`${pct(r.risk)} ${r.fixture?'· controlled fixture':'· trained model'}`],['Prior successes / trust',`${r.decision.prior_successes} / ${r.decision.trust_score}`],['Prepaid offer',r.initial_action==='NUDGE_TO_PREPAID'?cash(r.offer_paise):'Not applicable']])}<div class="detail-reason">${esc(r.reason)}</div><details><summary>Event history · ${r.events.length}</summary><ul class="audit-list">${r.events.slice().reverse().map(e=>`<li><strong>${esc(human(e.to))}</strong><br>${esc(e.reason)}<small>${time(e.at,true)} IST · ${esc(e.source)} · ${esc(e.from||'new')} → ${esc(e.to)}</small><small>Event ${esc(e.id)} · generation ${e.generation}</small></li>`).join('')}</ul></details><p class="muted">Messages and time are simulated. Ready means eligible for processing; no shipment is created.</p>`;}
function renderChat(){
  const r=state.conversation;if(!r)return;
  $('chat-header').innerHTML=`<div class="chat-person"><span class="avatar" aria-hidden="true">${esc(r.customer_name[0]||'?')}</span><div><h2>${esc(r.customer_name)}</h2><small>${esc(r.id.toUpperCase())} · simulated conversation</small></div></div><button class="icon-btn mobile-context" id="context-button" aria-label="Show order context and event history">ⓘ</button>`;
  $('context-button').onclick=()=>openDrawer(r.id.toUpperCase(),contextContent(r),'ORDER CONTEXT');
  $('clock-bar').innerHTML=`<span>SIMULATED CLOCK · ${time(r.clock,true)} IST</span><span>${r.hours_remaining!=null?`${r.hours_remaining.toFixed(1)}h remaining`:esc(human(r.status))}</span>`;
  const messageHtml=r.messages.map(m=>`<div class="message ${m.direction==='incoming'?'incoming':''}"><span class="sr-only">${m.direction==='incoming'?'Customer:':'Brand:'}</span>${esc(m.text)}<time datetime="${esc(m.at)}">${time(m.at)} · ${m.direction==='incoming'?'received':'simulated ✓✓'}</time></div>`).join('');
  $('messages').innerHTML=r.messages.length?`<div class="message system">Demo only · no real WhatsApp account is connected</div>${messageHtml}`:`<div class="chat-empty"><h3>${r.status==='DIRECT_READY'?'Straight to processing.':'A deliberate pause.'}</h3><p>${r.status==='DIRECT_READY'?'This order does not need a WhatsApp message.':esc(r.reason)}</p>${badge(r.status)}</div>`;
  $('messages').scrollTop=$('messages').scrollHeight;
  $('chat-context').innerHTML=contextContent(r);
  const pending=['CONFIRM_PENDING','REMINDER_SENT','PREPAID_OFFERED'].includes(r.status);
  const payment=r.status==='PAYMENT_PENDING';
  const expired=r.status==='HELD_EXPIRED';
  const terminal=['COD_CONFIRMED','PREPAID_CONFIRMED','CANCELLED'].includes(r.status);
  const context=r.status==='PREPAID_OFFERED'?'YES → mock payment · NO → new COD confirmation':pending?'YES → confirm COD · NO → cancel COD':payment?'A reply cannot verify payment. Use the mock adapter below.':terminal?'Final state: replies cannot release or cancel this order again.':expired?'Expired: shipment blocked. Operator review is required.':'This decision has no customer messaging step.';
  $('chat-controls').innerHTML=`<p class="context-label">${esc(context)}</p>${pending?'<div class="quick-replies"><button class="primary" data-reply="YES">Reply YES</button><button class="secondary" data-reply="NO">Reply NO</button><button class="secondary" data-reply="Maybe later 🙂">Send other text</button></div>':''}${payment?'<div class="quick-replies"><button class="primary" data-payment="success">Simulate payment success</button><button class="secondary" data-payment="failure">Simulate payment failure</button><button class="secondary" data-command="fallback">Use COD instead</button></div>':''}${pending||payment||terminal||expired?'<form class="reply-input" id="reply-form"><label class="sr-only" for="reply-text">Simulated customer reply</label><input id="reply-text" maxlength="1000" placeholder="Type a simulated customer reply…" required><button class="secondary" type="submit">Send reply</button></form>':''}<div class="time-controls">${r.messages.length?'<button class="secondary" data-advance="24">Advance +24h</button><button class="secondary" id="to-deadline">Advance to deadline</button>':''}${expired?'<button class="secondary" data-command="resend">Operator: reopen confirmation</button>':''}<button class="secondary" data-command="reset">Reset scenario</button></div>`;
  $('chat-controls').querySelectorAll('[data-reply]').forEach(b=>b.onclick=()=>command('reply',{text:b.dataset.reply}));
  $('chat-controls').querySelectorAll('[data-payment]').forEach(b=>b.onclick=()=>command('payment',{outcome:b.dataset.payment}));
  $('chat-controls').querySelectorAll('[data-command]').forEach(b=>b.onclick=()=>command(b.dataset.command,{}));
  $('chat-controls').querySelectorAll('[data-advance]').forEach(b=>b.onclick=()=>command('advance',{hours:Number(b.dataset.advance)}));
  if($('reply-form'))$('reply-form').onsubmit=e=>{e.preventDefault();command('reply',{text:$('reply-text').value});};
  if($('to-deadline'))$('to-deadline').onclick=()=>command('advance',{hours:r.hours_remaining??48});
}
async function command(kind,payload){
  if(state.busy)return;state.busy=true;$('studio-error').hidden=true;
  const r=state.conversation;const focused=document.activeElement?.textContent;
  $('chat-controls').querySelectorAll('button').forEach(b=>b.disabled=true);
  try{
    const data=await api(`/simulator/${encodeURIComponent(r.id)}/${kind}`,{method:'POST',body:JSON.stringify({...payload,event_id:crypto.randomUUID(),expected_revision:r.revision,generation:r.generation})});
    state.conversation=data;renderChat();const list=await api('/simulator/conversations');state.conversations=list.items;renderConversations();
    toast(kind==='reset'?'Scenario reset. Earlier events remain in the audit.':`State: ${human(data.status)}`);
    const replacement=[...$('chat-controls').querySelectorAll('button')].find(b=>b.textContent===focused);(replacement||$('reply-text')||$('chat-header')).focus?.();
  }catch(error){showError('studio-error',error,()=>selectConversation(r.id));await selectConversation(r.id);}
  finally{state.busy=false;$('chat-controls').querySelectorAll('button').forEach(b=>b.disabled=false);}
}
$('create-order').onclick=()=>{
  const id=`custom-${Date.now().toString(36)}`;
  const fields=[['order_id','Order ID',id],['customer_name','Customer name','Demo Buyer'],['order_value','Order value (₹)','649','number'],['customer_prior_orders','Prior orders','0','number'],['customer_prior_rto','Prior returns','0','number'],['address','Delivery address','12 MG Road near school'],['city','City','Pune'],['state','State','Maharashtra'],['pincode','Pincode (text)','411001'],['utm_source','Acquisition source','meta_ads'],['courier','Courier','Delhivery']];
  openDrawer('Try the real decision engine',`<p class="drawer-intro">This creates a custom simulated order using the actual trained model. No fixed risk overrides, real messages, payments or shipments.</p><form id="order-form"><div class="form-grid">${fields.map(([key,label,value,type])=>`<label class="field ${key==='address'?'full':''}"><span>${label}</span><input name="${key}" type="${type||'text'}" value="${esc(value)}" required ${type==='number'?'step="any"':''}></label>`).join('')}</div><p id="order-feedback" class="form-feedback" role="alert"></p><button class="primary" type="submit">Evaluate & create conversation →</button></form>`,'CUSTOM ORDER / TRAINED MODEL');
  $('order-form').onsubmit=async(e)=>{e.preventDefault();const values=Object.fromEntries(new FormData(e.target));for(const key of ['order_value','customer_prior_orders','customer_prior_rto'])values[key]=Number(values[key]);const body={...values,order_datetime:new Date().toISOString(),phone:'9000000000',payment_method:'COD',items:'Demo haircare kit',num_items:1};const button=e.target.querySelector('[type=submit]');button.disabled=true;try{const r=await api('/orders',{method:'POST',body:JSON.stringify(body)});closeDrawer();state.date=r.day;state.conversation=r;await loadConversations();toast('Created using the trained engine.');}catch(error){$('order-feedback').textContent=error.message;button.disabled=false;}};
};
navigate(location.hash==='#studio'?'studio':'ledger');
