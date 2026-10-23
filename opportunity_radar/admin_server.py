"""Local-only admin UI for Opportunity Radar. Binds exclusively to loopback."""
from __future__ import annotations
import csv, hashlib, json, os, re, subprocess, sys, threading, time, uuid
from datetime import datetime
from email.utils import parseaddr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .config import Settings, load_dotenv
from .email_sender import send_email_detailed, parse_recipients
from .freshrss_client import FreshRSSClient
from .log_util import redact
from .source_policy import load_sources
from .source_audit import audit_sources, check_url, url_targets
from .store import Store

ROOT = Path.cwd().resolve()
UI_FILE = ROOT / 'admin' / 'index.html'
ASSETS = {
    '/assets/app.css': (ROOT / 'admin' / 'assets' / 'app.css', 'text/css; charset=utf-8'),
    '/assets/app.js': (ROOT / 'admin' / 'assets' / 'app.js', 'application/javascript; charset=utf-8'),
}
RECIPIENT_FILE = ROOT / 'config' / 'recipients.json'
SOURCE_FIELDS = ['source_id','name','homepage','feed_url','access_method','permission_status','reviewed_at','review_notes','max_requests_per_day','enabled','freshrss_feed_id','source_type','provenance_class','canonical_domain','terms_url','last_verified_at','feed_provider','feed_provider_terms_url','topic','quality_tier','expected_signal','editorial_lanes','topic_tags','source_authority','content_access_level','source_cap']
ERROR_CODES = ['VALIDATION_ERROR','FORBIDDEN','SOURCE_VALIDATION_FAILED','FRESHRSS_UNAVAILABLE','MODEL_UNAVAILABLE','SMTP_FAILED',
               'SMTP_AUTH_FAILED','RUN_ALREADY_ACTIVE','SCHEDULE_FAILED','REPORT_MISSING','NOT_FOUND','INTERNAL_ERROR']
SOURCE_LOCK = threading.Lock()
RUN_LOCK = threading.Lock()
RUN_PROCESS: subprocess.Popen | None = None
RUN_STARTED = ''
RUN_BASELINE: int | None = None
SCHED_CACHE = {'at': 0.0, 'data': None}


def source_file():
    """Edit the active local registry when OR_SOURCES_PATH is set; the repo candidate file is the default."""
    return Path(os.environ.get('OR_SOURCES_PATH') or ROOT / 'config' / 'sources.csv')


def report_dir():
    return Path(Settings.from_env().report_dir)


def read_sources(path=None):
    p = Path(path) if path else source_file()
    if not p.exists(): return []
    with p.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_sources(rows, path=None):
    target = Path(path) if path else source_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.csv.tmp')
    with tmp.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=SOURCE_FIELDS, extrasaction='ignore')
        w.writeheader()
        for row in rows:
            w.writerow({k: str(row.get(k, '') if row.get(k) is not None else '').strip() for k in SOURCE_FIELDS})
    os.replace(tmp, target)


def read_recipients():
    if RECIPIENT_FILE.exists():
        try:
            data = json.loads(RECIPIENT_FILE.read_text(encoding='utf-8'))
            return data.get('recipients', []) if isinstance(data, dict) else []
        except (OSError, ValueError, TypeError): return []
    return parse_recipients(Settings.from_env().email_to)


def valid_email(address):
    _, parsed = parseaddr(str(address))
    return bool(parsed and parsed == str(address) and re.fullmatch(r"[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+", str(address)))


