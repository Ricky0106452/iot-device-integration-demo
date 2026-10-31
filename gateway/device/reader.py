"""依通道與點位設定讀取設備；共用串列通道由單一採集排程循序使用。"""
from datetime import datetime, timezone
import json
import sys

from pymodbus.client import ModbusSerialClient, ModbusTcpClient
from pymodbus.exceptions import ModbusException
from serial import SerialException

from gateway.config import DeviceSettings, RtuChannel, TcpChannel
from gateway.device.decoding import decode_point


def create_client(channel: TcpChannel | RtuChannel):
    if isinstance(channel, TcpChannel):
        return ModbusTcpClient(channel.host, port=channel.port,
                               timeout=channel.timeout_seconds, retries=0)
    return ModbusSerialClient(channel.serial_port, baudrate=channel.baudrate,
                              bytesize=channel.bytesize, parity=channel.parity,
                              stopbits=channel.stopbits, timeout=channel.timeout_seconds, retries=0)


def report_failure(code: str, detail: str, *, device_id: str, point_code: str | None = None):
    print(json.dumps({"event": "acquisition_failed", "code": code, "detail": detail,
                      "device_id": device_id, "point_code": point_code,
                      "attempt_finished_at": datetime.now(timezone.utc).isoformat()}),
          file=sys.stderr, flush=True)


def read_device(client, device: DeviceSettings) -> list[dict]:
    """每個點位分次讀取並標記時間；失敗不補零，其餘成功點位仍可送出。

    client 由呼叫端依通道建立，採集完成後關閉，但保留物件供下輪重連。
    """
    readings = []
    try:
        try:
            connected = client.connect()
        except (OSError, SerialException, ModbusException) as exc:
            report_failure("connection_failed", str(exc), device_id=device.device_id)
            return readings
        if not connected:
            report_failure("connection_failed", "無法連線到設備", device_id=device.device_id)
            return readings
        for point in device.points:
            try:
                read = (client.read_holding_registers if point.register_type == "holding"
                        else client.read_input_registers)
                result = read(point.address, count=point.register_count, device_id=device.unit_id)
                acquired_at = datetime.now(timezone.utc).isoformat()
                if result.isError():
                    report_failure("modbus_exception", str(result),
                                   device_id=device.device_id, point_code=point.code)
                    continue
                value = decode_point(result.registers, point)
                readings.append({"code": point.code, "unit": point.unit,
                                 "acquired_at": acquired_at, "value": format(value, "f")})
            except (OSError, SerialException, ModbusException, ValueError) as exc:
                report_failure("point_read_failed", str(exc),
                               device_id=device.device_id, point_code=point.code)
        return readings
    finally:
        client.close()
