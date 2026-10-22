"""Decode the fixed SIM-POWER-01 layout from docs/DEVICE_SPEC.md."""
from dataclasses import dataclass

from gateway.device_spec import MEASUREMENT_REGISTER_COUNT


@dataclass(frozen=True)
class Measurement:
    voltage_v: float
    current_a: float
    power_w: int
    energy_wh: int


def decode_measurement(registers: list[int]) -> Measurement:
    if len(registers) != MEASUREMENT_REGISTER_COUNT:
        raise ValueError(
            f"Expected {MEASUREMENT_REGISTER_COUNT} registers, received {len(registers)}"
        )
    if any(type(word) is not int or not 0 <= word <= 65535 for word in registers):
        raise ValueError("Each register must be an unsigned 16-bit integer")

    voltage_raw, current_raw, power_raw, energy_high, energy_low = registers

    return Measurement(
        voltage_v=voltage_raw / 10,
        current_a=current_raw / 100,
        power_w=power_raw,
        energy_wh=energy_high * 65536 + energy_low,
    )
