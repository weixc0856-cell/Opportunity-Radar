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


def _mode(security, starttls):
    mode = (security or '').strip().lower()
    if mode not in ('', 'ssl', 'starttls', 'none'):
        raise ValueError("OR_SMTP_SECURITY must be 'ssl', 'starttls', or 'none'")
    use_ssl = mode == 'ssl'
    use_starttls = (mode == 'starttls') if mode else (starttls and mode != 'none')
    return use_ssl, use_starttls


def _send_one(host, port, username, password, sender, address, subject, body, html, use_ssl, use_starttls):
    m = EmailMessage(); m['Subject'] = subject; m['From'] = sender; m['To'] = address; m.set_content(body)
    if html: m.add_alternative(html, subtype='html')
    smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_cls(host, port, timeout=30) as s:
        s.ehlo()
        if use_starttls:
            s.starttls(); s.ehlo()
        if username: s.login(username, password)
        s.send_message(m, to_addrs=[address])


def send_email_detailed(host,port,username,password,sender,recipient,subject,body,starttls=True,html=None,security=None):
    """Send one copy per recipient and report each result separately.

    A failure for one address must not hide the fact that earlier addresses were accepted.
    SMTP acceptance only means the sending side submitted the message; it is not inbox delivery.
    """
    recipients = parse_recipients(recipient)
    if not all((host, sender)) or not recipients:
        raise ValueError('SMTP host, sender and at least one recipient are required')
    use_ssl, use_starttls = _mode(security, starttls)
    results = []
    for address in recipients:
        try:
            _send_one(host, port, username, password, sender, address, subject, body, html, use_ssl, use_starttls)
            results.append({'recipient': address, 'ok': True, 'error': ''})
        except Exception as e:
            results.append({'recipient': address, 'ok': False, 'error': f'{type(e).__name__}: {e}'[:500]})
    return results


def send_email(host,port,username,password,sender,recipient,subject,body,starttls=True,html=None,security=None):
    results = send_email_detailed(host, port, username, password, sender, recipient, subject, body, starttls, html, security)
    failed = [r for r in results if not r['ok']]
    if failed:
        raise RuntimeError('; '.join(f"{r['recipient']}: {r['error']}" for r in failed))
