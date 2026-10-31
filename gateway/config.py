"""JSON 為唯一設定來源；啟動前驗證所有通道、設備、點位與 MQTT 設定。"""
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from gateway.device.spec import Identifier, PointSpec

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "appsettings.json"
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
PositiveSeconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class TcpChannel(SettingsModel):
    channel_id: Identifier
    protocol: Literal["modbus_tcp"]
    host: NonEmptyText
    port: int = Field(default=502, ge=1, le=65535)
    timeout_seconds: PositiveSeconds = 1.0


class RtuChannel(SettingsModel):
    channel_id: Identifier
    protocol: Literal["modbus_rtu"]
    serial_port: NonEmptyText
    baudrate: int = Field(default=9600, gt=0)
    bytesize: Literal[8] = 8
    parity: Literal["N", "E", "O"] = "E"
    stopbits: Literal[1, 2] = 1
    timeout_seconds: PositiveSeconds = 1.0

    @field_validator("bytesize", "stopbits", mode="before")
    @classmethod
    def require_integer_serial_parameters(cls, value):
        if type(value) is not int:
            raise ValueError("串列資料位元與停止位元必須是整數")
        return value


Channel = Annotated[TcpChannel | RtuChannel, Field(discriminator="protocol")]


class DeviceSettings(SettingsModel):
    device_id: Identifier
    channel_id: Identifier
    unit_id: int = Field(ge=1, le=247)
    interval_seconds: PositiveSeconds = 5.0
    points: list[PointSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_point_codes(self):
        codes = [point.code for point in self.points]
        if len(codes) != len(set(codes)):
            raise ValueError("同一設備不可有重複點位代碼")
        return self


class MqttSettings(SettingsModel):
    host: NonEmptyText
    port: int = Field(default=1883, ge=1, le=65535)
    timeout_seconds: PositiveSeconds = Field(default=5.0, le=5)
    topic_prefix: str = "okgo/demo/v2"
    username: str | None = None
    password: str | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def validate_topic_and_credentials(self):
        prefix = self.topic_prefix
        if (not prefix or prefix.startswith("/") or prefix.endswith("/")
                or any(char in prefix for char in ("+", "#", "\x00"))):
            raise ValueError("topic_prefix 必須為不含萬用字元的 MQTT Topic 前綴")
        if len((prefix + "/devices/" + "x" * 64 + "/telemetry").encode("utf-8")) > 65535:
            raise ValueError("MQTT Topic 過長")
        if prefix == "okgo/demo/v1":
            raise ValueError("v2 點位訊息不能送入既有電表 v1 Topic")
        if self.password is not None and not self.username:
            raise ValueError("設定 MQTT password 時也必須設定 username")
        return self


class BufferSettings(SettingsModel):
    path: str = Field(min_length=1)
    max_pending: int = Field(default=10000, gt=0)
    retry_interval_seconds: PositiveSeconds = 5.0

    @model_validator(mode="after")
    def require_disk(self):
        if self.path == ":memory:":
            raise ValueError("待送佇列必須使用磁碟檔案")
        return self


class GatewaySettings(SettingsModel):
    gateway_id: Identifier
    mqtt: MqttSettings
    buffer: BufferSettings
    channels: list[Channel] = Field(min_length=1)
    devices: list[DeviceSettings] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self):
        channel_ids = [channel.channel_id for channel in self.channels]
        if len(channel_ids) != len(set(channel_ids)):
            raise ValueError("channel_id 不可重複")
        device_ids = [device.device_id for device in self.devices]
        if len(device_ids) != len(set(device_ids)):
            raise ValueError("device_id 不可重複")
        endpoints = []
        for channel in self.channels:
            endpoint = ((channel.protocol, channel.host.lower(), channel.port)
                        if isinstance(channel, TcpChannel)
                        else (channel.protocol, channel.serial_port.casefold()))
            if endpoint in endpoints:
                raise ValueError("同一通訊位置應共用一個通道，不可重複定義")
            endpoints.append(endpoint)
        addresses = set()
        for device in self.devices:
            if device.channel_id not in channel_ids:
                raise ValueError(f"設備 {device.device_id} 引用了不存在的通道")
            address = (device.channel_id, device.unit_id)
            if address in addresses:
                raise ValueError("同一通道的 unit_id 不可重複，請合併該設備點位")
            addresses.add(address)
        return self


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 設定有重複欄位：{key}")
        result[key] = value
    return result


def load_settings(path=DEFAULT_CONFIG_PATH) -> GatewaySettings:
    source = Path(path).resolve()
    data = json.loads(source.read_text(encoding="utf-8-sig"), object_pairs_hook=reject_duplicate_keys)
    settings = GatewaySettings.model_validate(data)
    buffer_path = Path(settings.buffer.path)
    if not buffer_path.is_absolute():
        buffer_path = source.parent / buffer_path
    return settings.model_copy(update={
        "buffer": settings.buffer.model_copy(update={"path": str(buffer_path.resolve())})
    })
