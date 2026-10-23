import logging, os, re
from pathlib import Path

_SECRET=re.compile(r'(?i)((?:api[_-]?key|password|authorization|token|secret)\s*[=:]\s*)[^\s,;]+')
_BEARER=re.compile(r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+')
_EMAIL=re.compile(r'([A-Za-z0-9._%+-]{2})[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})')

def redact(text):
    """Mask credentials and email addresses before writing logs or returning them to the UI.

    Non-string values pass through untouched. Coercing every log argument to text broke
    %d formatting, and `str(text or '')` turned every numeric zero into an empty string,
    so a success line such as "errors=0" could not be formatted and never reached the log
    file at all.
    """
    if text is None: return ''
    if not isinstance(text,str): return text
    s=text
    s=_BEARER.sub(r'\1<redacted>',s)
    s=_SECRET.sub(r'\1<redacted>',s)
    s=_EMAIL.sub(r'\1***@\2',s)
    return s

def rotate_log(path,max_bytes=1_000_000,backups=3):
    """Keep a small bounded history instead of one unbounded log file."""
    p=Path(path)
    try:
        if not p.exists() or p.stat().st_size<max_bytes: return False
        for i in range(backups-1,0,-1):
            src=Path(f'{p}.{i}')
            if src.exists(): os.replace(src,Path(f'{p}.{i+1}'))
        os.replace(p,Path(f'{p}.1'))
        return True
    except OSError:
        return False

class RedactFilter(logging.Filter):
    def filter(self,record):
        try:
            record.msg=redact(record.msg)
            if isinstance(record.args,dict):
                record.args={k:redact(v) for k,v in record.args.items()}
            elif record.args:
                record.args=tuple(redact(a) for a in record.args)
        except Exception:
            pass
        return True
