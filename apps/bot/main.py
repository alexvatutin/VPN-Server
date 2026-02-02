from __future__ import annotations

import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.middleware.base import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from sqlalchemy import select

from packages.core.config import Settings
from packages.core.db import create_sessionmaker
from packages.core.models import Device, DeviceStatus, Payment, Subscription, SubscriptionStatus, User, UserStatus
from packages.core.plans import PLANS
from packages.core.rate_limiter import InMemoryRateLimiter
from packages.core.services import AuditService, DeviceService, PaymentService, SubscriptionService, UserService
from packages.gateway.mock import MockGatewayDriver
from packages.payments.stubs import StubProvider
from packages.payments.yookassa import YooKassaProvider

logging.basicConfig(level=logging.INFO)

settings = Settings()
sessionmaker = create_sessionmaker(settings.database_url)
driver = MockGatewayDriver()
limiter = InMemoryRateLimiter(capacity=5, refill_rate=1.0)

router = Router()


class DeviceStates(StatesGroup):
    waiting_name = State()


class BroadcastStates(StatesGroup):
    waiting_text = State()
    waiting_confirm = State()


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Buy / Extend", callback_data="buy")],
            [InlineKeyboardButton(text="Subscription status", callback_data="status")],
            [InlineKeyboardButton(text="My devices", callback_data="devices")],
            [InlineKeyboardButton(text="Get config", callback_data="get_config")],
            [InlineKeyboardButton(text="Support / FAQ", callback_data="support")],
        ]
    )


def aup_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="I agree", callback_data="aup_accept")]]
    )


def plans_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"{plan_id} - {plan['price'] / 100:.0f} RUB", callback_data=f"plan:{plan_id}")]
        for plan_id, plan in PLANS.items()
    ]
    buttons.append([InlineKeyboardButton(text="Back", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_user_keyboard(user: User) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Grant +30 days", callback_data=f"admin_grant:{user.telegram_id}:30"),
                InlineKeyboardButton(text="Ban", callback_data=f"admin_ban:{user.telegram_id}"),
            ],
            [
                InlineKeyboardButton(text="Unban", callback_data=f"admin_unban:{user.telegram_id}"),
                InlineKeyboardButton(text="Revoke all devices", callback_data=f"admin_revoke_devices:{user.telegram_id}"),
            ],
        ]
    )


