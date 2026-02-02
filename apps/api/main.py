from __future__ import annotations

from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.config import Settings
from packages.core.db import create_sessionmaker
from packages.core.models import Payment, PaymentStatus, Subscription, SubscriptionStatus, User
from packages.core.rate_limiter import InMemoryRateLimiter
from packages.core.services import PaymentService, SubscriptionService
from packages.core.telegram_client import TelegramNotifier
from packages.core.plans import PLANS
from packages.payments.provider import PaymentEvent
from packages.payments.yookassa import YooKassaProvider

settings = Settings()
sessionmaker = create_sessionmaker(settings.database_url)
limiter = InMemoryRateLimiter(capacity=10, refill_rate=1.0)
notifier = TelegramNotifier(settings.telegram_bot_token)

app = FastAPI(title="VPN Control Plane API")


async def get_session() -> AsyncSession:
    async with sessionmaker() as session:
        yield session


def get_yookassa_provider() -> YooKassaProvider:
    if not settings.yookassa_shop_id or not settings.yookassa_api_key:
        raise HTTPException(status_code=500, detail="YooKassa credentials missing.")
    return YooKassaProvider(
        settings.yookassa_shop_id,
        settings.yookassa_api_key,
        settings.yookassa_webhook_secret,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/payments/yookassa")
async def yookassa_webhook(
    request: Request,
    content_signature: str | None = Header(default=None, alias="Content-Signature"),
    content_signature_256: str | None = Header(default=None, alias="Content-Signature-256"),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    ip = request.client.host if request.client else "unknown"
    if not limiter.allow(ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")

    body = await request.body()
    provider = get_yookassa_provider()
    headers = {
        "Content-Signature": content_signature or "",
        "Content-Signature-256": content_signature_256 or "",
    }
    if not provider.verify_webhook(headers, body):
        raise HTTPException(status_code=400, detail="Invalid signature.")

    event = provider.parse_event(body)
    await handle_payment_event(session, event)
    await session.commit()
    return JSONResponse({"status": "ok"})


async def handle_payment_event(session: AsyncSession, event: PaymentEvent) -> None:
    if not event.external_payment_id:
        return
    payment = await session.scalar(select(Payment).where(Payment.external_id == event.external_payment_id))
    if not payment:
        return
    if event.status == "succeeded" and payment.status != PaymentStatus.succeeded:
        payment.status = PaymentStatus.succeeded
        subscription = await session.scalar(select(Subscription).where(Subscription.user_id == payment.user_id))
        if subscription:
            duration = PLANS.get(payment.plan_id, {}).get("duration")
            if duration:
                await SubscriptionService.extend(session, subscription, duration)
        user = await session.scalar(select(User).where(User.id == payment.user_id))
        if user:
            await notifier.send(user.telegram_id, "✅ Payment succeeded. Your access is now active.")
    elif event.status in {"canceled", "failed"}:
        payment.status = PaymentStatus.failed
        user = await session.scalar(select(User).where(User.id == payment.user_id))
        if user:
            await notifier.send(user.telegram_id, "❌ Payment failed or canceled.")


async def notify_expirations() -> None:
    async with sessionmaker() as session:
        now = datetime.utcnow()
        soon = now + timedelta(days=3)
        very_soon = now + timedelta(days=1)
        result = await session.execute(
            select(Subscription).where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.end_at.is_not(None),
            )
        )
        subscriptions = result.scalars().all()
        for subscription in subscriptions:
            if not subscription.end_at:
                continue
            user = await session.scalar(select(User).where(User.id == subscription.user_id))
            if not user:
                continue
            remaining = subscription.end_at - now
            if timedelta(days=0) < remaining <= timedelta(days=1):
                await notifier.send(user.telegram_id, "⚠️ Your access expires in 1 day.")
            elif timedelta(days=1) < remaining <= timedelta(days=3):
                await notifier.send(user.telegram_id, "⏳ Your access expires in 3 days.")
        await session.commit()


async def refresh_subscriptions() -> None:
    async with sessionmaker() as session:
        result = await session.execute(select(Subscription))
        for subscription in result.scalars():
            await SubscriptionService.refresh_status(session, subscription)
        await session.commit()


def _schedule_jobs(scheduler: AsyncIOScheduler) -> None:
    scheduler.add_job(notify_expirations, "interval", hours=12)
    scheduler.add_job(refresh_subscriptions, "interval", hours=6)


@app.on_event("startup")
async def startup_event() -> None:
    scheduler = AsyncIOScheduler()
    _schedule_jobs(scheduler)
    scheduler.start()
    app.state.scheduler = scheduler


@app.on_event("shutdown")
async def shutdown_event() -> None:
    scheduler: AsyncIOScheduler = app.state.scheduler
    scheduler.shutdown()
