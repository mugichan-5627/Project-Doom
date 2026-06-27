"""
Subscription store for the Doomsday autonomous alert system.

Primary backend: Upstash Redis via its HTTP REST API (works cleanly from Python —
just POST a command array to the base URL with a Bearer token).
Fallback: a local JSON file in /tmp, so the app runs end-to-end with NO keys set
(local dev / first deploy before the Upstash store is attached).

Env vars (either naming set works — Vercel Marketplace injects the KV_* names,
the Upstash console uses the UPSTASH_* names):
    KV_REST_API_URL   / UPSTASH_REDIS_REST_URL
    KV_REST_API_TOKEN / UPSTASH_REDIS_REST_TOKEN
"""
import os
import json
import logging
import tempfile
from datetime import datetime
from typing import List, Dict, Any, Optional

import requests

logger = logging.getLogger("doomsday.store")

_KEY = "doom:subscriptions"
# OS temp dir: %TEMP% on Windows (local dev), /tmp on Vercel (the only writable path).
_LOCAL_FALLBACK = os.path.join(tempfile.gettempdir(), "doom_subscriptions.json")
_TIMEOUT = 10


def _url() -> Optional[str]:
    direct = os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL")
    if direct:
        return direct
    # Fallback: tolerate any prefix the Vercel/Upstash integration applied
    # (e.g. STORAGE_KV_REST_API_URL) so the store works regardless of naming choice.
    for k, v in os.environ.items():
        if k.endswith("REST_API_URL") and v:
            return v
    return None


def _token() -> Optional[str]:
    direct = os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if direct:
        return direct
    # Prefer the read-write token; never pick the READ_ONLY one.
    for k, v in os.environ.items():
        if k.endswith("REST_API_TOKEN") and "READ_ONLY" not in k and v:
            return v
    return None


def is_configured() -> bool:
    """True when a real Upstash backend is wired (vs. local-file fallback)."""
    return bool(_url() and _token())


def _command(command: List[Any]) -> Any:
    """Run a single Redis command via the Upstash REST API. Returns the `result`."""
    resp = requests.post(
        _url(),
        headers={"Authorization": f"Bearer {_token()}"},
        json=command,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("result")


def get_subscriptions() -> List[Dict[str, Any]]:
    """Return the full list of subscription records (never raises — degrades to [])."""
    if is_configured():
        try:
            raw = _command(["GET", _KEY])
            return json.loads(raw) if raw else []
        except Exception as e:
            logger.warning(f"Upstash read failed, using local fallback: {e}")
    try:
        if os.path.exists(_LOCAL_FALLBACK):
            with open(_LOCAL_FALLBACK, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Local subscription read failed: {e}")
    return []


def _save_all(subs: List[Dict[str, Any]]) -> None:
    payload = json.dumps(subs)
    if is_configured():
        try:
            _command(["SET", _KEY, payload])
            return
        except Exception as e:
            logger.warning(f"Upstash write failed, using local fallback: {e}")
    try:
        with open(_LOCAL_FALLBACK, "w", encoding="utf-8") as f:
            f.write(payload)
    except Exception as e:
        logger.error(f"Local subscription write failed: {e}")


def add_subscription(email: str, tickers: List[str], threshold: float) -> Dict[str, Any]:
    """Upsert a subscription keyed by email. Preserves prior last_alert state."""
    subs = get_subscriptions()
    email_l = email.strip().lower()
    record = next((s for s in subs if s.get("email", "").lower() == email_l), None)
    if record is None:
        record = {"email": email.strip(), "created": datetime.utcnow().isoformat() + "Z", "last_alert": {}}
        subs.append(record)
    record["tickers"] = tickers
    record["threshold"] = float(threshold)
    record.setdefault("last_alert", {})
    record["updated"] = datetime.utcnow().isoformat() + "Z"
    _save_all(subs)
    return record


def update_last_alert(email: str, ticker: str, severity: float) -> None:
    """Record the severity last alerted for (email, ticker) so the cron won't re-spam."""
    subs = get_subscriptions()
    email_l = email.strip().lower()
    for s in subs:
        if s.get("email", "").lower() == email_l:
            s.setdefault("last_alert", {})[ticker] = float(severity)
            s["last_alert_at"] = datetime.utcnow().isoformat() + "Z"
            _save_all(subs)
            return
