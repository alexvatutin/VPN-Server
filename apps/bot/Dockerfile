FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY packages /app/packages
COPY apps/bot /app/apps/bot

ENV PYTHONPATH=/app

CMD ["python", "-m", "apps.bot.main"]
