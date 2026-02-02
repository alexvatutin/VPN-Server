from __future__ import annotations

from datetime import timedelta


PLANS: dict[str, dict[str, int | timedelta]] = {
    "1m": {"duration": timedelta(days=30), "price": 99000},
    "3m": {"duration": timedelta(days=90), "price": 249000},
}
