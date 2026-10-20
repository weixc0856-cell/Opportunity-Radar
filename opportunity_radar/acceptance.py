"""Real-environment smoke test. Prints no secrets; exits non-zero on critical failures."""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path
from urllib.request import Request, urlopen

from .config import Settings
from .email_sender import send_email_detailed
from .freshrss_client import FreshRSSClient
from .source_audit import audit_sources
from .source_policy import load_sources
from .store import Store


def summarize(results):
    passed = sum(1 for r in results if r['ok'])
    failed = [r for r in results if not r['ok']]
    critical = [r for r in failed if r.get('critical', True)]
    return {'passed': passed, 'failed': failed, 'critical_failed': critical}


def run_check(name, fn, critical=True):
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f'{type(e).__name__}: {str(e)[:200]}'
    return {'name': name, 'ok': bool(ok), 'detail': str(detail)[:400], 'critical': critical}


def scheduler_check():
    if os.name != 'nt': return False, 'not running on Windows'
    command = ("$t=Get-ScheduledTask -TaskName 'OpportunityRadarDaily' -ErrorAction Stop;"
               "$i=Get-ScheduledTaskInfo -TaskName 'OpportunityRadarDaily';"
               "[pscustomobject]@{state=[string]$t.State;last_result=[int]$i.LastTaskResult;next_run=[string]$i.NextRunTime} | ConvertTo-Json -Compress")
    out = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command], capture_output=True, text=True, timeout=15)
    raw = (out.stdout or '').strip()
    if out.returncode or not raw: return False, (out.stderr or 'scheduled task not found')[-200:]
    data = json.loads(raw)
    return data.get('state') == 'Ready', f"{data.get('state')} · last_result={data.get('last_result')} · next={data.get('next_run')}"


def main(argv=None):
    p = argparse.ArgumentParser(prog='opportunity_radar.acceptance', description='Real-environment acceptance checks')
    p.add_argument('--send-mail', action='store_true', help='send a test email to every configured recipient')
    p.add_argument('--skip-scheduler', action='store_true', help='skip the Windows scheduled-task check')
    p.add_argument('--json', action='store_true', help='machine-readable output')
    args = p.parse_args(argv)

    s = Settings.from_env()
    results = []

    def config_check():
        missing = s.validate(mail=False)
        return (not missing), ('ok' if not missing else 'missing: ' + ', '.join(missing))
    results.append(run_check('config', config_check))

    def sources_check():
        issues = audit_sources(load_sources())
        errors = [x for x in issues if x['severity'] == 'error']
        enabled = sum(1 for x in load_sources() if x.enabled)
        return (not errors and enabled > 0), f'{enabled} enabled; {len(errors)} audit error(s)'
    results.append(run_check('sources', sources_check))

    def freshrss_check():
        feeds = FreshRSSClient(s.freshrss_base_url, s.freshrss_username, s.freshrss_api_key, s.request_timeout).list_feeds()
        return bool(feeds), f'{len(feeds)} feed(s)'
    results.append(run_check('freshrss', freshrss_check))

    def model_check():
        url = s.llm_base_url.removesuffix('/v1') + '/health'
        req = Request(url, headers={'Authorization': 'Bearer ' + s.llm_api_key}, method='GET')
        with urlopen(req, timeout=3) as r:
            return 200 <= r.status < 300, f'HTTP {r.status}'
    results.append(run_check('model', model_check))

    def db_check():
        store = Store(s.db_path); latest = store.latest_run()
        return True, f'ok; latest run {latest["run_id"] if latest else "none"}'
    results.append(run_check('sqlite', db_check))

    def report_check():
        path = Path(s.report_dir) / 'latest-digest.html'
        return path.exists(), str(path) if path.exists() else 'latest-digest.html not found'
    results.append(run_check('report', report_check, critical=False))

    def mail_config_check():
        issues = s.validate_mail()
        return (not issues), 'ok' if not issues else '; '.join(issues)
    results.append(run_check('mail_config', mail_config_check))

    if args.send_mail:
        def send_check():
            results_ = send_email_detailed(s.smtp_host, s.smtp_port, s.smtp_username, s.smtp_password, s.email_from, s.email_to,
                                           '[Opportunity Radar] 验收测试', '这是一封来自 acceptance 命令的测试邮件。', s.smtp_starttls, security=s.smtp_security)
            failed = [r for r in results_ if not r['ok']]
            detail = ', '.join(f"{r['recipient']}: {'ok' if r['ok'] else r['error'][:80]}" for r in results_)
            return (not failed), detail
        results.append(run_check('mail_send', send_check))

    if not args.skip_scheduler:
        results.append(run_check('scheduler', scheduler_check, critical=False))

    summary = summarize(results)
    if args.json:
        print(json.dumps({'results': results, 'summary': {k: (len(v) if isinstance(v, list) else v) for k, v in summary.items()}}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(f"[{'PASS' if r['ok'] else 'FAIL'}] {r['name']:<14} {r['detail']}")
        print(f"\n{summary['passed']} passed, {len(summary['failed'])} failed, {len(summary['critical_failed'])} critical.")
        if summary['critical_failed']:
            print('Fix the critical failures before relying on the daily run.', file=sys.stderr)
    return 1 if summary['critical_failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