def validate_source_rows(rows):
    """Field-level validation so the UI can point at the exact input that is wrong."""
    details = []
    if not isinstance(rows, list) or not rows:
        return [{'field': 'sources', 'message': 'at least one source row is required'}]
    seen = set()
    for i, row in enumerate(rows):
        row = row or {}
        sid = str(row.get('source_id', '')).strip()
        if not sid: details.append({'field': f'sources[{i}].source_id', 'message': 'source_id is required'})
        elif not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', sid): details.append({'field': f'sources[{i}].source_id', 'message': 'source_id must be 1-80 chars of letters, digits, dot, dash or underscore'})
        elif sid in seen: details.append({'field': f'sources[{i}].source_id', 'message': f'duplicate source_id: {sid}'})
        seen.add(sid)
        # A candidate under review may have no verified endpoint yet; an enabled source
        # may not. Emptying feed_url is the honest record for "no feed found", and is
        # preferred over putting a publisher page in a column named feed_url.
        for field, limit in (('name', 200), ('feed_url', 1000), ('homepage', 1000), ('terms_url', 1000), ('review_notes', 2000)):
            value = str(row.get(field, '')).strip()
            if field == 'name' and not value: details.append({'field': f'sources[{i}].{field}', 'message': f'{field} is required'})
            if len(value) > limit: details.append({'field': f'sources[{i}].{field}', 'message': f'{field} must be at most {limit} characters'})
        feed = str(row.get('feed_url', '')).strip().lower()
        if feed and not feed.startswith('https://'): details.append({'field': f'sources[{i}].feed_url', 'message': 'feed_url must use HTTPS'})
        enabled = str(row.get('enabled', '')).lower() in {'true', '1', 'yes', 'on'}
        if enabled and not feed: details.append({'field': f'sources[{i}].feed_url', 'message': 'enabled sources need a verified feed_url'})
        if enabled and str(row.get('permission_status', '')).lower() != 'approved':
            details.append({'field': f'sources[{i}].permission_status', 'message': 'enabled sources require permission_status=approved'})
        feed_id = str(row.get('freshrss_feed_id', '')).strip()
        if enabled and not feed_id: details.append({'field': f'sources[{i}].freshrss_feed_id', 'message': 'enabled sources need a FreshRSS Feed ID'})
        if feed_id and not feed_id.isdigit(): details.append({'field': f'sources[{i}].freshrss_feed_id', 'message': 'FreshRSS Feed ID must be numeric'})
    return details


def validate_recipient_list(addresses):
    if not isinstance(addresses, list) or not addresses:
        return [{'field': 'recipients', 'message': 'at least one recipient is required'}]
    details = []
    for i, item in enumerate(addresses):
        address = str(item).strip()
        if not valid_email(address): details.append({'field': f'recipients[{i}]', 'message': f'invalid email address: {address}'})
    return details


def source_validation(rows):
    # Validate a temporary registry through the same rules used by the CLI.
    temp = source_file().with_name('.sources-admin-validation.csv')
    try:
        with temp.open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=SOURCE_FIELDS, extrasaction='ignore'); w.writeheader()
            for row in rows: w.writerow({k: str(row.get(k, '') or '').strip() for k in SOURCE_FIELDS})
        return [x for x in audit_sources(load_sources(str(temp))) if x['severity'] == 'error']
    finally:
        try: temp.unlink()
        except OSError: pass


def local_model_health():
    s = Settings.from_env()
    url = s.llm_base_url.removesuffix('/v1') + '/health'
    try:
        req = Request(url, headers={'Authorization': 'Bearer ' + s.llm_api_key}, method='GET')
        with urlopen(req, timeout=1.5) as r: return {'ok': 200 <= r.status < 300, 'detail': f'HTTP {r.status}', 'url': url}
    except Exception as e: return {'ok': False, 'detail': type(e).__name__, 'url': url}


def tail(path, lines=80):
    p = Path(path)
    if not p.is_absolute(): p = ROOT / p
    try: return '\n'.join(p.read_text(encoding='utf-8', errors='replace').splitlines()[-lines:])
    except OSError: return ''


