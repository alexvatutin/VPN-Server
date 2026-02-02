from __future__ import annotations

import io
import secrets
from datetime import datetime

import qrcode

from packages.gateway.driver import AccessProfile, GatewayDriver


class MockGatewayDriver(GatewayDriver):
    async def provision_device(self, user_id: int, device_id: str, device_name: str) -> AccessProfile:
        config_text = self._build_config(user_id, device_id, device_name)
        return AccessProfile(config_text=config_text, qr_png_bytes=self._generate_qr(config_text))

    async def revoke_device(self, device_id: str) -> None:
        return None

    async def rotate_device(self, device_id: str) -> AccessProfile:
        config_text = (
            f"[client]\n"
            f"id={device_id}\n"
            f"rotated_at={datetime.utcnow().isoformat()}\n"
            f"token={secrets.token_hex(16)}\n"
            f"note=Mock profile rotated.\n"
        )
        return AccessProfile(config_text=config_text, qr_png_bytes=self._generate_qr(config_text))

    async def health(self) -> bool:
        return True

    def _build_config(self, user_id: int, device_id: str, device_name: str) -> str:
        return (
            f"[client]\n"
            f"user={user_id}\n"
            f"device_id={device_id}\n"
            f"device_name={device_name}\n"
            f"token={secrets.token_hex(16)}\n"
            f"created_at={datetime.utcnow().isoformat()}\n"
            f"note=Mock access profile. No VPN logic included.\n"
        )

    def _generate_qr(self, config_text: str) -> bytes:
        img = qrcode.make(config_text)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()
