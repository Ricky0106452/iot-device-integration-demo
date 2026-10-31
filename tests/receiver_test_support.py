"""接收端測試配置；刻意使用不同的來源與平台點位名稱。"""
from uuid import uuid4


def receiver_payload(database_url="postgresql+psycopg://unused/unused", suffix="test"):
    return {"receiver_id":"rx-"+suffix, "database_url":database_url,
        "mqtt":{"host":"127.0.0.1", "port":1883},
        "platform_devices":[{"device_id":"building-"+suffix, "name":"一樓",
            "points":[{"code":"temp1", "name":"一樓室溫", "unit":"degC", "resolution":"0.1"},
                      {"code":"temp-other", "name":"備用點位", "unit":"degC", "resolution":"0.1"}]}],
        "bindings":[{"topic":"factory/"+suffix+"/environment", "source_gateway_id":"gateway-001",
                     "source_device_id":"sensor-002", "source_code":"temp2",
                     "target_device_id":"building-"+suffix, "target_point_code":"temp1"}]}


def point_message():
    return {"schema_version":2, "message_id":str(uuid4()), "gateway_id":"gateway-001",
            "device_id":"sensor-002", "acquired_at":"2026-10-31T08:00:01Z",
            "readings":[{"code":"temp2", "unit":"degC", "acquired_at":"2026-10-31T08:00:00Z", "value":"26.5"}]}