def devices_keyboard(devices: list[Device]) -> InlineKeyboardMarkup:
    keyboard_rows = []
    for device in devices:
        keyboard_rows.append(
            [
                InlineKeyboardButton(text=f"Revoke {device.name}", callback_data=f"device_revoke:{device.device_id}"),
                InlineKeyboardButton(text="Rotate", callback_data=f"device_rotate:{device.device_id}"),
            ]
        )
    keyboard_rows.append([InlineKeyboardButton(text="Back", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


def provider():
    if settings.yookassa_shop_id and settings.yookassa_api_key:
        return YooKassaProvider(settings.yookassa_shop_id, settings.yookassa_api_key, settings.yookassa_webhook_secret)
    return StubProvider("yookassa")


@router.message(Command("start"))
async def start_handler(message: Message) -> None:
    async with sessionmaker() as session:
        user = await UserService.get_or_create(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        await session.commit()
        if user.status == UserStatus.banned:
            await message.answer("Your account is banned. Contact support.")
            return
        if not user.accepted_aup:
            await message.answer(
                "Before using the service, please accept the Acceptable Use Policy.",
                reply_markup=aup_keyboard(),
            )
            return
    await message.answer("Welcome! Choose an option:", reply_markup=main_menu())


@router.callback_query(F.data == "aup_accept")
async def aup_accept_handler(callback: CallbackQuery) -> None:
    async with sessionmaker() as session:
        result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        if user:
            await UserService.set_aup(session, user, True)
        await session.commit()
    await callback.message.answer("✅ Thanks! You can now buy access or manage devices.")
    await callback.message.answer("Main menu:", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "buy")
async def buy_handler(callback: CallbackQuery) -> None:
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        if not user or user.status == UserStatus.banned:
            await callback.message.answer("Your account is banned. Contact support.")
            await callback.answer()
            return
        if not user.accepted_aup:
            await callback.message.answer("Please accept the Acceptable Use Policy first.", reply_markup=aup_keyboard())
            await callback.answer()
            return
    await callback.message.answer("Choose a plan:", reply_markup=plans_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("plan:"))
async def plan_handler(callback: CallbackQuery) -> None:
    plan_id = callback.data.split(":", 1)[1]
    plan = PLANS.get(plan_id)
    if not plan:
        await callback.answer("Unknown plan.")
        return
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        if not user:
            await callback.answer("User not found.")
            return
        try:
            external_id, confirmation_url = await provider().create_payment(
                user_id=user.id,
                plan_id=plan_id,
                amount=int(plan["price"]),
                return_url=f"{settings.api_public_url}/payments/return",
            )
        except NotImplementedError:
            await callback.message.answer("Payment provider is not configured yet. Contact support.")
            await callback.answer()
            return
        await PaymentService.create(
            session,
            user=user,
            provider="yookassa",
            external_id=external_id,
            plan_id=plan_id,
            amount=int(plan["price"]),
        )
        await session.commit()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Pay now", url=confirmation_url)]]
    )
    await callback.message.answer("Complete payment via the link below:", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "status")
async def status_handler(callback: CallbackQuery) -> None:
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        if not user:
            await callback.answer("User not found.")
            return
        if user.status == UserStatus.banned:
            await callback.message.answer("Your account is banned. Contact support.")
            await callback.answer()
            return
        subscription = await session.scalar(select(Subscription).where(Subscription.user_id == user.id))
        if subscription:
            await SubscriptionService.refresh_status(session, subscription)
            await session.commit()
            end_at = subscription.end_at.isoformat() if subscription.end_at else "N/A"
            await callback.message.answer(
                f"Status: {subscription.status.value}\nExpires at: {end_at}"
            )
    await callback.answer()


@router.callback_query(F.data == "devices")
async def devices_handler(callback: CallbackQuery) -> None:
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        if not user:
            await callback.answer("User not found.")
            return
        if user.status == UserStatus.banned:
            await callback.message.answer("Your account is banned. Contact support.")
            await callback.answer()
            return
        devices = await session.execute(select(Device).where(Device.user_id == user.id))
        device_list = devices.scalars().all()
    if not device_list:
        await callback.message.answer("No devices yet. Use 'Get config' to add one.")
    else:
        lines = []
        for device in device_list:
            lines.append(f"{device.name} ({device.status.value}) - created {device.created_at.date()}")
        await callback.message.answer("\n".join(lines), reply_markup=devices_keyboard(device_list))
    await callback.answer()


@router.callback_query(F.data == "back")
async def back_handler(callback: CallbackQuery) -> None:
    await callback.message.answer("Main menu:", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("device_revoke"))
async def device_revoke_handler(callback: CallbackQuery) -> None:
    _, device_id = callback.data.split(":")
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        if not user:
            await callback.answer("User not found.")
            return
        device = await session.scalar(select(Device).where(Device.device_id == device_id, Device.user_id == user.id))
        if not device:
            await callback.answer("Device not found.")
            return
        await DeviceService.revoke(session, device)
        await driver.revoke_device(device.device_id)
        await session.commit()
    await callback.message.answer("Device revoked.")
    await callback.answer()


@router.callback_query(F.data.startswith("device_rotate"))
async def device_rotate_handler(callback: CallbackQuery) -> None:
    _, device_id = callback.data.split(":")
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        if not user:
            await callback.answer("User not found.")
            return
        device = await session.scalar(select(Device).where(Device.device_id == device_id, Device.user_id == user.id))
        if not device:
            await callback.answer("Device not found.")
            return
        await DeviceService.rotate(session, device)
        profile = await driver.rotate_device(device.device_id)
        await session.commit()
    await callback.message.answer(f"Rotated config:\n\n{profile.config_text}")
    if profile.qr_png_bytes:
        await callback.message.answer_photo(profile.qr_png_bytes, caption="Updated QR.")
    await callback.answer()


@router.callback_query(F.data == "get_config")
async def get_config_handler(callback: CallbackQuery, state: FSMContext) -> None:
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        if not user or user.status == UserStatus.banned:
            await callback.message.answer("Your account is banned. Contact support.")
            await callback.answer()
            return
        if not user.accepted_aup:
            await callback.message.answer("Please accept the Acceptable Use Policy first.", reply_markup=aup_keyboard())
            await callback.answer()
            return
        subscription = await session.scalar(select(Subscription).where(Subscription.user_id == user.id))
        if subscription:
            await SubscriptionService.refresh_status(session, subscription)
            await session.commit()
        if not subscription or subscription.status != SubscriptionStatus.active:
            await callback.message.answer("Subscription inactive. Please buy or extend.")
            await callback.answer()
            return
        active_count = await DeviceService.active_count(session, user)
        if active_count >= 5:
            await callback.message.answer("Device limit reached (5). Revoke a device first.")
            await callback.answer()
            return
    await state.set_state(DeviceStates.waiting_name)
    await callback.message.answer("Send a name for the new device:")
    await callback.answer()


@router.message(DeviceStates.waiting_name)
async def device_name_handler(message: Message, state: FSMContext) -> None:
    device_name = message.text.strip()
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if not user:
            await message.answer("User not found.")
            await state.clear()
            return
        device = await DeviceService.create(session, user, device_name)
        profile = await driver.provision_device(user.id, device.device_id, device.name)
        await session.commit()
    await message.answer(f"Here is your config:\n\n{profile.config_text}")
    if profile.qr_png_bytes:
        await message.answer_photo(profile.qr_png_bytes, caption="Scan the QR for quick setup.")
    await state.clear()


@router.message(Command("admin_users"))
async def admin_users_handler(message: Message, command: CommandObject) -> None:
    if message.from_user.id not in settings.admin_ids:
        await message.answer("Not authorized.")
        return
    query = (command.args or "").strip()
    async with sessionmaker() as session:
        if query.isdigit():
            result = await session.execute(select(User).where(User.telegram_id == int(query)))
        elif query:
            result = await session.execute(select(User).where(User.username.ilike(f"%{query}%")))
        else:
            result = await session.execute(select(User).order_by(User.created_at.desc()).limit(20))
        users = result.scalars().all()
    if not users:
        await message.answer("No users found.")
        return
    lines = [f"{user.telegram_id} @{user.username or '-'} ({user.status.value})" for user in users]
    await message.answer("\n".join(lines))


@router.message(Command("admin_user"))
async def admin_user_handler(message: Message, command: CommandObject) -> None:
    if message.from_user.id not in settings.admin_ids:
        await message.answer("Not authorized.")
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Usage: /admin_user <telegram_id>")
        return
    telegram_id = int(command.args.strip())
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if not user:
            await message.answer("User not found.")
            return
        subscription = await session.scalar(select(Subscription).where(Subscription.user_id == user.id))
        await message.answer(
            f"User {user.telegram_id} @{user.username or '-'}\n"
            f"Status: {user.status.value}\n"
            f"Subscription: {subscription.status.value if subscription else 'N/A'}",
            reply_markup=admin_user_keyboard(user),
        )


@router.message(Command("admin_payments"))
async def admin_payments_handler(message: Message) -> None:
    if message.from_user.id not in settings.admin_ids:
        await message.answer("Not authorized.")
        return
    async with sessionmaker() as session:
        result = await session.execute(
            select(Payment).order_by(Payment.created_at.desc()).limit(50)
        )
        payments = result.scalars().all()
    if not payments:
        await message.answer("No payments found.")
        return
    lines = [
        f"{payment.external_id} {payment.plan_id} {payment.amount / 100:.0f} RUB {payment.status.value}"
        for payment in payments
    ]
    await message.answer("\n".join(lines))


@router.message(Command("admin_revoke_device"))
async def admin_revoke_device_handler(message: Message, command: CommandObject) -> None:
    if message.from_user.id not in settings.admin_ids:
        await message.answer("Not authorized.")
        return
    args = (command.args or "").split()
    if len(args) != 2:
        await message.answer("Usage: /admin_revoke_device <telegram_id> <device_id>")
        return
    telegram_id, device_id = args
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == int(telegram_id)))
        if not user:
            await message.answer("User not found.")
            return
        device = await session.scalar(select(Device).where(Device.device_id == device_id, Device.user_id == user.id))
        if not device:
            await message.answer("Device not found.")
            return
        await DeviceService.revoke(session, device)
        await driver.revoke_device(device.device_id)
        await AuditService.record(
            session,
            actor_telegram_id=message.from_user.id,
            action="admin_revoke_device",
            metadata=f"telegram_id={telegram_id},device_id={device_id}",
        )
        await session.commit()
    await message.answer("Device revoked.")


@router.callback_query(F.data.startswith("admin_grant"))
async def admin_grant_handler(callback: CallbackQuery) -> None:
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer("Not authorized.")
        return
    _, telegram_id, days = callback.data.split(":")
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == int(telegram_id)))
        if not user:
            await callback.message.answer("User not found.")
            await callback.answer()
            return
        subscription = await session.scalar(select(Subscription).where(Subscription.user_id == user.id))
        if subscription:
            await SubscriptionService.extend(session, subscription, timedelta(days=int(days)))
        await AuditService.record(
            session,
            actor_telegram_id=callback.from_user.id,
            action="admin_grant",
            metadata=f"telegram_id={telegram_id},days={days}",
        )
        await session.commit()
    await callback.message.answer("✅ Granted.")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ban"))
