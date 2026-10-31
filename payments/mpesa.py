"""Thin client for Safaricom Daraja: OAuth token, STK push (Lipa Na M-Pesa Online) and STK query."""
import base64
import logging
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

BASES = {
    "sandbox": "https://sandbox.safaricom.co.ke",
    "production": "https://api.safaricom.co.ke",
}
TIMEOUT = 20


class MpesaError(Exception):
    """Raised for any failure talking to Daraja. The message is safe to show staff."""


def cfg():
    return settings.MPESA


def is_simulated():
    return bool(cfg()["SIMULATE"])


def base_url():
    return BASES.get(cfg()["ENV"], BASES["sandbox"])


def normalize_phone(raw):
    """Accept 07xx, 01xx, 7xx, +254... and return 2547XXXXXXXX / 2541XXXXXXXX. Raises ValueError."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("254") and len(digits) == 12:
        pass
    elif digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "17":
        digits = "254" + digits
    if not re.fullmatch(r"254[17]\d{8}", digits):
        raise ValueError("Invalid phone number")
    return digits


def _timestamp():
    return datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y%m%d%H%M%S")


def _password(timestamp):
    raw = f"{cfg()['SHORTCODE']}{cfg()['PASSKEY']}{timestamp}"
    return base64.b64encode(raw.encode()).decode()


def callback_url():
    base = cfg()["CALLBACK_BASE_URL"]
    if not base.startswith("https://"):
        raise MpesaError("MPESA_CALLBACK_BASE_URL must be a public https:// address.")
    return f"{base}/payments/callback/{cfg()['CALLBACK_SECRET']}/"


def get_access_token():
    cached = cache.get("mpesa_access_token")
    if cached:
        return cached
    if not (cfg()["CONSUMER_KEY"] and cfg()["CONSUMER_SECRET"]):
        raise MpesaError("M-Pesa is not configured (missing consumer key/secret).")
    try:
        resp = requests.get(
            f"{base_url()}/oauth/v1/generate",
            params={"grant_type": "client_credentials"},
            auth=(cfg()["CONSUMER_KEY"], cfg()["CONSUMER_SECRET"]),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        logger.error("Daraja token request failed: %s", exc)
        raise MpesaError("Could not reach M-Pesa. Try again or take cash.")
    cache.set("mpesa_access_token", token, max(int(data.get("expires_in", 3599)) - 120, 60))
    return token


def _post(path, payload):
    token = get_access_token()
    try:
        resp = requests.post(
            f"{base_url()}{path}", json=payload, timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {token}"},
        )
    except requests.RequestException as exc:
        logger.error("Daraja request %s failed: %s", path, exc)
        raise MpesaError("Could not reach M-Pesa. Try again or take cash.")
    if resp.status_code == 401:
        cache.delete("mpesa_access_token")
    try:
        return resp.json()
    except ValueError:
        logger.error("Daraja %s returned non-JSON (%s): %s", path, resp.status_code, resp.text[:200])
        raise MpesaError("M-Pesa returned an unexpected response.")


def stk_push(phone, amount, reference, description="Purchase"):
    """Ask Safaricom to prompt `phone` for `amount` (whole KES). Returns the Daraja response dict."""
    if is_simulated():
        return {
            "MerchantRequestID": f"SIM-{uuid.uuid4().hex[:10]}",
            "CheckoutRequestID": f"ws_CO_SIM_{uuid.uuid4().hex[:16]}",
            "ResponseCode": "0",
        }

    timestamp = _timestamp()
    payload = {
        "BusinessShortCode": cfg()["SHORTCODE"],
        "Password": _password(timestamp),
        "Timestamp": timestamp,
        "TransactionType": cfg()["TRANSACTION_TYPE"],
        "Amount": int(amount),
        "PartyA": phone,
        "PartyB": cfg()["PARTY_B"],
        "PhoneNumber": phone,
        "CallBackURL": callback_url(),
        "AccountReference": reference[:12],
        "TransactionDesc": description[:13],
    }
    data = _post("/mpesa/stkpush/v1/processrequest", payload)
    if str(data.get("ResponseCode")) != "0":
        message = data.get("CustomerMessage") or data.get("errorMessage") or data.get("ResponseDescription") or "M-Pesa rejected the request."
        logger.warning("STK push rejected: %s", data)
        raise MpesaError(message)
    return data


def stk_query(checkout_request_id):
    """Ask Daraja for the outcome of an STK push. Returns None while it is still processing."""
    if is_simulated() or checkout_request_id.startswith("ws_CO_SIM"):
        return {"ResultCode": "0", "ResultDesc": "Simulated payment accepted."}

    timestamp = _timestamp()
    data = _post("/mpesa/stkpushquery/v1/query", {
        "BusinessShortCode": cfg()["SHORTCODE"],
        "Password": _password(timestamp),
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id,
    })
    if "errorCode" in data or "ResultCode" not in data:
        return None  # e.g. 500.001.1001 "The transaction is being processed"
    return data
