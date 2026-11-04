import hashlib
import hmac

import requests
from django.conf import settings

BASE_URL = "https://api.paystack.co"


class PaystackError(Exception):
    pass


def _headers():
    if not settings.PAYSTACK_SECRET_KEY:
        raise PaystackError("Online payments are not configured.")
    return {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}


def _call(method, path, **kwargs):
    try:
        response = requests.request(method, f"{BASE_URL}{path}", headers=_headers(), timeout=15, **kwargs)
        body = response.json()
    except (requests.RequestException, ValueError):
        raise PaystackError("Could not reach Paystack. Please try again.")
    if not response.ok or not body.get("status"):
        raise PaystackError(body.get("message") or "Paystack rejected the request.")
    return body["data"]


def initialize_transaction(email, amount_kobo, reference, callback_url, metadata):
    return _call("POST", "/transaction/initialize", json={
        "email": email,
        "amount": amount_kobo,
        "currency": "NGN",
        "reference": reference,
        "callback_url": callback_url,
        "metadata": metadata,
    })


def verify_transaction(reference):
    return _call("GET", f"/transaction/verify/{reference}")


def valid_signature(raw_body: bytes, signature: str) -> bool:
    if not settings.PAYSTACK_SECRET_KEY or not signature:
        return False
    expected = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)