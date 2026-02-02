from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class PaymentEvent:
    external_payment_id: str
    status: str
    amount: int
    metadata: dict[str, str]


class PaymentProvider(Protocol):
    async def create_payment(self, user_id: int, plan_id: str, amount: int, return_url: str) -> tuple[str, str]:
        raise NotImplementedError

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        raise NotImplementedError

    def parse_event(self, body: bytes) -> PaymentEvent:
        raise NotImplementedError