async def admin_ban_handler(callback: CallbackQuery) -> None:
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer("Not authorized.")
        return
    _, telegram_id = callback.data.split(":")
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == int(telegram_id)))
        if user:
            await UserService.set_status(session, user, UserStatus.banned)
        await AuditService.record(
            session,
            actor_telegram_id=callback.from_user.id,
            action="admin_ban",
            metadata=f"telegram_id={telegram_id}",
        )
        await session.commit()
    await callback.message.answer("User banned.")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_unban"))
async def admin_unban_handler(callback: CallbackQuery) -> None:
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer("Not authorized.")
        return
    _, telegram_id = callback.data.split(":")
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == int(telegram_id)))
        if user:
            await UserService.set_status(session, user, UserStatus.active)
        await AuditService.record(
            session,
            actor_telegram_id=callback.from_user.id,
            action="admin_unban",
            metadata=f"telegram_id={telegram_id}",
        )
        await session.commit()
    await callback.message.answer("User unbanned.")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_revoke_devices"))
async def admin_revoke_devices_handler(callback: CallbackQuery) -> None:
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer("Not authorized.")
        return
    _, telegram_id = callback.data.split(":")
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == int(telegram_id)))
        if not user:
            await callback.answer("User not found.")
            return
        devices = await session.execute(
            select(Device).where(Device.user_id == user.id, Device.status == DeviceStatus.active)
        )
        for device in devices.scalars():
            await DeviceService.revoke(session, device)
        await AuditService.record(
            session,
            actor_telegram_id=callback.from_user.id,
            action="admin_revoke_devices",
            metadata=f"telegram_id={telegram_id}",
        )
        await session.commit()
    await callback.message.answer("Devices revoked.")
    await callback.answer()


