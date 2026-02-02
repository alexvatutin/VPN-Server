from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.core.db import Base
from packages.core.models import Payment, PaymentStatus, Subscription, SubscriptionStatus, User
from packages.payments.provider import PaymentEvent


@pytest.fixture()
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest.mark.asyncio
async def test_webhook_idempotent(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    from apps.api import main as api_main
    user = User(telegram_id=123, username="tester", first_name="Test")
    session.add(user)
    await session.flush()
    subscription = Subscription(user_id=user.id, status=SubscriptionStatus.expired)
    payment = Payment(
        user_id=user.id,
        provider="yookassa",
        external_id="pay_1",
        plan_id="1m",
        amount=99000,
        status=PaymentStatus.pending,
        created_at=datetime.utcnow(),
    )
    session.add_all([subscription, payment])
    await session.commit()

    notifications: list[int] = []

    class DummyNotifier:
        async def send(self, telegram_id: int, message: str) -> None:
            notifications.append(telegram_id)

    monkeypatch.setattr(api_main, "notifier", DummyNotifier())

    event = PaymentEvent(external_payment_id="pay_1", status="succeeded", amount=99000, metadata={})
    await api_main.handle_payment_event(session, event)
    await session.commit()
    first_end = subscription.end_at
    await api_main.handle_payment_event(session, event)
    await session.commit()
    second_end = subscription.end_at

    assert first_end == second_end
    assert len(notifications) == 1
