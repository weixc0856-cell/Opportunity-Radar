from __future__ import annotations
import os, re
import tomllib
from dataclasses import dataclass
from pathlib import Path

def load_dotenv(path='.env'):
    p=Path(path)
    if not p.exists(): return
    for raw in p.read_text(encoding='utf-8').splitlines():
        line=raw.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k,v=line.split('=',1); k=k.strip(); v=v.strip().strip('"').strip("'")
        if k and k not in os.environ: os.environ[k]=v

def bval(k, default=True):
    return os.getenv(k, str(default)).lower().strip() in {'1','true','yes','on'}

def load_scoring(path='config/scoring.toml'):
    """Read weights and thresholds from TOML so the report obeys the same rules as the score."""
    p=Path(path)
    if not p.exists(): return {}
    with p.open('rb') as f: return tomllib.load(f)

@dataclass(frozen=True)
class Settings:
    freshrss_base_url:str; freshrss_username:str; freshrss_api_key:str
    llm_base_url:str; llm_model:str; llm_api_key:str; llm_timeout:int; llm_max_tokens:int
    smtp_host:str; smtp_port:int; smtp_username:str; smtp_password:str
    email_from:str; email_to:str; smtp_starttls:bool
    max_articles:int; request_timeout:int; db_path:str; log_path:str; report_dir:str
    smtp_security:str=''; email_on_empty:bool=False; alert_after_failures:int=3
    @classmethod
    def from_env(cls):
        load_dotenv()
        g=lambda k,d='':os.getenv(k,d).strip()
        port=int(g('OR_SMTP_PORT','587'))
        # OR_SMTP_SECURITY is the current name; OR_SMTP_TLS is accepted for older .env files.
        security=(g('OR_SMTP_SECURITY') or g('OR_SMTP_TLS') or '').lower()
        if security=='auto': security='ssl' if port in {465,994} else 'starttls'
        elif not security and port in {465,994}: security='ssl'
        # The local admin recipient list takes precedence over OR_EMAIL_TO when present.
        email_to=g('OR_EMAIL_TO')
        recipients_path=Path('config/recipients.json')
        if recipients_path.exists():
            try:
                import json
                saved=json.loads(recipients_path.read_text(encoding='utf-8'))
                addresses=saved.get('recipients',[]) if isinstance(saved,dict) else []
                if isinstance(addresses,list):
                    joined=','.join(str(x).strip() for x in addresses if str(x).strip())
                    if joined: email_to=joined
            except (OSError,ValueError,TypeError):
                pass
        return cls(freshrss_base_url=g('OR_FRESHRSS_BASE_URL','http://127.0.0.1:8088').rstrip('/'),freshrss_username=g('OR_FRESHRSS_USERNAME'),freshrss_api_key=g('OR_FRESHRSS_API_KEY'),
                   llm_base_url=g('OR_LLM_BASE_URL','http://127.0.0.1:8080/v1').rstrip('/'),llm_model=g('OR_LLM_MODEL'),llm_api_key=g('OR_LLM_API_KEY'),
                   llm_timeout=int(g('OR_LLM_TIMEOUT_SECONDS','90')),llm_max_tokens=int(g('OR_LLM_MAX_TOKENS','500')),
                   smtp_host=g('OR_SMTP_HOST'),smtp_port=port,smtp_username=g('OR_SMTP_USERNAME'),smtp_password=g('OR_SMTP_PASSWORD'),
                   email_from=g('OR_EMAIL_FROM'),email_to=email_to,smtp_starttls=bval('OR_SMTP_STARTTLS',True),smtp_security=security,
                   max_articles=max(1,int(g('OR_MAX_ARTICLES','10'))),request_timeout=int(g('OR_REQUEST_TIMEOUT_SECONDS','20')),
                   db_path=g('OR_DB_PATH','data/opportunity_radar.sqlite3'),log_path=g('OR_LOG_PATH','reports/opportunity-radar.log'),report_dir=g('OR_REPORT_DIR','reports'),
                   email_on_empty=bval('OR_EMAIL_ON_EMPTY',False),alert_after_failures=max(1,int(g('OR_ALERT_AFTER_FAILURES','3'))))
    def validate(self, mail=True):
        required={'OR_FRESHRSS_USERNAME':self.freshrss_username,'OR_FRESHRSS_API_KEY':self.freshrss_api_key,'OR_LLM_MODEL':self.llm_model}
        if mail: required.update({'OR_SMTP_HOST':self.smtp_host,'OR_EMAIL_FROM':self.email_from,'OR_EMAIL_TO':self.email_to})
        return [k for k,v in required.items() if not v or v.startswith('replace_') or 'example.com' in v]
    def validate_mail(self):
        """Return actionable mail-config problems without ever echoing the password."""
        from .email_sender import parse_recipients
        issues=[]
        for k,v in (('OR_SMTP_HOST',self.smtp_host),('OR_SMTP_USERNAME',self.smtp_username),('OR_SMTP_PASSWORD',self.smtp_password),
                    ('OR_EMAIL_FROM',self.email_from),('OR_EMAIL_TO',self.email_to)):
            if not v or v.startswith('replace_') or 'example.com' in v or 'your-' in v: issues.append(f'{k} is missing or still a placeholder')
        recipients=parse_recipients(self.email_to)
        if self.email_to and not recipients: issues.append('OR_EMAIL_TO has no valid addresses')
        valid=lambda addr: bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$',addr))
        if self.email_from and not valid(self.email_from): issues.append('OR_EMAIL_FROM is not a valid email address')
        for addr in recipients:
            if not valid(addr): issues.append(f'OR_EMAIL_TO contains an invalid address: {addr}')
        if not 1<=self.smtp_port<=65535: issues.append('OR_SMTP_PORT must be between 1 and 65535')
        if self.smtp_security not in {'','ssl','starttls','none'}: issues.append('OR_SMTP_SECURITY must be ssl, starttls or none')
        return issues
