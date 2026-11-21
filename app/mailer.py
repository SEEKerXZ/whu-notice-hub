"""邮件发送（SMTP over SSL）。配置全部来自环境变量。"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr


def is_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD"))


def send_email(subject: str, html_body: str, to: str | None = None) -> bool:
    """发送 HTML 邮件；未配置时抛 RuntimeError。"""
    if not is_configured():
        raise RuntimeError("SMTP 未配置：请设置 SMTP_HOST / SMTP_USER / SMTP_PASSWORD")

    host = os.getenv("SMTP_HOST", "smtp.example.com")
    port = int(os.getenv("SMTP_PORT", "465"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    recipient = to or os.getenv("MAIL_TO") or user

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("武大通知聚合", user))
    msg["To"] = recipient
    msg.set_content("请使用支持 HTML 的邮件客户端查看这条通知聚合。")
    msg.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=25, context=context) as server:
            server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=25) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(msg)
    return True
