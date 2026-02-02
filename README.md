# Telegram Paid Access Control Plane (MVP)

This repository provides a production-ready control plane for a small paid-access service managed via a Telegram bot. It **does not** include any VPN or censorship-bypass implementation. Instead, it ships a pluggable `GatewayDriver` interface with a fully working mock driver for end-to-end testing. 

## MVP assumptions
- Up to 50 paying users.
- Up to 5 active devices per user.
- Single region.
- One-time payments only (recurring billing can be added later).
- Users are identified by Telegram `user_id` only.

## Architecture
- **apps/api**: FastAPI app for webhooks, health, and scheduling (APS cheduler).
- **apps/bot**: aiogram 3.x Telegram bot for UX and admin actions.
- **packages/core**: domain models, services, rate limiter, settings.
- **packages/gateway**: `GatewayDriver` interface and Mock implementation (QR codes).
- **packages/payments**: provider interface + YooKassa implementation + stubs.
- **infra**: docker-compose and DB initialization.
- **tests**: unit tests for core services and payment webhook idempotency.

## Features
- User onboarding via Telegram.
- Acceptable Use consent flow (required before purchase/device provisioning).
- Plans in code (`PLANS`), prices in kopeks.
- One-time payment flow: create payment -> confirmation URL -> webhook -> extend subscription.
- Device lifecycle: add, list, revoke, rotate.
- Admin tools via bot commands with audit logs.
- Expiry reminders at 3 days and 1 day.
- In-memory rate limiting for bot and webhooks (replace with Redis if needed).

## Quick start (Docker)
```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

## Environment variables
| Variable | Description |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `DATABASE_URL` | PostgreSQL async URL |
| `ADMIN_TELEGRAM_IDS` | Comma-separated admin Telegram IDs |
| `YOOKASSA_SHOP_ID` | YooKassa shop ID |
| `YOOKASSA_API_KEY` | YooKassa API key |
| `YOOKASSA_WEBHOOK_SECRET` | Optional webhook signature secret |
| `API_PUBLIC_URL` | Public URL for return links |

## Webhooks
- Default bot mode is long polling.
- If you enable webhooks on Telegram, set `WEBHOOK_MODE=true` and configure Telegram to hit your public API URL.
- The bot service listens on port `8081` in webhook mode (see docker-compose port mapping).
- YooKassa webhook endpoint:
  - `POST /webhooks/payments/yookassa`

## Admin usage
Set `ADMIN_TELEGRAM_IDS` to a comma-separated list of Telegram IDs.

Commands:
- `/admin_users [query]`
- `/admin_user <telegram_id>`
- `/admin_broadcast`

Admin actions (grant days, ban/unban, revoke devices) generate audit logs.

## Gateway driver
`GatewayDriver` is the interface used by the bot to provision, revoke, and rotate device access profiles. The mock implementation generates a dummy config and QR code. Replace it with a real driver later without changing the bot or API flows.

## Security notes
- Secrets are sourced from environment variables.
- Webhooks validate signatures when `YOOKASSA_WEBHOOK_SECRET` is provided.
- Rate limiting uses an in-memory token bucket (not suitable for multi-instance).
- The system stores minimal data (no traffic logs).

## Acceptable Use Policy (example)
Users must accept an acceptable use policy before purchasing or provisioning devices. Adjust the policy text in the bot messaging to match your compliance requirements.

## Local development
```bash
make install
make migrate
make run-api
make run-bot
```
