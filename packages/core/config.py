from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(..., alias="DATABASE_URL")
    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    admin_telegram_ids: str = Field("", alias="ADMIN_TELEGRAM_IDS")
    webhook_mode: bool = Field(False, alias="WEBHOOK_MODE")
    api_public_url: str = Field("http://localhost:8000", alias="API_PUBLIC_URL")

    yookassa_shop_id: str | None = Field(None, alias="YOOKASSA_SHOP_ID")
    yookassa_api_key: str | None = Field(None, alias="YOOKASSA_API_KEY")
    yookassa_webhook_secret: str | None = Field(None, alias="YOOKASSA_WEBHOOK_SECRET")

    @property
    def admin_ids(self) -> set[int]:
        if not self.admin_telegram_ids:
            return set()
        return {int(value.strip()) for value in self.admin_telegram_ids.split(",") if value.strip()}
