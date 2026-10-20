'use strict';
const pageNames = {overview:'总览', sources:'信息源管理', mail:'邮件收件人', operations:'运行与定时', logs:'日志与报告'};
const fields = [['source_id','来源 ID'],['name','显示名称'],['homepage','主页 URL'],['feed_url','RSS / Atom URL'],['access_method','访问方式'],['permission_status','审核状态'],['reviewed_at','人工审核日期'],['last_verified_at','最近核验日期'],['freshrss_feed_id','FreshRSS Feed ID'],['canonical_domain','规范域名'],['terms_url','条款 URL'],['source_type','来源类型'],['provenance_class','来源属性'],['topic','主题'],['quality_tier','质量层级'],['expected_signal','预期信号'],['max_requests_per_day','每日文章上限'],['feed_provider','第三方 Feed 提供方'],['feed_provider_terms_url','第三方提供方条款 URL'],['review_notes','审核备注']];
let sources = [], editIndex = null, toastTimer = null, freshFeeds = [], lastMailResults = [], lastFailedDeliveries = [], lastFocus = null;

const $ = id => document.getElementById(id);
const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function toast(msg, kind = 'info') {
  const el = $('toast');
  el.textContent = msg;
  el.className = 'toast' + (kind === 'error' ? ' error' : kind === 'success' ? ' success' : '');
  el.style.display = 'block';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.style.display = 'none'; }, 5000);
}

async function api(url, method = 'GET', body) {
  const r = await fetch(url, {method, headers: body ? {'Content-Type':'application/json'} : {}, body: body ? JSON.stringify(body) : undefined, cache: 'no-store'});
  let d = {};
  try { d = await r.json(); } catch (e) { /* non-JSON error page */ }
  if (!r.ok || d.ok === false) {
    const err = d.error || {code: 'HTTP_' + r.status, message: 'HTTP ' + r.status, details: []};
    const e = new Error(err.message || ('HTTP ' + r.status));
    e.code = err.code; e.details = err.details || []; e.payload = d;
    throw e;
  }
  return d;
}

function setBusy(buttons, busy, text) {
  (buttons || []).forEach(b => { if (!b) return; b.disabled = !!busy; if (text) b.textContent = text; });
}

function stateRow(text, kind = '') {
  return `<tr><td colspan="7"><div class="state ${kind}">${esc(text)}</div></td></tr>`;
}

function applyFieldErrors(details) {
  let first = null;
  (details || []).forEach(d => {
    const m = /^sources\[\d+\]\.(.+)$/.exec(d.field || '');
    if (m) {
      const key = m[1], input = $('f-' + key);
      if (input) {
        input.setAttribute('aria-invalid', 'true');
        const err = $('err-' + key); if (err) err.textContent = d.message;
        first = first || input;
      }
    } else if ((d.field || '').startsWith('recipients')) {
      $('recipients').setAttribute('aria-invalid', 'true');
    }
  });
  if (first) first.focus();
}

function clearFieldErrors() {
  document.querySelectorAll('#source-form [aria-invalid]').forEach(x => x.removeAttribute('aria-invalid'));
  document.querySelectorAll('#source-form .field-error').forEach(x => { x.textContent = ''; });
  $('recipients').removeAttribute('aria-invalid');
}

function go(p) {
  document.querySelectorAll('.page').forEach(x => x.classList.toggle('active', x.id === 'page-' + p));
  document.querySelectorAll('[data-page]').forEach(x => x.classList.toggle('active', x.dataset.page === p));
  $('crumb').textContent = pageNames[p] || p;
  if (p === 'sources') loadSources();
  if (p === 'mail') loadRecipients();
  if (p === 'logs') loadLogs();
  window.scrollTo({top: 0, behavior: 'smooth'});
}

