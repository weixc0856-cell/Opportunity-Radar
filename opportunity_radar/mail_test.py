import argparse, sys
from datetime import datetime
from .config import Settings
from .email_sender import send_email

def main(argv=None):
    p=argparse.ArgumentParser(prog='opportunity_radar.mail_test',description='Send a test email using the configured SMTP settings')
    p.add_argument('--to',default='',help='override the configured recipient')
    args=p.parse_args(argv)
    s=Settings.from_env()
    issues=s.validate_mail()
    if issues:
        for i in issues: print(' - '+i,file=sys.stderr)
        print('Fix these in .env before sending a test email.',file=sys.stderr); return 2
    to=args.to or s.email_to
    stamp=datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')
    subject='Opportunity Radar SMTP 测试'
    body=(f'这是一封 SMTP 配置测试邮件。\n\n发送时间：{stamp}\n发件服务器：{s.smtp_host}:{s.smtp_port}\n'
          f'传输方式：{s.smtp_security or "auto"}\n\n收到即表示发件服务器、认证和收件地址可用；它不包含分析结果。')
    html=(f'<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;color:#1f2328;line-height:1.7;">'
          f'<h2 style="color:#d9730d;margin:0 0 8px;">SMTP 测试</h2>'
          f'<p>这是一封 SMTP 配置测试邮件。</p>'
          f'<p style="color:#6b7280;font-size:13px;">发送时间：{stamp}<br>发件服务器：{s.smtp_host}:{s.smtp_port}<br>'
          f'传输方式：{s.smtp_security or "auto"}</p>'
          f'<p style="color:#6b7280;font-size:12px;">收到即表示发件服务器、认证和收件地址可用；它不包含分析结果。</p></div>')
    try:
        send_email(s.smtp_host,s.smtp_port,s.smtp_username,s.smtp_password,s.email_from,to,subject,body,
                   s.smtp_starttls,html=html,security=s.smtp_security)
    except Exception as e:
        print(f'发送失败：{type(e).__name__}: {e}',file=sys.stderr); return 1
    print(f'测试邮件已提交给 {to}（{s.smtp_host}:{s.smtp_port}, {s.smtp_security or "auto"}）。')
    print('注意：SMTP 成功只代表发送端完成提交，不代表已送达收件箱或被阅读。')
    return 0

if __name__=='__main__': raise SystemExit(main())
