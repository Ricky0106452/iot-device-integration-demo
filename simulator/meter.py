"""模擬電表的量測狀態，與 Modbus 通訊分開。"""
import math
from decimal import Decimal


class PowerMeter:
    def __init__(self):
        self.elapsed = 0.0
        self.energy_wh = Decimal(70000)
        self.registers = [2300, 1000, 2300, 1, 4464]

    def advance(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Elapsed seconds must be finite and non-negative")
        # 這段時間沿用上一份快照的功率；保留不足一 Wh 的餘量。
        energy = self.energy_wh + Decimal(self.registers[2]) * Decimal(str(seconds)) / 3600
        if energy >= Decimal(2**32):
            raise OverflowError("Energy exceeds UInt32 capacity")
        elapsed = self.elapsed + seconds
        voltage_raw = round(2300 + 20 * math.sin(elapsed / 30))
        power_w = round(2300 + 500 * math.sin(elapsed / 20))
        current_raw = round(power_w / (voltage_raw / 10) * 100)
        whole_wh = int(energy)
        # 整份替換，讀取端不會拿到跨更新時刻的兩個電量 word。
        self.registers = [voltage_raw, current_raw, power_w, whole_wh >> 16, whole_wh & 0xFFFF]
        self.energy_wh = energy
        self.elapsed = elapsed