async function refreshAll() {
  try {
    const s = await api('/api/status');
    $('m-sources').textContent = s.source_count;
    $('m-enabled').textContent = s.enabled_sources;
    $('m-recipients').textContent = s.recipient_count;
    $('m-report').textContent = s.report_exists ? '已生成' : '尚无';
    $('m-report-date').textContent = s.report_mtime || '运行后生成';
    $('model-pill').textContent = s.model.ok ? '本地模型可访问' : '本地模型未连接';
    $('model-pill').className = 'pill ' + (s.model.ok ? 'ok' : '');
    $('s-model').textContent = s.model.url + ' · ' + s.model.detail;
    $('s-sources').textContent = s.enabled_sources + ' 个已启用 / ' + s.source_count + ' 个登记';
    $('s-report').textContent = s.report_exists ? s.report_mtime : '尚无真实日报';
    const lr = s.latest_run;
    $('s-run').textContent = lr ? `#${lr.run_id} · ${lr.status}${lr.stage ? ' · ' + lr.stage : ''} · ${lr.started_at}` : '尚无运行记录';
    $('run-state').textContent = s.run.running ? '运行中' : '空闲';
    $('smtp-host').value = s.smtp_host || '未配置';
    $('smtp-mode').value = (s.smtp_port || '—') + ' / ' + (s.smtp_security || '未配置');
    $('smtp-from').value = s.email_from || '未配置';
    const sch = s.scheduler || {};
    $('sched-state').textContent = sch.available
      ? `计划任务：${sch.state || '未知'} · 上次 ${sch.last_run || '—'} · 结果 ${sch.last_result ?? '—'} · 下次 ${sch.next_run || '—'}`
      : '计划任务状态不可用';
    document.querySelectorAll('.run-trigger').forEach(b => { b.disabled = !!s.run.running; });
    renderDeliveries(s.deliveries || []);
  } catch (e) {
    toast('状态读取失败：' + e.message, 'error');
  }
}

function renderDeliveries(rows) {
  lastFailedDeliveries = rows.filter(r => r.status === 'failed' && r.recipient).map(r => r.recipient);
  $('delivery-list').innerHTML = rows.length
    ? rows.map(r => `<div class="${r.status === 'sent' ? 'ok' : 'fail'}">${esc(r.recipient || '（无收件人）')} · ${esc(r.status)}${r.message ? ' · ' + esc(r.message) : ''}</div>`).join('')
    : '<div class="state empty">尚无投递记录</div>';
  const rb = $('resend-report'); if (rb) rb.hidden = !lastFailedDeliveries.length;
}

async function loadSources() {
  $('source-rows').innerHTML = stateRow('正在读取来源…');
  try {
    sources = (await api('/api/sources')).sources;
    renderSources();
  } catch (e) {
    $('source-rows').innerHTML = stateRow('读取失败：' + e.message, 'error');
    toast('来源读取失败：' + e.message, 'error');
  }
}

function renderSources() {
  const q = ($('source-q').value || '').toLowerCase();
  const f = $('source-status').value;
  const arr = sources.map((s, i) => ({...s, _i: i})).filter(s =>
    (!q || [s.name, s.source_id, s.canonical_domain, s.topic].join(' ').toLowerCase().includes(q)) &&
    (f === 'all' || (f === 'enabled' ? s.enabled === 'true' : f === 'disabled' ? s.enabled !== 'true' : s.permission_status === f)));
  $('source-rows').innerHTML = arr.map(s => `<tr>
    <td><b>${esc(s.name)}</b><small>${esc(s.canonical_domain)} · ${esc(s.source_id)}</small></td>
    <td>${esc(s.quality_tier || '—')}</td><td>${esc(s.topic || '—')}</td>
    <td><span class="tag ${s.permission_status === 'approved' ? 'ok' : 'warn'}">${esc(s.permission_status)}</span></td>
    <td>${esc(s.freshrss_feed_id || '—')}</td>
    <td><span class="tag ${s.enabled === 'true' ? 'ok' : ''}">${s.enabled === 'true' ? '启用' : '禁用'}</span></td>
    <td><button class="btn" onclick="editSource(${s._i})">编辑</button></td></tr>`).join('')
    || stateRow('没有匹配的来源', 'empty');
}

function defaultSource() {
  return {source_id:'new-source', name:'', homepage:'https://', feed_url:'https://', access_method:'rss', permission_status:'review_required',
          reviewed_at:'', last_verified_at:'', freshrss_feed_id:'', canonical_domain:'', terms_url:'https://', source_type:'official_blog',
          provenance_class:'first_party', topic:'', quality_tier:'B · 专业媒体', expected_signal:'', max_requests_per_day:'12',
          feed_provider:'', feed_provider_terms_url:'', review_notes:'', enabled:'false'};
}

