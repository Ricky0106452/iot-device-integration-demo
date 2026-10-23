"""MQTT 接收訊息的欄位與驗證規則。"""
from datetime import datetime
from decimal import Decimal
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


IDENTIFIER_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
UUID4_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
UTC_TIME_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$"
Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=IDENTIFIER_PATTERN)]
Register = Annotated[int, Field(ge=0, le=65535)]


class Measurement(BaseModel):
    """四項量測；上下限來自編碼能力，不是正常工作範圍。"""
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)

    voltage_v: float = Field(ge=0, le=6553.5, description="電壓 V，word0 / 10，解析度 0.1 V。",
                             json_schema_extra={"multipleOf": 0.1})
    current_a: float = Field(ge=0, le=655.35, description="電流 A，word1 / 100，解析度 0.01 A。",
                             json_schema_extra={"multipleOf": 0.01})
    power_w: int = Field(ge=0, le=65535, description="有功功率 W，word2。")
    energy_wh: int = Field(ge=0, le=4294967295, description="累積電量 Wh，word3 * 65536 + word4。")


    @field_validator("voltage_v", "current_a")
    @classmethod
    def require_device_resolution(cls, value: float, info) -> float:
        # 以十進位檢查刻度，不使用浮點餘數，也不替來源值四捨五入。
        step = Decimal("0.1") if info.field_name == "voltage_v" else Decimal("0.01")
        if Decimal(str(value)) % step != 0:
            raise ValueError(f"數值必須是設備解析度 {step} 的整數倍")
        return value


class Telemetry(BaseModel):
    """一筆 v1 量測；驗證欄位，不代表已核對 Topic 或完成持久儲存。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: Literal[1]
    message_id: str = Field(pattern=UUID4_PATTERN, json_schema_extra={"format": "uuid"})
    device_id: Identifier
    gateway_id: Identifier
    # 保留原字串以維持取得時間的表示方式；另檢查日期是否存在。
    acquired_at: str = Field(pattern=UTC_TIME_PATTERN, json_schema_extra={"format": "date-time"})
    raw_registers: list[Register] = Field(min_length=5, max_length=5)
    measurement: Measurement

    @field_validator("schema_version", mode="before")
    @classmethod
    def require_integer_version(cls, value):
        # Python 的 True == 1，不能只依 Literal[1] 判斷輸入型別。
        if type(value) is not int:
            raise ValueError("版本必須是整數，不接受布林或自動轉型")
        return value

    @field_validator("device_id", "gateway_id", "message_id", "acquired_at")
    @classmethod
    def require_full_string_match(cls, value: str, info) -> str:
        patterns = {"device_id": IDENTIFIER_PATTERN, "gateway_id": IDENTIFIER_PATTERN,
                    "message_id": UUID4_PATTERN, "acquired_at": UTC_TIME_PATTERN}
        if re.fullmatch(patterns[info.field_name], value) is None:
            raise ValueError("欄位必須完整符合格式，不允許結尾換行")
        if info.field_name == "acquired_at":
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
