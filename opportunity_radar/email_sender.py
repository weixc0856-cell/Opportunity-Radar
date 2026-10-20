import smtplib
from email.message import EmailMessage
from email.utils import getaddresses

def parse_recipients(value):
    """Accept one or more addresses separated by commas or semicolons."""
    if isinstance(value, (list, tuple, set)):
        raw = [str(x) for x in value]
    else:
        raw = [str(value).replace(';', ',')]
    recipients = [addr.strip() for _, addr in getaddresses(raw) if addr.strip()]
    # Keep order while removing duplicates case-insensitively.
    result, seen = [], set()
    for addr in recipients:
        key = addr.casefold()
        if key not in seen:
            seen.add(key); result.append(addr)
    return result

def send_email(host,port,username,password,sender,recipient,subject,body,starttls=True,html=None,security=None):
    recipients = parse_recipients(recipient)
    if not all((host,sender)) or not recipients:
        raise ValueError('SMTP host, sender and at least one recipient are required')
    mode = (security or '').strip().lower()
    if mode not in ('', 'ssl', 'starttls', 'none'):
        raise ValueError("OR_SMTP_SECURITY must be 'ssl', 'starttls', or 'none'")
    # Legacy configuration remains supported: STARTTLS is used when no explicit mode is set.
    use_ssl = mode == 'ssl'
    use_starttls = (mode == 'starttls') if mode else (starttls and mode != 'none')
    # Send one copy per recipient so recipients do not see each other's addresses.
    for address in recipients:
        m=EmailMessage(); m['Subject']=subject; m['From']=sender; m['To']=address; m.set_content(body)
        if html: m.add_alternative(html,subtype='html')
        smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with smtp_cls(host,port,timeout=30) as s:
            s.ehlo()
            if use_starttls:
                s.starttls(); s.ehlo()
            if username: s.login(username,password)
            s.send_message(m, to_addrs=[address])
