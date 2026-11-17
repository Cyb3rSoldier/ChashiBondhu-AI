"""Sending reset emails (SMTP) and SMS codes.

.env settings
  CB_MAIL_PROVIDER = smtp | console | (empty = off)
  CB_SMTP_HOST, CB_SMTP_PORT (587), CB_SMTP_USER, CB_SMTP_PASSWORD, CB_MAIL_FROM
  CB_PUBLIC_URL   = site address used in links, e.g. http://127.0.0.1:8000
  CB_SMS_PROVIDER = console | (empty = off).  No paid SMS gateway is connected yet.
  CB_ENV          = production  -> "console" senders are refused (they print secrets to the terminal).
Errors are logged WITHOUT the token, code, email or phone.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from chashibondhu.web.identity import setting

log = logging.getLogger("chashibondhu.notify")


def _console_allowed() -> bool:
    return setting("CB_ENV").lower() != "production"


def mail_enabled() -> bool:
    p = setting("CB_MAIL_PROVIDER").lower()
    if p == "smtp":
        return bool(setting("CB_SMTP_HOST") and setting("CB_MAIL_FROM") and setting("CB_PUBLIC_URL"))
    return p == "console" and _console_allowed()


def sms_enabled() -> bool:
    return setting("CB_SMS_PROVIDER").lower() == "console" and _console_allowed()


def public_url() -> str:
    return (setting("CB_PUBLIC_URL") or "http://127.0.0.1:8000").rstrip("/")


def send_reset_email(to: str, name: str, token: str, minutes: int) -> bool:
    link = f"{public_url()}/reset/{token}"
    msg = EmailMessage()
    msg["Subject"] = "ChashiBondhu password reset / পাসওয়ার্ড রিসেট"
    msg["From"] = setting("CB_MAIL_FROM")
    msg["To"] = to
    msg.set_content(
        f"Hello {name},\n\nSomeone asked to reset your ChashiBondhu password.\n"
        f"Open this link within {minutes} minutes (it works only once):\n{link}\n\n"
        "If it was not you, ignore this email. Your password stays the same.\n\n"
        f"আপনার চাষীবন্ধু পাসওয়ার্ড বদলাতে {minutes} মিনিটের মধ্যে উপরের লিংক খুলুন। "
        "আপনি না চাইলে এই ইমেইল উপেক্ষা করুন।\n")
    provider = setting("CB_MAIL_PROVIDER").lower()
    try:
        if provider == "console" and _console_allowed():
            print(f"[DEV MAIL] to={to} link={link}", flush=True)   # local testing only
            return True
        if provider != "smtp":
            return False
        port = int(setting("CB_SMTP_PORT", "587") or 587)
        ctx = ssl.create_default_context()
        if port == 465:
            server = smtplib.SMTP_SSL(setting("CB_SMTP_HOST"), port, context=ctx, timeout=20)
        else:
            server = smtplib.SMTP(setting("CB_SMTP_HOST"), port, timeout=20)
            server.starttls(context=ctx)
        with server:
            if setting("CB_SMTP_USER"):
                server.login(setting("CB_SMTP_USER"), setting("CB_SMTP_PASSWORD"))
            server.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001 - never crash the request; never log the link
        log.warning("reset email failed: %s", type(e).__name__)
        return False


def send_sms(phone: str, text: str) -> bool:
    if setting("CB_SMS_PROVIDER").lower() == "console" and _console_allowed():
        print(f"[DEV SMS] to={phone} text={text}", flush=True)       # local testing only
        return True
    return False
