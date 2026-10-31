"""平台設備/點位與來源映射的接收端設定；不依賴 Gateway 設定檔。"""
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from receiver.point_models import Identifier, PointValue

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "receiver.appsettings.json"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def exact_topic(value):
    if (not value or len(value.encode("utf-8")) > 512
            or any(char in value for char in ("+", "#", "\x00"))):
        raise ValueError("來源 Topic 必須為 1..512 UTF-8 bytes 的完整 Topic，不接受萬用字元")
    return value


class PlatformPoint(Settings):
    code: Identifier
    name: str = Field(min_length=1, max_length=100)
    unit: str = Field(max_length=32)
    resolution: PointValue

    @field_validator("resolution")
    @classmethod
    def positive_resolution(cls, value):
        if value <= 0:
            raise ValueError("解析度必須大於零")
        return value


class PlatformDevice(Settings):
    device_id: Identifier
    name: str = Field(min_length=1, max_length=100)
    points: list[PlatformPoint] = Field(min_length=1)


class SourceBindingSettings(Settings):
    topic: str
    source_gateway_id: Identifier
    source_device_id: Identifier
    source_code: Identifier
    target_device_id: Identifier
    target_point_code: Identifier

    _topic = field_validator("topic")(exact_topic)


class MqttSettings(Settings):
    host: str = Field(min_length=1)
    port: int = Field(default=1883, ge=1, le=65535)
    timeout_seconds: float = Field(default=5.0, gt=0, le=5, allow_inf_nan=False)
    username: str | None = None
    password: str | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def credentials(self):
        if self.password is not None and not self.username:
            raise ValueError("password 需搭配 username")
        return self


class ReceiverSettings(Settings):
    receiver_id: Identifier
    database_url: str = Field(min_length=1, repr=False)
    mqtt: MqttSettings
    ready_file: str | None = None
    platform_devices: list[PlatformDevice] = Field(min_length=1)
    bindings: list[SourceBindingSettings] = Field(min_length=1)

    @property
    def topics(self):
        return tuple(sorted({binding.topic for binding in self.bindings}))

    @model_validator(mode="after")
    def validate_bindings(self):
        devices, targets = set(), set()
        for device in self.platform_devices:
            if device.device_id in devices:
                raise ValueError("平台設備 ID 不可重複")
            devices.add(device.device_id)
            for point in device.points:
                key = (device.device_id, point.code)
                if key in targets:
                    raise ValueError("平台點位不可重複")
                targets.add(key)
        sources, destinations = set(), set()
        for binding in self.bindings:
            target = (binding.target_device_id, binding.target_point_code)
            if target not in targets:
                raise ValueError("來源映射的目的點位未宣告")
            stream = (binding.topic, binding.source_gateway_id, binding.source_device_id)
            source = (*stream, binding.source_code)
            destination = (*stream, *target)
            if source in sources:
                raise ValueError("同一來源不可綁定兩次")
            if destination in destinations:
                raise ValueError("同一訊息來源的兩個 code 不可覆蓋同一平台點位")
            sources.add(source)
            destinations.add(destination)
        return self


def load_settings(path=DEFAULT_CONFIG_PATH):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("設定含重複欄位")
            result[key] = value
        return result
    return ReceiverSettings.model_validate(json.loads(
        Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys))
