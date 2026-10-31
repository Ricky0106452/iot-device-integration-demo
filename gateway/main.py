"""Gateway 唯一入口；固定載入專案根目錄 appsettings.json，不讀命令列或環境設定。"""
from datetime import datetime, timezone
from functools import partial
import json
import sqlite3
import sys

from pydantic import ValidationError

from gateway.buffering.outbox import Outbox
from gateway.buffering.sender import OutboxSender
from gateway.config import DEFAULT_CONFIG_PATH, load_settings
from gateway.messaging.publisher import publish_telemetry
from gateway.polling import run_polling


def main(config_path=DEFAULT_CONFIG_PATH) -> int:
    try:
        settings = load_settings(config_path)
    except (OSError, ValueError, ValidationError) as exc:
        # Pydantic 原始輸入可能含密碼，只記欄位位置與錯誤種類。
        detail = ([{"field": ".".join(map(str, item["loc"])), "type": item["type"]}
                   for item in exc.errors(include_input=False)] if isinstance(exc, ValidationError)
                  else type(exc).__name__)
        print(json.dumps({"event": "configuration_failed", "detail": detail}), file=sys.stderr)
        return 1
    try:
        with Outbox(settings.buffer.path, max_pending=settings.buffer.max_pending) as outbox:
            publisher = partial(publish_telemetry, host=settings.mqtt.host,
                                port=settings.mqtt.port, timeout=settings.mqtt.timeout_seconds,
                                username=settings.mqtt.username, password=settings.mqtt.password)
            with OutboxSender(outbox, publisher,
                              retry_interval=settings.buffer.retry_interval_seconds) as sender:
                return run_polling(settings, outbox, sender)
    except (sqlite3.Error, OSError) as exc:
        print(json.dumps({"event": "outbox_storage_failed", "detail": str(exc),
                          "attempt_finished_at": datetime.now(timezone.utc).isoformat()}),
              file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 1:
        print("Gateway 只使用 appsettings.json；不接受命令列參數。", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main())
