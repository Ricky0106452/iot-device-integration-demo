"""整合測試專用：兩台設備，點位位址 0/10 與 100/120，中間留空。"""
import asyncio
import sys

from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice


async def serve(port):
    def registers(address, values):
        return SimData(address=address, values=values, datatype=DataType.REGISTERS, readonly=True)
    devices = [
        SimDevice(id=1, simdata=[registers(0, [2300]), registers(10, [1000])]),
        SimDevice(id=2, simdata=[registers(100, [65413]), registers(120, [655, 0])]),
    ]
    server = ModbusTcpServer(context=devices, address=("127.0.0.1", port))
    try:
        await server.serve_forever()
    finally:
        await server.shutdown()


if __name__ == "__main__":
    asyncio.run(serve(int(sys.argv[1])))
