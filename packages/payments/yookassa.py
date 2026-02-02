from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid

import httpx

from packages.payments.provider import PaymentEvent, PaymentProvider


class YooKassaProvider(PaymentProvider):
    def __init__(self, shop_id: str, api_key: str, webhook_secret: str | None = None) -> None:
        self._shop_id = shop_id
        self._api_key = api_key
        self._webhook_secret = webhook_secret

    async def create_payment(self, user_id: int, plan_id: str, amount: int, return_url: str) -> tuple[str, str]:
        payload = {
            "amount": {"value": f"{amount / 100:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": return_url},
            "capture": True,
            "metadata": {"user_id": str(user_id), "plan_id": plan_id},
            "description": f"Subscription {plan_id}",
        }
        headers = self._auth_headers()
        headers["Idempotence-Key"] = str(uuid.uuid4())
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post("https://api.yookassa.ru/v3/payments", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        external_id = data["id"]
        confirmation_url = data["confirmation"]["confirmation_url"]
        return external_id, confirmation_url

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        if not self._webhook_secret:
            return True
        signature = headers.get("Content-Signature") or headers.get("Content-Signature-256")
        if not signature:
            return False
        digest = hmac.new(self._webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, digest)

    def parse_event(self, body: bytes) -> PaymentEvent:
        payload = json.loads(body.decode("utf-8"))
        obj = payload.get("object", {})
        amount_value = obj.get("amount", {}).get("value", "0")
        amount = int(float(amount_value) * 100)
        metadata = obj.get("metadata", {})
        return PaymentEvent(
            external_payment_id=obj.get("id", ""),
            status=obj.get("status", ""),
            amount=amount,
            metadata={str(k): str(v) for k, v in metadata.items()},
        )

    def _auth_headers(self) -> dict[str, str]:
        token = f"{self._shop_id}:{self._api_key}".encode("utf-8")
        encoded = base64.b64encode(token).decode("ascii")
        return {"Authorization": f"Basic {encoded}"}
