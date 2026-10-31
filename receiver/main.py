"""接收端入口：載入自己的平台/來源映射設定，再建立持久訂閱。"""
from functools import partial
import json
import sys

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from receiver.config import DEFAULT_CONFIG_PATH, load_settings
from receiver.point_handler import handle_point_message
from receiver.subscribe import run_receiver
from storage.database import create_db_engine
from storage.point_telemetry import store_point_telemetry
from storage.source_mapping import configure_sources


def main(config_path=DEFAULT_CONFIG_PATH):
    try:
        settings = load_settings(config_path)
    except (OSError, ValueError) as exc:
        detail = ([{"field":list(item["loc"]), "type":item["type"]}
                   for item in exc.errors(include_input=False)] if isinstance(exc, ValidationError)
                  else type(exc).__name__)
        print(json.dumps({"event":"configuration_failed", "detail":detail}), file=sys.stderr)
        return 1
    engine = create_db_engine(settings.database_url)
    try:
        configure_sources(engine, settings)
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.receiver_id,
                            clean_session=False, manual_ack=True, protocol=mqtt.MQTTv311,
                            reconnect_on_failure=False)
        if settings.mqtt.username is not None:
            client.username_pw_set(settings.mqtt.username, settings.mqtt.password)
        return run_receiver(client,
            store=partial(store_point_telemetry, engine, receiver_id=settings.receiver_id),
            message_handler=handle_point_message, topic_filters=settings.topics,
            host=settings.mqtt.host, port=settings.mqtt.port, timeout=settings.mqtt.timeout_seconds,
            ready_file=settings.ready_file)
    finally:
        engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 1:
        print("Receiver 只使用 receiver.appsettings.json。", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main())
