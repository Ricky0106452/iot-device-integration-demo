"""接收端獨立的 v2 訊息契約；不匯入 Gateway 的採集設定或解碼器。"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]


def utc_time(value):
    if not isinstance(value, (str, datetime)):
        raise ValueError("時間必須是帶時區的 ISO 時間")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    except ValueError as exc:
        raise ValueError("不是有效時間") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("時間必須包含時區")
    return result.astimezone(timezone.utc)


def decimal_string(value):
    if not isinstance(value, str) or len(value) > 800:
        raise ValueError("v2 讀值必須為十進位字串")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("不是合法數值") from exc
    if not number.is_finite():
        raise ValueError("讀值必須為有限數值")
    return number


UtcTime = Annotated[datetime, BeforeValidator(utc_time)]
PointValue = Annotated[Decimal, BeforeValidator(decimal_string), Field(max_digits=750, decimal_places=350)]


class PointValueMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: Identifier
    unit: str = Field(max_length=32)
    acquired_at: UtcTime
    value: PointValue


class PointTelemetry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[2]
    message_id: str
    gateway_id: Identifier
    device_id: Identifier
    acquired_at: UtcTime
    readings: list[PointValueMessage] = Field(min_length=1, max_length=1000)

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version 必須為整數")
        return value

    @field_validator("message_id")
    @classmethod
    def canonical_uuid(cls, value):
        identifier = UUID(value)
        if identifier.version != 4 or str(identifier) != value:
            raise ValueError("message_id 必須為標準小寫 UUID4")
        return value

    @model_validator(mode="after")
    def unique_codes(self):
        codes = [reading.code for reading in self.readings]
        if len(codes) != len(set(codes)):
            raise ValueError("訊息不可有重複點位代碼")
        return self

    def canonical_content(self) -> dict:
        # 排序、時間正規化與十進位表示不影響相同訊息的判定。
        def number(value):
            result = format(value, "f")
            if "." in result:
                result = result.rstrip("0").rstrip(".")
            return "0" if value == 0 else result
        return {"schema_version": 2, "message_id": self.message_id,
                "gateway_id": self.gateway_id, "device_id": self.device_id,
                "acquired_at": self.acquired_at.isoformat(),
                "readings": [{"code": value.code, "unit": value.unit,
                              "acquired_at": value.acquired_at.isoformat(), "value": number(value.value)}
                             for value in sorted(self.readings, key=lambda item: item.code)]}
