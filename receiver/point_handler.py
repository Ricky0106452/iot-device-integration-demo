"""v2 接收處理；Topic 與來源識別依平台映射核對，不假設平台點位名稱相同。"""
from datetime import datetime, timezone
import json
import sys

from pydantic import ValidationError

from receiver.point_models import PointTelemetry
from storage.device_setup import DeviceConfigurationError


def handle_point_message(topic, payload, *, store):
    received_at = datetime.now(timezone.utc)
    if len(payload) > 262144:
        print(json.dumps({"event":"telemetry_rejected", "code":"payload_too_large", "topic":topic}),
              file=sys.stderr, flush=True)
        return
    try:
        model = PointTelemetry.model_validate_json(payload)
    except ValidationError as exc:
        error = exc.errors(include_input=False, include_context=False, include_url=False)[0]
        print(json.dumps({"event":"telemetry_rejected", "code":"invalid_payload", "topic":topic,
                          "field":list(error["loc"]), "received_at":received_at.isoformat()}),
              file=sys.stderr, flush=True)
        return
    try:
        result = store(model, topic=topic, received_at=received_at)
    except DeviceConfigurationError as exc:
        print(json.dumps({"event":"telemetry_rejected", "code":"source_mapping_error", "topic":topic,
                          "message_id":model.message_id, "reason":str(exc)}), file=sys.stderr, flush=True)
        return
    event = {"stored":"telemetry_stored", "duplicate":"telemetry_duplicate",
             "conflict":"telemetry_conflict", "unmapped":"telemetry_unmapped"}[result]
    print(json.dumps({"event":event, "topic":topic, "message_id":model.message_id,
                      "source_device_id":model.device_id, "source_gateway_id":model.gateway_id,
                      "received_at":received_at.isoformat()}),
          file=sys.stderr if result in ("conflict", "unmapped") else sys.stdout, flush=True)