function inputFor(k, s) {
  const common = `id="f-${k}" aria-describedby="err-${k}"`;
  if (k === 'permission_status') return `<select ${common}><option value="review_required">review_required</option><option value="approved">approved</option><option value="disabled">disabled</option></select>`;
  if (k === 'access_method') return `<select ${common}><option value="rss">rss</option><option value="atom">atom</option><option value="official_api">official_api</option><option value="authorized_email_export">authorized_email_export</option></select>`;
  if (['review_notes','expected_signal'].includes(k)) return `<textarea ${common}>${esc(s[k] || '')}</textarea>`;
  return `<input ${common} value="${esc(s[k] || '')}" ${k === 'freshrss_feed_id' ? 'list="fresh-feed-options"' : ''} ${k === 'source_id' && editIndex !== null ? 'readonly' : ''}>`;
}

function editSource(i) {
  editIndex = i;
  const s = i === null ? defaultSource() : {...sources[i]};
  $('modal-title').textContent = i === null ? '添加来源' : '编辑来源：' + s.name;
  $('source-form').innerHTML = fields.map(([k, l]) =>
    `<div class="field"><label for="f-${k}">${esc(l)}</label>${inputFor(k, s)}<div class="field-error" id="err-${k}" aria-live="polite"></div></div>`).join('');
  fields.forEach(([k]) => { const e = $('f-' + k); if (e && e.tagName === 'SELECT') e.value = s[k] || e.options[0].value; });
  $('src-enabled').checked = s.enabled === 'true';
  clearFieldErrors();
  openModal();
}

function openModal() {
  lastFocus = document.activeElement;
  $('modal').classList.add('open');
  document.body.style.overflow = 'hidden';
  const first = $('source-form').querySelector('input,select,textarea');
  if (first) first.focus();
}

function closeModal() {
  $('modal').classList.remove('open');
  document.body.style.overflow = '';
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}

