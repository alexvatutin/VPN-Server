from __future__ import annotations

from packages.payments.provider import PaymentEvent, PaymentProvider


class StubProvider(PaymentProvider):
    def __init__(self, name: str) -> None:
        self.name = name

    async def create_payment(self, user_id: int, plan_id: str, amount: int, return_url: str) -> tuple[str, str]:
        raise NotImplementedError(f"{self.name} provider not implemented yet.")

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        return False

    def parse_event(self, body: bytes) -> PaymentEvent:
        raise NotImplementedError(f"{self.name} provider not implemented yet.")
