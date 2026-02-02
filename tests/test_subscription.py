from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.core.db import Base
from packages.core.models import Subscription, SubscriptionStatus
from packages.core.services import SubscriptionService


@pytest.fixture()
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest.mark.asyncio
async def test_extend_subscription(session: AsyncSession) -> None:
    subscription = Subscription(status=SubscriptionStatus.expired)
    session.add(subscription)
    await session.flush()

    await SubscriptionService.extend(session, subscription, timedelta(days=30))
    assert subscription.end_at is not None
    assert subscription.status == SubscriptionStatus.active
