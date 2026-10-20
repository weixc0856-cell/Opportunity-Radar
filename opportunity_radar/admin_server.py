"""Local-only admin UI for Opportunity Radar. Binds exclusively to loopback."""
from __future__ import annotations
import csv, json, os, re, subprocess, sys, threading, time
from datetime import datetime
from email.utils import parseaddr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .config import Settings, load_dotenv
from .email_sender import send_email, parse_recipients
from .freshrss_client import FreshRSSClient
from .source_policy import load_sources
from .source_audit import audit_sources, check_url

ROOT = Path.cwd().resolve()
UI_FILE = ROOT / 'admin' / 'index.html'
RECIPIENT_FILE = ROOT / 'config' / 'recipients.json'
REPORT_DIR = ROOT / 'reports'
SOURCE_FIELDS = ['source_id','name','homepage','feed_url','access_method','permission_status','reviewed_at','review_notes','max_requests_per_day','enabled','freshrss_feed_id','source_type','provenance_class','canonical_domain','terms_url','last_verified_at','feed_provider','feed_provider_terms_url','topic','quality_tier','expected_signal']
RUN_LOCK = threading.Lock()
RUN_PROCESS: subprocess.Popen | None = None
RUN_STARTED = ''


def source_file():
    """Edit the active local registry when OR_SOURCES_PATH is set; the repo candidate file is the default."""
    return Path(os.environ.get('OR_SOURCES_PATH') or ROOT / 'config' / 'sources.csv')


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
    s = Settings.from_env()
    return parse_recipients(s.email_to)


def valid_email(address):
    _, parsed = parseaddr(address)
    return bool(parsed and parsed == address and re.fullmatch(r"[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+", address))


def source_validation(rows):
    # Validate a temporary registry through the same rules used by the CLI.
    temp = source_file().with_name('.sources-admin-validation.csv')
    try:
        with temp.open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=SOURCE_FIELDS, extrasaction='ignore'); w.writeheader()
            for row in rows: w.writerow({k: str(row.get(k, '') or '').strip() for k in SOURCE_FIELDS})
        issues = audit_sources(load_sources(str(temp)))
        enabled_errors = [x for x in issues if x['severity'] == 'error']
        return enabled_errors
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