function trapFocus(e) {
  const focusables = [...document.querySelectorAll('#modal button,#modal input,#modal select,#modal textarea')].filter(x => !x.disabled && x.offsetParent !== null);
  if (!focusables.length) return;
  const first = focusables[0], last = focusables[focusables.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

async function saveSource() {
  const row = {};
  fields.forEach(([k]) => { const el = $('f-' + k); if (el) row[k] = el.value.trim(); });
  row.enabled = $('src-enabled').checked ? 'true' : 'false';
  const next = [...sources];
  if (editIndex === null) {
    if (next.some(s => s.source_id === row.source_id)) { toast('来源 ID 已存在', 'error'); return; }
    next.push(row);
  } else next[editIndex] = row;
  clearFieldErrors();
  try {
    await api('/api/sources/save', 'POST', {sources: next});
    sources = (await api('/api/sources')).sources;
    closeModal(); renderSources(); refreshAll();
    toast('来源已保存。', 'success');
  } catch (e) {
    applyFieldErrors(e.details);
    toast('保存失败：' + e.message, 'error');
  }
}

async function loadFreshFeeds() {
  try {
    const d = await api('/api/freshrss-feeds');
    freshFeeds = d.feeds || [];
    $('fresh-feed-options').innerHTML = freshFeeds.map(f => `<option value="${esc(f.id)}">${esc(f.title)} — ${esc(f.url || f.site_url || '')}</option>`).join('');
    toast(`已从 FreshRSS 读取 ${freshFeeds.length} 个 Feed。`, 'success');
  } catch (e) {
    toast('读取 FreshRSS 失败：' + e.message, 'error');
  }
}

async function auditSources() {
  try {
    const d = await api('/api/source-check', 'POST', {check_urls: false});
    const issues = d.issues || [];
    toast(issues.length ? `发现 ${issues.length} 条审计提示：` + issues.slice(0, 4).map(x => x.source_id + ' ' + x.code).join('；') : '来源审计没有报告问题。',
          issues.some(x => x.severity === 'error') ? 'error' : 'success');
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function loadRecipients() {
  try {
    const d = await api('/api/recipients');
    $('recipients').value = d.recipients.join('\n');
    renderDeliveries((await api('/api/deliveries/latest')).deliveries || []);
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function saveRecipients() {
  clearFieldErrors();
  const list = $('recipients').value.split(/[\n,;]+/).map(x => x.trim()).filter(Boolean);
  try {
    const d = await api('/api/recipients/save', 'POST', {recipients: list});
    $('recipients').value = d.recipients.join('\n');
    toast('已保存 ' + d.recipients.length + ' 个收件邮箱。', 'success');
    refreshAll();
  } catch (e) {
    applyFieldErrors(e.details);
    $('mail-results').innerHTML = `<div class="fail">${esc(e.message)}</div>`;
    toast('保存失败：' + e.message, 'error');
  }
}

function renderMailResults(results, error) {
  lastMailResults = results || [];
  $('mail-results').innerHTML = lastMailResults.length
    ? lastMailResults.map(r => `<div class="${r.ok ? 'ok' : 'fail'}">${esc(r.recipient)} · ${r.ok ? '已提交' : '失败：' + esc(r.error)}</div>`).join('')
    : (error ? `<div class="fail">${esc(error.message)}</div>` : '');
  $('retry-mail').hidden = !lastMailResults.some(r => !r.ok);
}

async function testEmail() {
  const btn = document.querySelector('[onclick="testEmail()"]');
  setBusy([btn], true, '发送中…');
  $('mail-results').textContent = '正在提交测试邮件…';
  try {
    const d = await api('/api/email/test', 'POST', {});
    renderMailResults(d.results || []);
    toast(d.message || '测试邮件已提交。', 'success');
  } catch (e) {
    renderMailResults((e.payload && e.payload.results) || [], e);
    toast('发送失败：' + e.message, 'error');
  } finally {
    setBusy([btn], false, '✉ 发送测试邮件');
    refreshAll();
  }
}

async function retryFailedMail() {
  const failed = [...new Set(lastMailResults.filter(r => !r.ok).map(r => r.recipient))];
  if (!failed.length) return;
  try {
    const d = await api('/api/email/test', 'POST', {recipients: failed});
    renderMailResults(d.results || []);
    toast('失败地址已重试。', 'success');
  } catch (e) {
    renderMailResults((e.payload && e.payload.results) || [], e);
    toast('重试失败：' + e.message, 'error');
  }
  refreshAll();
}

async function resendReport() {
  if (!lastFailedDeliveries.length) return;
  try {
    const d = await api('/api/email/resend', 'POST', {recipients: [...new Set(lastFailedDeliveries)]});
    toast('最新日报已重发给 ' + d.count + ' 个地址。', 'success');
  } catch (e) {
    toast('重发失败：' + e.message, 'error');
  }
  refreshAll();
}

async function runDigest() {
  const btns = [...document.querySelectorAll('.run-trigger')];
  setBusy(btns, true);
  $('run-result').textContent = '正在启动…';
  try {
    const d = await api('/api/run', 'POST', {});
    $('run-result').textContent = d.message + ' PID ' + d.pid;
    toast(d.message, 'success');
  } catch (e) {
    $('run-result').textContent = '启动失败：' + e.message;
    toast('启动失败：' + e.message, 'error');
  }
  setTimeout(refreshAll, 1000);
}

async function saveSchedule() {
  $('schedule-result').textContent = '正在注册…';
  try {
    const d = await api('/api/schedule', 'POST', {start_time: $('schedule-time').value || '08:00'});
    $('schedule-result').textContent = d.output || '定时任务已注册';
    const sch = d.scheduler || {};
    if (sch.available) $('sched-state').textContent = `计划任务：${sch.state || '未知'} · 上次 ${sch.last_run || '—'} · 结果 ${sch.last_result ?? '—'} · 下次 ${sch.next_run || '—'}`;
    toast('定时任务已注册。', 'success');
  } catch (e) {
    $('schedule-result').textContent = '注册失败：' + e.message;
    toast('注册失败：' + e.message, 'error');
  }
}

async function loadLogs() {
  try {
    const d = await api('/api/logs');
    $('log-app').textContent = d.application || '暂无应用日志';
    $('log-admin').textContent = d.admin || '暂无管理日志';
    $('log-scheduler').textContent = d.scheduler || '暂无定时任务日志';
  } catch (e) {
    toast(e.message, 'error');
  }
}

document.addEventListener('keydown', e => {
  if (!$('modal').classList.contains('open')) return;
  if (e.key === 'Escape') { e.preventDefault(); closeModal(); }
  if (e.key === 'Tab') trapFocus(e);
});
document.querySelectorAll('[data-page]').forEach(x => { x.onclick = () => go(x.dataset.page); });
refreshAll();
setInterval(() => { if (!document.hidden) refreshAll(); }, 15000);

async function copyLog(id) {
  const text = ($(id) && $(id).textContent) || '';
  try {
    await navigator.clipboard.writeText(text);
    toast('日志已复制。', 'success');
  } catch (e) {
    toast('复制失败，请手动选择文本。', 'error');
  }
}
