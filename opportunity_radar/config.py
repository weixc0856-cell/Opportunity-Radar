from __future__ import annotations
import os
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
    @classmethod
    def from_env(cls):
        load_dotenv()
        g=lambda k,d='':os.getenv(k,d).strip()
        return cls(g('OR_FRESHRSS_BASE_URL','http://127.0.0.1:8088').rstrip('/'),g('OR_FRESHRSS_USERNAME'),g('OR_FRESHRSS_API_KEY'),g('OR_LLM_BASE_URL','http://127.0.0.1:8080/v1').rstrip('/'),g('OR_LLM_MODEL'),g('OR_LLM_API_KEY'),int(g('OR_LLM_TIMEOUT_SECONDS','90')),int(g('OR_LLM_MAX_TOKENS','500')),g('OR_SMTP_HOST'),int(g('OR_SMTP_PORT','587')),g('OR_SMTP_USERNAME'),g('OR_SMTP_PASSWORD'),g('OR_EMAIL_FROM'),g('OR_EMAIL_TO'),bval('OR_SMTP_STARTTLS',True),max(1,int(g('OR_MAX_ARTICLES','10'))),int(g('OR_REQUEST_TIMEOUT_SECONDS','20')),g('OR_DB_PATH','data/opportunity_radar.sqlite3'),g('OR_LOG_PATH','reports/opportunity-radar.log'),g('OR_REPORT_DIR','reports'))
    def validate(self, mail=True):
        required={'OR_FRESHRSS_USERNAME':self.freshrss_username,'OR_FRESHRSS_API_KEY':self.freshrss_api_key,'OR_LLM_MODEL':self.llm_model}
        if mail: required.update({'OR_SMTP_HOST':self.smtp_host,'OR_EMAIL_FROM':self.email_from,'OR_EMAIL_TO':self.email_to})
        return [k for k,v in required.items() if not v or v.startswith('replace_') or 'example.com' in v]
