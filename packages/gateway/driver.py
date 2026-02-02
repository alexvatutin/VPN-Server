from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class AccessProfile:
    config_text: str
    qr_png_bytes: bytes | None = None


class GatewayDriver(Protocol):
    async def provision_device(self, user_id: int, device_id: str, device_name: str) -> AccessProfile:
        raise NotImplementedError

    async def revoke_device(self, device_id: str) -> None:
        raise NotImplementedError

    async def rotate_device(self, device_id: str) -> AccessProfile:
        raise NotImplementedError

    async def health(self) -> bool:
        raise NotImplementedError
