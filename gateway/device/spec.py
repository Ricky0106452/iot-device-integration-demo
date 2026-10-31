"""可設定的 Modbus 數值點位；位址一律採用從 0 開始的 PDU 位址。"""
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
FORMATS = {"uint16": "H", "int16": "h", "uint32": "I", "int32": "i",
           "uint64": "Q", "int64": "q", "float32": "f", "float64": "d"}
REGISTER_COUNTS = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2,
                   "uint64": 4, "int64": 4, "float32": 2, "float64": 4}


def parse_decimal(value):
    if type(value) not in (str, int, float, Decimal):
        raise ValueError("倍率與偏移量必須為數字或十進位字串")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("不是合法的十進位數字") from exc


DecimalSetting = Annotated[Decimal, BeforeValidator(parse_decimal),
                           Field(allow_inf_nan=False, max_digits=20, decimal_places=10)]


class PointSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    code: Identifier
    unit: str = Field(default="", max_length=32)
    register_type: Literal["holding", "input"] = "holding"
    address: int = Field(ge=0, le=65535)
    data_type: Literal["uint16", "int16", "uint32", "int32", "uint64", "int64", "float32", "float64"]
    byte_order: Literal["big", "little"] = "big"
    word_order: Literal["big", "little"] = "big"
    scale: DecimalSetting = Decimal("1")
    offset: DecimalSetting = Decimal("0")

    @property
    def register_count(self) -> int:
        return REGISTER_COUNTS[self.data_type]

    @model_validator(mode="after")
    def validate_register_span(self):
        if self.address + self.register_count > 65536:
            raise ValueError("點位所需暫存器超出 Modbus 位址範圍")
        if self.scale == 0:
            raise ValueError("scale 不得為零")
        return self
