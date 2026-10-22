"""Fixed measurement-block contract for SIM-POWER-01 (docs/DEVICE_SPEC.md).

Changing the device layout requires reviewing the decoder and its tests too;
changing the register count alone does not add support for another model.
"""

MEASUREMENT_START_ADDRESS = 0
MEASUREMENT_REGISTER_COUNT = 5
