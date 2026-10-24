"""持續提供 Modbus 服務的模擬電表。"""
import argparse
import asyncio
import json
import logging
import math
from time import monotonic

from pymodbus.constants import ExcCodes
from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice

from simulator.meter import PowerMeter


async def update_meter(meter, interval):
    previous = monotonic()
    while True:
        await asyncio.sleep(interval)
        now = monotonic()
        meter.advance(now - previous)
        previous = now
        print(json.dumps({"event": "simulator_updated", "raw_registers": meter.registers}), flush=True)


async def serve(args):
    meter = PowerMeter()

    async def holding_reads_only(function_code, start_address, address, count,
                                 current_registers, set_values):
        if function_code != 3:
            return ExcCodes.ILLEGAL_FUNCTION
        # 定時工作獨立更新量測；讀取時將最新完整快照交給 PyModbus。
        # 此處沒有 await，因此與更新工作不會交錯修改同一份回覆。
        current_registers[:5] = meter.registers
        return None

    measurements = SimData(address=0, values=meter.registers,
                           datatype=DataType.REGISTERS, readonly=True)
    device = SimDevice(id=args.device_id, simdata=[measurements], action=holding_reads_only)
    server = ModbusTcpServer(context=device, address=(args.host, args.port))
    mode = "fixed" if args.fixed else f"update every {args.interval:g}s"
    print(f"Meter: {args.host}:{args.port}, device_id={args.device_id}; {mode}; "
          "holding registers 0..4; Ctrl+C to stop", flush=True)
    try:
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(server.serve_forever())
            if not args.fixed:
                tasks.create_task(update_meter(meter, args.interval))
    finally:
        await server.shutdown()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Simulated power meter")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1502)
    parser.add_argument("--device-id", type=int, default=1)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--fixed", action="store_true", help="Keep the initial measurement unchanged")
    args = parser.parse_args(argv)
    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error("--interval must be finite and greater than zero")
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
