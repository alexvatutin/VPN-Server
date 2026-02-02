from __future__ import annotations

from aiogram import Bot


class TelegramNotifier:
    def __init__(self, token: str) -> None:
        self._bot = Bot(token=token)

    async def send(self, telegram_id: int, message: str) -> None:
        await self._bot.send_message(chat_id=telegram_id, text=message)
