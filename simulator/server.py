"""Fixed-value Modbus device; run separately from the gateway."""
import argparse
import logging

from pymodbus.constants import ExcCodes
from pymodbus.server import StartTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice


async def holding_reads_only(function_code, start_address, address, count,
                             current_registers, set_values):
    """Expose only FC03 in this fixed-read step."""
    if function_code != 3:
        return ExcCodes.ILLEGAL_FUNCTION
    return None


def main():
    parser = argparse.ArgumentParser(description="Fixed-value simulated power meter")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1502)
    parser.add_argument("--device-id", type=int, default=1)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    # Raw words are intentionally independent of the gateway's decoder.
    measurements = SimData(
        address=0,
        values=[2300, 1000, 2300, 1, 4464],
        datatype=DataType.REGISTERS,
        readonly=True,
    )
    device = SimDevice(id=args.device_id, simdata=[measurements], action=holding_reads_only)
    print(
        f"Fixed meter: {args.host}:{args.port}, device_id={args.device_id}; "
        "holding registers 0..4; Ctrl+C to stop",
        flush=True,
    )
    StartTcpServer(context=device, address=(args.host, args.port))


if __name__ == "__main__":
    main()