@router.message(Command("admin_broadcast"))
async def admin_broadcast_handler(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in settings.admin_ids:
        await message.answer("Not authorized.")
        return
    await state.set_state(BroadcastStates.waiting_text)
    await message.answer("Send the broadcast message text.")


@router.message(BroadcastStates.waiting_text)
async def broadcast_text_handler(message: Message, state: FSMContext) -> None:
    await state.update_data(text=message.text)
    await state.set_state(BroadcastStates.waiting_confirm)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Confirm", callback_data="broadcast_confirm")],
            [InlineKeyboardButton(text="Cancel", callback_data="broadcast_cancel")],
        ]
    )
    await message.answer("Confirm broadcast?", reply_markup=keyboard)


@router.callback_query(F.data == "broadcast_confirm")
async def broadcast_confirm_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer("Not authorized.")
        return
    data = await state.get_data()
    text = data.get("text", "")
    async with sessionmaker() as session:
        result = await session.execute(select(User).where(User.status == UserStatus.active))
        users = result.scalars().all()
        bot = callback.bot
        for user in users:
            await bot.send_message(chat_id=user.telegram_id, text=text)
        await AuditService.record(
            session,
            actor_telegram_id=callback.from_user.id,
            action="admin_broadcast",
            metadata=f"count={len(users)}",
        )
        await session.commit()
    await callback.message.answer("Broadcast sent.")
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Broadcast canceled.")
    await callback.answer()


@router.callback_query(F.data == "support")
async def support_handler(callback: CallbackQuery) -> None:
    await callback.message.answer("Contact support at @your_support_handle.")
    await callback.answer()


class RateLimitMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if hasattr(event, "from_user") and event.from_user:
            key = str(event.from_user.id)
            if not limiter.allow(key):
                if isinstance(event, Message):
                    await event.answer("Too many requests. Please slow down.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("Too many requests.", show_alert=True)
                return
        return await handler(event, data)


async def main() -> None:
    bot = Bot(token=settings.telegram_bot_token, parse_mode=ParseMode.HTML)
    dp = Dispatcher()
    dp.message.middleware(RateLimitMiddleware())
    dp.callback_query.middleware(RateLimitMiddleware())
    dp.include_router(router)
    if settings.webhook_mode:
        webhook_url = f"{settings.api_public_url}/telegram/webhook"
        await bot.set_webhook(webhook_url)
        app = web.Application()
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/telegram/webhook")
        setup_application(app, dp, bot=bot)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", 8081)
        await site.start()
        await asyncio.Event().wait()
    else:
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
