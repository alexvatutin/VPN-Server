from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.models import (
    AuditLog,
    Device,
    DeviceStatus,
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionStatus,
    User,
    UserStatus,
)


class UserService:
    @staticmethod
    async def get_or_create(
        session: AsyncSession,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
    ) -> User:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user:
            return user
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
        )
        session.add(user)
        await session.flush()
        subscription = Subscription(user_id=user.id, status=SubscriptionStatus.expired)
        session.add(subscription)
        await session.flush()
        return user

    @staticmethod
    async def set_aup(session: AsyncSession, user: User, accepted: bool) -> User:
        user.accepted_aup = accepted
        await session.flush()
        return user

    @staticmethod
    async def set_status(session: AsyncSession, user: User, status: UserStatus) -> User:
        user.status = status
        await session.flush()
        return user


class SubscriptionService:
    @staticmethod
    async def extend(session: AsyncSession, subscription: Subscription, duration: timedelta) -> Subscription:
        now = datetime.utcnow()
        if subscription.end_at and subscription.end_at > now:
            subscription.end_at += duration
        else:
            subscription.end_at = now + duration
        subscription.status = SubscriptionStatus.active
        await session.flush()
        return subscription

    @staticmethod
    async def refresh_status(session: AsyncSession, subscription: Subscription) -> Subscription:
        now = datetime.utcnow()
        if subscription.end_at and subscription.end_at > now:
            subscription.status = SubscriptionStatus.active
        else:
            subscription.status = SubscriptionStatus.expired
        await session.flush()
        return subscription


class DeviceService:
    @staticmethod
    async def active_count(session: AsyncSession, user: User) -> int:
        result = await session.execute(
            select(Device).where(Device.user_id == user.id, Device.status == DeviceStatus.active)
        )
        return len(result.scalars().all())

    @staticmethod
    async def create(session: AsyncSession, user: User, name: str) -> Device:
        device = Device(user_id=user.id, name=name)
        session.add(device)
        await session.flush()
        return device

    @staticmethod
    async def revoke(session: AsyncSession, device: Device) -> Device:
        device.status = DeviceStatus.revoked
        await session.flush()
        return device

    @staticmethod
    async def rotate(session: AsyncSession, device: Device) -> Device:
        device.rotated_at = datetime.utcnow()
        await session.flush()
        return device


class PaymentService:
    @staticmethod
    async def create(
        session: AsyncSession,
        user: User,
        provider: str,
        external_id: str,
        plan_id: str,
        amount: int,
    ) -> Payment:
        payment = Payment(
            user_id=user.id,
            provider=provider,
            external_id=external_id,
            plan_id=plan_id,
            amount=amount,
            status=PaymentStatus.pending,
        )
        session.add(payment)
        await session.flush()
        return payment

    @staticmethod
    async def update_status(session: AsyncSession, payment: Payment, status: PaymentStatus) -> Payment:
        payment.status = status
        await session.flush()
        return payment


class AuditService:
    @staticmethod
    async def record(session: AsyncSession, actor_telegram_id: int, action: str, metadata: str | None = None) -> AuditLog:
        log = AuditLog(actor_telegram_id=actor_telegram_id, action=action, metadata=metadata)
        session.add(log)
        await session.flush()
        return log
