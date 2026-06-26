"""
Email notification layer for the Doomsday alert system.

Primary backend: Resend (https://resend.com) via its HTTP API — one POST, no SDK.
Fallback: log the email to the console (so the app runs with NO key set; you can
see exactly what *would* have been sent during local dev).

Env vars:
    RESEND_API_KEY     - required to actually send
    ALERT_FROM_EMAIL   - optional; defaults to Resend's no-domain sender
"""
import os
import logging
from typing import List, Dict, Any

import requests

logger = logging.getLogger("doomsday.notify")

_API = "https://api.resend.com/emails"
_TIMEOUT = 15
# Resend lets you send from this address with NO domain verification — perfect for demos.
_DEFAULT_FROM = "Doomsday Desk <onboarding@resend.dev>"


def is_configured() -> bool:
    return bool(os.getenv("RESEND_API_KEY"))


def _from() -> str:
    return os.getenv("ALERT_FROM_EMAIL") or _DEFAULT_FROM


def send_email(to: str, subject: str, html: str) -> Dict[str, Any]:
    """Send an HTML email. Never raises — returns a status dict."""
    key = os.getenv("RESEND_API_KEY")
    if not key:
        logger.warning(f"[EMAIL FALLBACK] No RESEND_API_KEY set. Would send to {to}: '{subject}'")
        return {"sent": False, "reason": "no_api_key", "to": to, "subject": subject}
    try:
        resp = requests.post(
            _API,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"from": _from(), "to": [to], "subject": subject, "html": html},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return {"sent": True, "id": resp.json().get("id"), "to": to}
    except Exception as e:
        logger.error(f"Resend send failed for {to}: {e}")
        return {"sent": False, "reason": str(e), "to": to}


# ===============================================================
# HTML TEMPLATES (dark cockpit aesthetic, email-client safe inline CSS)
# ===============================================================

_WRAP_OPEN = (
    '<div style="background:#0a0e14;color:#e6edf3;font-family:Arial,Helvetica,sans-serif;'
    'padding:28px;max-width:640px;margin:0 auto;border:1px solid #1c2430;border-radius:10px">'
)
_WRAP_CLOSE = (
    '<p style="color:#5b6677;font-size:11px;margin-top:24px;border-top:1px solid #1c2430;padding-top:14px">'
    'Doomsday Rapid Agent — autonomous risk watchtower. You are receiving this because you armed a watchlist. '
    'Open the cockpit for the full multi-agent tribunal and valuation waterfall.</p></div>'
)


def _header(title: str, accent: str) -> str:
    return (
        f'<div style="font-family:\'Courier New\',monospace;letter-spacing:2px;color:{accent};'
        f'font-size:18px;font-weight:bold">☣ DOOMSDAY DESK</div>'
        f'<h1 style="font-size:20px;margin:10px 0 18px;color:#fff">{title}</h1>'
    )


def _macro_line(world_state: Any) -> str:
    fear = getattr(world_state, "fear_level", "—")
    vix = getattr(world_state, "vix", "—")
    return (
        f'<p style="color:#8b97a7;font-size:13px;margin:0 0 16px">'
        f'Market regime: <b style="color:#e6edf3">{fear}</b> &nbsp;|&nbsp; VIX <b style="color:#e6edf3">{vix}</b></p>'
    )


def _row(item: Dict[str, Any], threshold: float) -> str:
    sev = item.get("severity", 0)
    breached = item.get("breached", sev >= threshold)
    color = "#ff4d4d" if breached else "#2dd4bf"
    flag = "BREACH" if breached else "OK"
    return (
        f'<tr>'
        f'<td style="padding:10px 12px;border-bottom:1px solid #1c2430;font-weight:bold">{item.get("ticker","")}</td>'
        f'<td style="padding:10px 12px;border-bottom:1px solid #1c2430;color:#8b97a7">{item.get("name","")}</td>'
        f'<td style="padding:10px 12px;border-bottom:1px solid #1c2430;color:{color};font-weight:bold">{sev:.1f}/10</td>'
        f'<td style="padding:10px 12px;border-bottom:1px solid #1c2430;color:{color}">{flag}</td>'
        f'</tr>'
    )


def _table(items: List[Dict[str, Any]], threshold: float) -> str:
    rows = "".join(_row(i, threshold) for i in items)
    return (
        '<table style="width:100%;border-collapse:collapse;font-size:14px;margin:8px 0">'
        '<tr style="color:#5b6677;font-size:11px;text-transform:uppercase;letter-spacing:1px">'
        '<td style="padding:6px 12px">Ticker</td><td style="padding:6px 12px">Asset</td>'
        '<td style="padding:6px 12px">Severity</td><td style="padding:6px 12px">Status</td></tr>'
        f'{rows}</table>'
    )


def build_confirmation_html(email: str, snapshot: List[Dict[str, Any]], world_state: Any, threshold: float) -> str:
    """Sent immediately on subscribe — the instant-gratification demo email."""
    n = len(snapshot)
    breaches = sum(1 for s in snapshot if s.get("breached"))
    sub = (
        f'Watchlist armed: <b style="color:#fff">{n}</b> asset(s), alert threshold '
        f'<b style="color:#fff">{threshold:.0f}/10</b>. '
        + (f'<b style="color:#ff4d4d">{breaches} already breaching.</b>' if breaches else
           'All quiet for now — the watchtower will email you the moment a risk crosses your threshold.')
    )
    return (
        _WRAP_OPEN
        + _header("Watchlist Armed ✅", "#2dd4bf")
        + _macro_line(world_state)
        + f'<p style="font-size:14px;color:#c4cdd9;margin:0 0 14px">{sub}</p>'
        + _table(snapshot, threshold)
        + _WRAP_CLOSE
    )


def build_alert_html(email: str, breached: List[Dict[str, Any]], world_state: Any, threshold: float = 7.0) -> str:
    """Sent by the cron when one or more tickers breach the threshold."""
    n = len(breached)
    lead = (
        f'<p style="font-size:14px;color:#c4cdd9;margin:0 0 14px">'
        f'The autonomous watchtower detected <b style="color:#ff4d4d">{n} critical risk signal(s)</b> '
        f'on your watchlist. Top risk per asset below — open the cockpit to run the full Fracture Swarm '
        f'tribunal and stressed-valuation waterfall.</p>'
    )
    detail = "".join(
        f'<p style="font-size:13px;color:#8b97a7;margin:6px 0">'
        f'<b style="color:#e6edf3">{b.get("ticker","")}</b> — {b.get("top_risk","")}</p>'
        for b in breached
    )
    return (
        _WRAP_OPEN
        + _header("⚠ Critical Risk Alert", "#ff4d4d")
        + _macro_line(world_state)
        + lead
        + _table(breached, threshold)
        + detail
        + _WRAP_CLOSE
    )