def scheduler_status():
    """Expose the Windows task state so the UI can show last run and exit code, not just 'registered'."""
    if os.name != 'nt': return {'available': False, 'detail': 'not running on Windows'}
    now = time.time()
    if SCHED_CACHE['data'] is not None and now - SCHED_CACHE['at'] < 10:
        return SCHED_CACHE['data']
    command = ("$t=Get-ScheduledTask -TaskName 'OpportunityRadarDaily' -ErrorAction Stop;"
               "$i=Get-ScheduledTaskInfo -TaskName 'OpportunityRadarDaily';"
               "[pscustomobject]@{state=[string]$t.State;last_run=[string]$i.LastRunTime;"
               "last_result=[int]$i.LastTaskResult;next_run=[string]$i.NextRunTime} | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command], capture_output=True, text=True, timeout=12)
        raw = (out.stdout or '').strip()
        data = json.loads(raw) if raw else {}
        data['available'] = bool(raw)
        if out.returncode: data['error'] = (out.stderr or out.stdout)[-500:]
    except Exception as e:
        data = {'available': False, 'error': f'{type(e).__name__}: {e}'}
    SCHED_CACHE.update(at=now, data=data)
    return data


def smtp_error_code(exc):
    text = str(exc).lower()
    if 'auth' in text or '535' in text or 'login' in text: return 'SMTP_AUTH_FAILED'
    return 'SMTP_FAILED'


def finalize_launcher(store):
    """If the launcher died before the CLI created a run row, persist that failure too."""
    global RUN_PROCESS, RUN_BASELINE, RUN_STARTED
    if not RUN_PROCESS or RUN_PROCESS.poll() is None: return
    code = RUN_PROCESS.returncode
    try:
        latest = store.latest_run()
        if latest is None or (RUN_BASELINE is not None and latest['run_id'] <= RUN_BASELINE):
            rid = store.start_run(stage='launcher')
            store.finish_run(rid, 'failed', 0, 0, 1, f'launcher exited with code {code}', exit_code=code)
    except Exception:
        pass
    RUN_PROCESS = None; RUN_BASELINE = None; RUN_STARTED = ''


class Handler(BaseHTTPRequestHandler):
    server_version = 'OpportunityRadarLocalAdmin/1.1'

    def log_message(self, fmt, *args):
        print('[admin] ' + redact(fmt % args))

    def _request_id(self):
        return uuid.uuid4().hex[:12]

    def _json(self, payload, status=200):
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status); self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw))); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(raw)

    def _ok(self, payload=None, status=200):
        data = {'ok': True, 'request_id': self._request_id()}
        if payload: data.update(payload)
        self._json(data, status)

    def _error(self, code, message, status=400, details=None, extra=None):
        envelope = {'ok': False, 'request_id': self._request_id(),
                    'error': {'code': code, 'message': message, 'details': details or []}}
        if extra: envelope.update(extra)
        self._json(envelope, status)

    def _text(self, data, content_type='text/plain; charset=utf-8', status=200):
        raw = data.encode('utf-8'); self.send_response(status); self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw))); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(raw)

    def _body(self):
        length = int(self.headers.get('Content-Length', '0'))
        if length < 0 or length > 1_000_000: raise ValueError('Request body too large')
        return json.loads(self.rfile.read(length).decode('utf-8')) if length else {}

    def _check_local(self):
        host = self.headers.get('Host', '').split(':')[0].strip('[]').lower()
        if host not in {'127.0.0.1', 'localhost', '::1'}:
            self._error('FORBIDDEN', 'Only local browser access is allowed', 403); return False
        origin = self.headers.get('Origin')
        if origin:
            parsed = urlparse(origin)
            if parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
                self._error('FORBIDDEN', 'Cross-origin request blocked', 403); return False
        return True

    def do_GET(self):
        if not self._check_local(): return
        path = urlparse(self.path).path
        try:
            if path in {'/', '/admin'}:
                try: self._text(UI_FILE.read_text(encoding='utf-8'), 'text/html; charset=utf-8')
                except OSError: self._error('NOT_FOUND', 'Admin UI not found. Start from the project root.', 500)
            elif path in ASSETS:
                file, ctype = ASSETS[path]
                try: self._text(file.read_text(encoding='utf-8'), ctype)
                except OSError: self._error('NOT_FOUND', f'Asset not found: {path}', 404)
            elif path == '/api/contract':
                self._ok({'version': '1.1', 'error_codes': ERROR_CODES,
                          'endpoints': ['/api/status','/api/sources','/api/sources/save','/api/recipients','/api/recipients/save',
                                        '/api/freshrss-feeds','/api/audit','/api/source-check','/api/email/test','/api/email/resend',
                                        '/api/deliveries/latest','/api/run','/api/schedule','/api/logs','/report']})
            elif path == '/api/status':
                s = Settings.from_env(); store = Store(s.db_path)
                previous = RUN_PROCESS
                finalize_launcher(store)
                running = bool(RUN_PROCESS and RUN_PROCESS.poll() is None)
                latest = store.latest_run()
                rd = report_dir(); report = rd / 'latest-digest.html'
                self._ok({'model': local_model_health(), 'source_count': len(read_sources()),
                          'enabled_sources': sum(str(x.get('enabled','')).lower() == 'true' for x in read_sources()),
                          'recipient_count': len(read_recipients()), 'report_exists': report.exists(),
                          'report_mtime': datetime.fromtimestamp(report.stat().st_mtime).isoformat(timespec='seconds') if report.exists() else None,
                          'report_dir': str(rd),
                          'run': {'running': running, 'pid': RUN_PROCESS.pid if running else None, 'started_at': RUN_STARTED or None,
                                  'just_finished': bool(previous and not RUN_PROCESS)},
                          'latest_run': latest, 'deliveries': store.latest_deliveries(), 'scheduler': scheduler_status(),
                          'smtp_host': s.smtp_host, 'smtp_port': s.smtp_port, 'email_from': s.email_from,
                          'smtp_security': s.smtp_security or ('starttls' if s.smtp_starttls else 'none'),
                          'log_tail': redact(tail(s.log_path, 30))})
            elif path == '/api/sources':
                self._ok({'sources': read_sources(), 'fields': SOURCE_FIELDS, 'source_file': str(source_file())})
            elif path == '/api/recipients':
                self._ok({'recipients': read_recipients()})
            elif path == '/api/freshrss-feeds':
                s = Settings.from_env()
                missing = [k for k, v in {'OR_FRESHRSS_USERNAME': s.freshrss_username, 'OR_FRESHRSS_API_KEY': s.freshrss_api_key}.items() if not v or v.startswith('replace_')]
                if missing: self._error('VALIDATION_ERROR', '缺少 FreshRSS 配置：' + ', '.join(missing), 400, [{'field': m, 'message': 'missing'} for m in missing])
                else:
                    try: self._ok({'feeds': FreshRSSClient(s.freshrss_base_url, s.freshrss_username, s.freshrss_api_key, s.request_timeout).list_feeds()})
                    except Exception as e: self._error('FRESHRSS_UNAVAILABLE', f'读取 FreshRSS 失败：{type(e).__name__}', 502)
            elif path == '/api/audit':
                self._ok({'issues': audit_sources(load_sources(str(source_file())))})
            elif path == '/api/deliveries/latest':
                self._ok({'deliveries': Store(Settings.from_env().db_path).latest_deliveries()})
            elif path == '/api/logs':
                s = Settings.from_env(); rd = report_dir()
                self._ok({'application': redact(tail(s.log_path, 200)), 'admin': redact(tail(rd / 'admin-run.log', 200)),
                          'scheduler': redact(tail(rd / 'scheduler-run.log', 100)), 'cli': redact(tail(rd / 'cli-run.log', 200))})
            elif path == '/report':
                report = report_dir() / 'latest-digest.html'
                if report.exists(): self._text(report.read_text(encoding='utf-8'), 'text/html; charset=utf-8')
                else: self._text('<h2>尚无真实日报</h2><p>先运行一次日报任务。</p>', 'text/html; charset=utf-8', 404)
            else: self._error('NOT_FOUND', 'Not found', 404)
        except Exception as e:
            self._error('INTERNAL_ERROR', f'{type(e).__name__}', 500)

    def do_POST(self):
        if not self._check_local(): return
        path = urlparse(self.path).path
        try: data = self._body()
        except Exception as e: self._error('VALIDATION_ERROR', str(e), 400); return
        try:
            if path == '/api/sources/save': self._save_sources(data)
            elif path == '/api/recipients/save': self._save_recipients(data)
            elif path == '/api/email/test': self._email_test(data)
            elif path == '/api/email/resend': self._email_resend(data)
            elif path == '/api/run': self._run_digest()
            elif path == '/api/schedule': self._schedule(data)
            elif path == '/api/source-check': self._source_check(data)
            else: self._error('NOT_FOUND', 'Not found', 404)
        except Exception as e:
            self._error('INTERNAL_ERROR', f'{type(e).__name__}: {str(e)[:300]}', 500)

    def _save_sources(self, data):
        rows = data.get('sources')
        details = validate_source_rows(rows)
        if details: self._error('VALIDATION_ERROR', '来源字段校验失败', 400, details); return
        for row in rows:
            row['enabled'] = 'true' if str(row.get('enabled','')).lower() in {'true','1','yes','on'} else 'false'
            row['permission_status'] = str(row.get('permission_status','review_required')).strip().lower()
        errors = source_validation(rows)
        if errors:
            self._error('SOURCE_VALIDATION_FAILED', '启用来源未通过审计', 400,
                        [{'field': x['source_id'], 'message': f"{x['code']}: {x['message']}"} for x in errors]); return
        with SOURCE_LOCK:
            write_sources(rows)
        self._ok({'count': len(rows), 'source_file': str(source_file())})

    def _save_recipients(self, data):
        addresses = data.get('recipients', [])
        details = validate_recipient_list(addresses)
        if details: self._error('VALIDATION_ERROR', '收件邮箱校验失败', 400, details); return
        clean = []; seen = set()
        for item in addresses:
            address = str(item).strip()
            if address.casefold() not in seen: seen.add(address.casefold()); clean.append(address)
        RECIPIENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = RECIPIENT_FILE.with_suffix('.json.tmp')
        tmp.write_text(json.dumps({'recipients': clean, 'updated_at': datetime.now().astimezone().isoformat(timespec='seconds')}, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, RECIPIENT_FILE)
        self._ok({'recipients': clean})

    def _email_test(self, data=None):
        s = Settings.from_env(); issues = s.validate_mail()
        if issues: self._error('VALIDATION_ERROR', '邮件配置不完整', 400, [{'field': i.split()[0], 'message': i} for i in issues]); return
        recipients = (data or {}).get('recipients') or read_recipients()
        details = validate_recipient_list(recipients)
        if details: self._error('VALIDATION_ERROR', '收件邮箱校验失败', 400, details); return
        results = send_email_detailed(s.smtp_host, s.smtp_port, s.smtp_username, s.smtp_password, s.email_from, recipients,
                                      '[Opportunity Radar] 本地 SMTP 测试',
                                      '这是一封由本机 Opportunity Radar 管理页面发送的测试邮件。\n如果你收到这封邮件，说明 SMTP 提交流程正常。',
                                      s.smtp_starttls, security=s.smtp_security)
        failed = [r for r in results if not r['ok']]
        if failed:
            self._error('SMTP_FAILED', '部分收件人发送失败', 502,
                        [{'field': r['recipient'], 'message': r['error']} for r in failed], {'results': results}); return
        self._ok({'results': results, 'count': len(results), 'message': 'SMTP 已提交；请检查收件箱和垃圾邮件。'})

    def _email_resend(self, data):
        addresses = data.get('recipients', [])
        details = validate_recipient_list(addresses)
        if details: self._error('VALIDATION_ERROR', '收件邮箱校验失败', 400, details); return
        rd = report_dir(); txt_path = rd / 'latest-digest.txt'; html_path = rd / 'latest-digest.html'
        if not txt_path.exists(): self._error('REPORT_MISSING', '尚无可用日报，先运行一次日报任务。', 409); return
        raw = txt_path.read_text(encoding='utf-8')
        subject, _, body = raw.partition('\n\n')
        html = html_path.read_text(encoding='utf-8') if html_path.exists() else None
        s = Settings.from_env()
        results = send_email_detailed(s.smtp_host, s.smtp_port, s.smtp_username, s.smtp_password, s.email_from, addresses,
                                      subject or 'Opportunity Radar', body, s.smtp_starttls, html=html, security=s.smtp_security)
        store = Store(s.db_path); latest = store.latest_run(); rid = latest['run_id'] if latest else None
        key = 'retry-' + hashlib.sha256(raw.encode()).hexdigest()[:16]
        for res in results:
            store.delivery(rid, 'sent' if res['ok'] else 'failed', res.get('error',''), key, res['recipient'])
        failed = [r for r in results if not r['ok']]
        if failed:
            self._error('SMTP_FAILED', '部分重试失败', 502, [{'field': r['recipient'], 'message': r['error']} for r in failed], {'results': results}); return
        self._ok({'results': results, 'count': len(results)})

    def _run_digest(self):
        global RUN_PROCESS, RUN_STARTED, RUN_BASELINE
        with RUN_LOCK:
            s = Settings.from_env(); store = Store(s.db_path)
            finalize_launcher(store)
            if RUN_PROCESS and RUN_PROCESS.poll() is None:
                self._error('RUN_ALREADY_ACTIVE', '已有日报任务正在运行', 409, [{'field': 'run_id', 'message': str(store.latest_run() and store.latest_run().get('run_id'))}]); return
            active = store.active_run()
            if active:
                self._error('RUN_ALREADY_ACTIVE', '数据库中已有运行中的任务', 409, [{'field': 'run_id', 'message': str(active['run_id'])}]); return
            rd = report_dir(); rd.mkdir(parents=True, exist_ok=True)
            log_path = rd / 'admin-run.log'; log_file = log_path.open('a', encoding='utf-8')
            log_file.write(f"\n\n=== Admin run started {datetime.now().astimezone().isoformat(timespec='seconds')} ===\n"); log_file.flush()
            try:
                baseline = store.latest_run(); RUN_BASELINE = baseline['run_id'] if baseline else 0
                if os.name == 'nt':
                    command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'deploy' / 'windows' / 'run-digest.ps1')]
                else:
                    command = [sys.executable, '-m', 'opportunity_radar.cli']
                RUN_PROCESS = subprocess.Popen(command, cwd=str(ROOT), stdout=log_file, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                RUN_STARTED = datetime.now().astimezone().isoformat(timespec='seconds')
                self._ok({'pid': RUN_PROCESS.pid, 'message': '日报已启动；Windows 下会先尝试启动 Docker 与本地模型。可在运行记录查看状态。'})
            except Exception as e:
                log_file.close(); self._error('INTERNAL_ERROR', f'启动失败：{type(e).__name__}', 500)

    def _schedule(self, data):
        start = str(data.get('start_time', '08:00'))
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', start):
            self._error('VALIDATION_ERROR', '时间格式必须为 HH:MM', 400, [{'field': 'start_time', 'message': 'expected HH:MM'}]); return
        script = ROOT / 'deploy' / 'windows' / 'install-task.ps1'
        if os.name != 'nt':
            self._error('SCHEDULE_FAILED', '定时任务注册需要在 Windows 本机运行。', 400); return
        result = subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-StartTime',start],
                                cwd=str(ROOT), capture_output=True, text=True, timeout=90)
        SCHED_CACHE['data'] = None
        if result.returncode:
            self._error('SCHEDULE_FAILED', '定时任务注册失败', 500, [{'field': 'powershell', 'message': (result.stderr or result.stdout)[-1000:]}]); return
        self._ok({'output': result.stdout[-3000:], 'scheduler': scheduler_status()})

    def _source_check(self, data):
        issues = audit_sources(load_sources(str(source_file()))); results = []
        if data.get('check_urls'):
            for source in load_sources(str(source_file())):
                if source.enabled:
                    for label, url in url_targets(source):
                        ok, detail = check_url(url)
                        results.append({'source_id': source.source_id, 'field': label, 'ok': ok, 'detail': detail})
        self._ok({'issues': issues, 'url_checks': results})


def main():
    load_dotenv()
    host = '127.0.0.1'; port = int(os.getenv('OR_ADMIN_PORT', '8090'))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f'Opportunity Radar local admin: http://{host}:{port}')
    print('Security: loopback only. SMTP credentials remain in .env; never expose this server to a LAN or public network.')
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nStopping local admin server...')
    finally: server.server_close()

if __name__ == '__main__': main()