class Handler(BaseHTTPRequestHandler):
    server_version = 'OpportunityRadarLocalAdmin/1.0'
    def log_message(self, fmt, *args):
        # Avoid writing secrets/query strings to the console.
        print('[admin] ' + (fmt % args))

    def _json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(raw)

    def _text(self, data, content_type='text/plain; charset=utf-8', status=200):
        raw = data.encode('utf-8'); self.send_response(status); self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(raw)

    def _body(self):
        length = int(self.headers.get('Content-Length','0'))
        if length < 0 or length > 1_000_000: raise ValueError('Request body too large')
        return json.loads(self.rfile.read(length).decode('utf-8')) if length else {}

    def _check_local(self):
        host = self.headers.get('Host','').split(':')[0].strip('[]').lower()
        if host not in {'127.0.0.1','localhost','::1'}: self._json({'error':'Only local browser access is allowed'},403); return False
        origin = self.headers.get('Origin')
        if origin:
            parsed = urlparse(origin)
            if parsed.hostname not in {'127.0.0.1','localhost','::1'}:
                self._json({'error':'Cross-origin request blocked'},403); return False
        return True

    def do_GET(self):
        path = urlparse(self.path).path
        if path in {'/','/admin'}:
            try: self._text(UI_FILE.read_text(encoding='utf-8'), 'text/html; charset=utf-8')
            except OSError: self._text('Admin UI not found. Start from the project root.', status=500)
        elif path == '/api/sources': self._json({'sources':read_sources(),'fields':SOURCE_FIELDS})
        elif path == '/api/recipients': self._json({'recipients':read_recipients()})
        elif path == '/api/freshrss-feeds':
            s = Settings.from_env()
            missing = [k for k,v in {'OR_FRESHRSS_USERNAME':s.freshrss_username,'OR_FRESHRSS_API_KEY':s.freshrss_api_key}.items() if not v or v.startswith('replace_')]
            if missing: self._json({'error':'缺少 FreshRSS 配置：'+', '.join(missing)},400)
            else:
                try: self._json({'feeds':FreshRSSClient(s.freshrss_base_url,s.freshrss_username,s.freshrss_api_key,s.request_timeout).list_feeds()})
                except Exception as e: self._json({'error':f'{type(e).__name__}: {e}'},502)
        elif path == '/api/audit': self._json({'issues':audit_sources(load_sources(str(source_file())))})
        elif path == '/api/status':
            global RUN_PROCESS
            running = bool(RUN_PROCESS and RUN_PROCESS.poll() is None)
            report = ROOT / 'reports' / 'latest-digest.html'
            s = Settings.from_env()
            self._json({'model':local_model_health(),'source_count':len(read_sources()),'enabled_sources':sum(str(x.get('enabled','')).lower()=='true' for x in read_sources()),'recipient_count':len(read_recipients()),'report_exists':report.exists(),'report_mtime':datetime.fromtimestamp(report.stat().st_mtime).isoformat(timespec='seconds') if report.exists() else None,'run':{'running':running,'pid':RUN_PROCESS.pid if running else None,'started_at':RUN_STARTED if running else None,'return_code':RUN_PROCESS.returncode if RUN_PROCESS and not running else None},'smtp_host':s.smtp_host,'smtp_port':s.smtp_port,'email_from':s.email_from,'smtp_security':s.smtp_security or ('starttls' if s.smtp_starttls else 'none'),'log_tail':tail(s.log_path,30)})
        elif path == '/api/logs': self._json({'application':tail('reports/opportunity-radar.log',200),'admin':tail('reports/admin-run.log',200),'scheduler':tail('reports/scheduler-run.log',100)})
        elif path == '/report':
            report = ROOT / 'reports' / 'latest-digest.html'
            if report.exists(): self._text(report.read_text(encoding='utf-8'), 'text/html; charset=utf-8')
            else: self._text('<h2>尚无真实日报</h2><p>先运行一次日报任务。</p>', 'text/html; charset=utf-8', 404)
        else: self._json({'error':'Not found'},404)

    def do_POST(self):
        if not self._check_local(): return
        path = urlparse(self.path).path
        try: data = self._body()
        except Exception as e: self._json({'error':str(e)},400); return
        if path == '/api/sources/save':
            rows = data.get('sources')
            if not isinstance(rows,list): self._json({'error':'sources must be a list'},400); return
            seen=set()
            for row in rows:
                sid=str(row.get('source_id','')).strip()
                if not sid or sid in seen: self._json({'error':f'Missing or duplicate source_id: {sid}'},400); return
                seen.add(sid)
                row['enabled'] = 'true' if str(row.get('enabled','')).lower() in {'true','1','yes','on'} else 'false'
                row['permission_status'] = str(row.get('permission_status','review_required')).strip().lower()
                if row['enabled']=='true' and row['permission_status']!='approved': self._json({'error':f'{sid}: enable requires permission_status=approved'},400); return
                if row['enabled']=='true' and not str(row.get('freshrss_feed_id','')).strip(): self._json({'error':f'{sid}: enabled source needs FreshRSS Feed ID'},400); return
            errors=source_validation(rows)
            if errors:
                self._json({'error':'启用来源未通过审计；请修正后再保存。','issues':errors},400); return
            write_sources(rows); self._json({'ok':True,'count':len(rows)}); return
        if path == '/api/recipients/save':
            addresses=data.get('recipients',[])
            if not isinstance(addresses,list): self._json({'error':'recipients must be a list'},400); return
            if not addresses: self._json({'error':'至少保留一个收件邮箱，避免日报配置被清空。'},400); return
            clean=[]; seen=set()
            for item in addresses:
                address=str(item).strip()
                if not valid_email(address): self._json({'error':f'邮箱地址格式不正确：{address}'},400); return
                if address.casefold() not in seen: seen.add(address.casefold()); clean.append(address)
            RECIPIENT_FILE.parent.mkdir(parents=True,exist_ok=True)
            tmp=RECIPIENT_FILE.with_suffix('.json.tmp'); tmp.write_text(json.dumps({'recipients':clean,'updated_at':datetime.now().astimezone().isoformat(timespec='seconds')},ensure_ascii=False,indent=2),encoding='utf-8'); os.replace(tmp,RECIPIENT_FILE)
            self._json({'ok':True,'recipients':clean}); return
        if path == '/api/email/test':
            s=Settings.from_env(); recipients=read_recipients()
            missing=s.validate(mail=True)
            if missing: self._json({'error':'缺少配置：'+', '.join(missing)},400); return
            if not recipients: self._json({'error':'请先添加至少一个收件邮箱并保存。'},400); return
            try:
                send_email(s.smtp_host,s.smtp_port,s.smtp_username,s.smtp_password,s.email_from,recipients,'[Opportunity Radar] 本地 SMTP 测试','这是一封由本机 Opportunity Radar 管理页面发送的测试邮件。\n如果你收到这封邮件，说明 SMTP 提交流程正常。',s.smtp_starttls,security=s.smtp_security)
                self._json({'ok':True,'count':len(recipients),'message':'SMTP 已提交；请检查收件箱和垃圾邮件。'})
            except Exception as e: self._json({'error':f'{type(e).__name__}: {e}'},502)
            return
        if path == '/api/run':
            global RUN_PROCESS, RUN_STARTED
            with RUN_LOCK:
                if RUN_PROCESS and RUN_PROCESS.poll() is None: self._json({'error':'已有日报任务正在运行','pid':RUN_PROCESS.pid},409); return
                REPORT_DIR.mkdir(parents=True,exist_ok=True)
                log_path=REPORT_DIR/'admin-run.log'
                log_file=log_path.open('a',encoding='utf-8')
                log_file.write(f"\n\n=== Admin run started {datetime.now().astimezone().isoformat(timespec='seconds')} ===\n"); log_file.flush()
                try:
                    if os.name == 'nt':
                        # Use the same end-to-end Windows entry point as the scheduled task:
                        # start Docker Compose, ensure local llama-server is healthy, then run CLI.
                        command = ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'deploy'/'windows'/'run-digest.ps1')]
                    else:
                        command = [sys.executable,'-m','opportunity_radar.cli']
                    RUN_PROCESS=subprocess.Popen(command,cwd=str(ROOT),stdout=log_file,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    RUN_STARTED=datetime.now().astimezone().isoformat(timespec='seconds')
                    self._json({'ok':True,'pid':RUN_PROCESS.pid,'message':'日报已启动；Windows 下会先尝试启动 Docker 与本地模型。可在运行记录查看状态。'})
                except Exception as e: log_file.close(); self._json({'error':str(e)},500)
            return
        if path == '/api/schedule':
            start=str(data.get('start_time','08:00'))
            if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',start): self._json({'error':'时间格式必须为 HH:MM'},400); return
            script=ROOT/'deploy'/'windows'/'install-task.ps1'
            if os.name!='nt': self._json({'error':'定时任务注册需要在 Windows 本机运行；当前不是 Windows。','command':f'.\\deploy\\windows\\install-task.ps1 -StartTime "{start}"'},400); return
            try:
                result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-StartTime',start],cwd=str(ROOT),capture_output=True,text=True,timeout=90)
                if result.returncode: self._json({'error':(result.stderr or result.stdout)[-3000:]},500)
                else: self._json({'ok':True,'output':result.stdout[-3000:]})
            except Exception as e: self._json({'error':str(e)},500)
            return
        if path == '/api/source-check':
            issues=audit_sources(load_sources(str(source_file()))); results=[]
            if data.get('check_urls'):
                for source in load_sources(str(source_file())):
                    if source.enabled:
                        for label,url in [('homepage',source.homepage),('feed',source.feed_url),('terms',source.terms_url)]:
                            ok,detail=check_url(url); results.append({'source_id':source.source_id,'field':label,'ok':ok,'detail':detail})
            self._json({'issues':issues,'url_checks':results}); return
        self._json({'error':'Not found'},404)


def main():
    load_dotenv()
    host='127.0.0.1'; port=int(os.getenv('OR_ADMIN_PORT','8090'))
    server=ThreadingHTTPServer((host,port),Handler)
    print(f'Opportunity Radar local admin: http://{host}:{port}')
    print('Security: loopback only. SMTP credentials remain in .env; never expose this server to a LAN or public network.')
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nStopping local admin server...')
    finally: server.server_close()

if __name__=='__main__': main()
