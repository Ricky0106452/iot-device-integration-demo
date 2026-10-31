"""依點位型別與 byte/word order 解碼；十進位倍率與偏移量不使用浮點運算。"""
from decimal import Decimal, localcontext
import math
import struct

from gateway.device.spec import FORMATS, PointSpec


def decode_point(registers: list[int], point: PointSpec) -> Decimal:
    if len(registers) != point.register_count:
        raise ValueError(f"預期 {point.register_count} 個暫存器，收到 {len(registers)} 個")
    if any(type(word) is not int or not 0 <= word <= 65535 for word in registers):
        raise ValueError("暫存器必須是 0..65535 的整數")
    words = registers if point.word_order == "big" else list(reversed(registers))
    chunks = [word.to_bytes(2, byteorder="big") for word in words]
    if point.byte_order == "little":
        chunks = [chunk[::-1] for chunk in chunks]
    value = struct.unpack(">" + FORMATS[point.data_type], b"".join(chunks))[0]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("不接受 NaN 或 Infinity 讀值")
    with localcontext() as context:
        context.prec = 50
        return Decimal(str(value)) * point.scale + point.offset
