import smtplib
from email.message import EmailMessage
def send_email(host,port,username,password,sender,recipient,subject,body,starttls=True,html=None):
    if not all((host,sender,recipient)): raise ValueError('SMTP host, sender and recipient are required')
    m=EmailMessage(); m['Subject']=subject; m['From']=sender; m['To']=recipient; m.set_content(body)
    if html: m.add_alternative(html,subtype='html')
    with smtplib.SMTP(host,port,timeout=30) as s:
        s.ehlo()
        if starttls: s.starttls(); s.ehlo()
        if username: s.login(username,password)
        s.send_message(m)
