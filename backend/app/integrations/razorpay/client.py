"""
Razorpay API client. TEST MODE ONLY.

Deliberately thin: this module knows how to make two documented Razorpay
API calls and turn their responses into typed results. It contains NO
business logic, NO rules-engine knowledge, and NO opinion about whether
a given action is "allowed" - that's the rules engine's job (Phase 3)
and the orchestrator's job (Phase 5), neither of which this file imports.

APIs used (both documented at https://razorpay.com/docs/api/payment-links/):
- POST /v1/payment_links   - create a Standard Payment Link
- GET  /v1/payment_links/{id} - fetch a Payment Link's current status

Why Payment Links, not a Payments API capture call: Razorpay's Payments
APIs retrieve payment details and capture an *already-authorized*
payment - they are not used to collect a new payment, and a failed
payment was never authorized. A Payment Link is the documented,
checkout-oriented way to give a customer a fresh, hosted way to pay.

Authentication: HTTP Basic Auth using (key_id, key_secret), exactly as
Razorpay's REST API documents. The secret is never logged: this file
contains no log/print statement anywhere, and no exception message
built here ever includes self._key_secret or a raw Authorization
header - errors surface only the HTTP status code and Razorpay's own
(non-secret) error description (see _request()).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


class RazorpayClientError(Exception):
    """Raised on any Razorpay API failure: network error, timeout,
    non-2xx response, or an unparseable response body. Never includes
    the API secret in its message."""


@dataclass(frozen=True)
class PaymentLinkResult:
    """Typed result of creating (or fetching) a Razorpay Payment Link."""

    id: str
    short_url: str
    reference_id: str
    status: str  # Razorpay's own status string, e.g. "created", "paid", "cancelled", "expired"
    amount: float  # INR, converted back from paise
    raw_status_field: str  # kept for forward-compat display; same as `status`


class RazorpayClient:
    """
    Minimal, typed wrapper around the two Razorpay Payment Links endpoints
    this project uses. Every method:
    - uses HTTPS
    - authenticates with HTTP Basic Auth (key_id, key_secret)
    - respects a configurable timeout
    - raises RazorpayClientError (never a raw httpx exception) on failure
    - returns a typed dataclass, never a raw dict
    """

    def __init__(self, key_id: str, key_secret: str, base_url: str, timeout_seconds: float = 10.0):
        if not key_id or not key_secret:
            raise RazorpayClientError("Razorpay key_id and key_secret are both required")
        self._key_id = key_id
        self._key_secret = key_secret
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def create_payment_link(
        self,
        amount_inr: float,
        reference_id: str,
        description: str,
        currency: str = "INR",
        customer: dict | None = None,
        notes: dict | None = None,
    ) -> PaymentLinkResult:
        """POST /v1/payment_links - creates a Standard Payment Link.
        Amount is converted to paise (Razorpay's smallest-unit convention)
        as its documented API requires."""
        body: dict = {
            "amount": round(amount_inr * 100),  # INR -> paise
            "currency": currency,
            "description": description,
            "reference_id": reference_id,
            "notes": notes or {},
        }
        if customer:
            body["customer"] = customer

        data = self._request("POST", "/payment_links", json=body)
        return self._parse_payment_link(data)

    def fetch_payment_link(self, payment_link_id: str) -> PaymentLinkResult:
        """GET /v1/payment_links/{id} - fetches current status."""
        data = self._request("GET", f"/payment_links/{payment_link_id}")
        return self._parse_payment_link(data)

    def _parse_payment_link(self, data: dict) -> PaymentLinkResult:
        try:
            return PaymentLinkResult(
                id=data["id"],
                short_url=data.get("short_url", ""),
                reference_id=data.get("reference_id", ""),
                status=data["status"],
                amount=float(data["amount"]) / 100.0,  # paise -> INR
                raw_status_field=data["status"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RazorpayClientError(f"Malformed Razorpay payment_link response: missing/invalid field ({exc})") from exc

    def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        url = f"{self._base_url}{path}"
        try:
            response = httpx.request(
                method,
                url,
                json=json,
                auth=(self._key_id, self._key_secret),
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise RazorpayClientError(f"Razorpay API request timed out ({method} {path})") from exc
        except httpx.HTTPError as exc:
            raise RazorpayClientError(f"Razorpay API request failed ({method} {path}): {type(exc).__name__}") from exc

        if response.status_code >= 400:
            # Include the status code and Razorpay's error description if
            # present, but never the request headers (which contain auth).
            try:
                error_body = response.json()
                description = error_body.get("error", {}).get("description", "")
            except ValueError:
                description = ""
            raise RazorpayClientError(
                f"Razorpay API returned {response.status_code} for {method} {path}"
                + (f": {description}" if description else "")
            )

        try:
            return response.json()
        except ValueError as exc:
            raise RazorpayClientError(f"Razorpay API returned non-JSON response ({method} {path})") from exc
