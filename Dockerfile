# 四個應用程序及一次性工作共用相同環境。
FROM python:3.12.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY api ./api
COPY gateway ./gateway
COPY appsettings.json ./appsettings.json
COPY config ./config
COPY receiver ./receiver
COPY simulator ./simulator
COPY storage ./storage
COPY tests ./tests
COPY docs/mqtt/telemetry.example.json ./docs/mqtt/telemetry.example.json
RUN mkdir -p /app/data && chown 10001:10001 /app/data
USER 10001:10001
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
