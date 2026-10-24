"""模擬量測的積分、編碼與週期更新驗證。"""
import asyncio
from contextlib import redirect_stdout
from decimal import Decimal
import io
import unittest
from unittest.mock import patch

from simulator.meter import PowerMeter
from simulator.server import main, update_meter


class PowerMeterTests(unittest.TestCase):
    def test_energy_integrates_previous_power_and_keeps_fraction(self):
        meter = PowerMeter()
        meter.advance(0.5)
        self.assertEqual(int(meter.energy_wh), 70000)
        previous_power = meter.registers[2]
        energy = meter.energy_wh
        meter.advance(9.5)
        self.assertEqual(meter.energy_wh, energy + Decimal(previous_power) * Decimal('9.5') / 3600)
        self.assertEqual(meter.registers[3] * 65536 + meter.registers[4], int(meter.energy_wh))

    def test_profile_changes_and_current_matches_power_voltage(self):
        meter = PowerMeter()
        initial = meter.registers.copy()
        meter.advance(5)
        self.assertNotEqual(meter.registers[:3], initial[:3])
        voltage, current, power, *_ = meter.registers
        self.assertEqual(current, round(power / (voltage / 10) * 100))
        for _ in range(200):
            meter.advance(5)
            self.assertTrue(2280 <= meter.registers[0] <= 2320)
            self.assertTrue(1800 <= meter.registers[2] <= 2800)
            self.assertTrue(all(0 <= value <= 65535 for value in meter.registers))

    def test_uint32_overflow_does_not_wrap_or_change_snapshot(self):
        meter = PowerMeter()
        meter.energy_wh = Decimal(2**32 - 1)
        before = meter.registers.copy()
        with self.assertRaises(OverflowError):
            meter.advance(10)
        self.assertEqual(meter.registers, before)
        self.assertEqual(meter.energy_wh, Decimal(2**32 - 1))

    def test_invalid_elapsed_does_not_change_state(self):
        for seconds in [-1, float('inf'), float('nan')]:
            meter = PowerMeter()
            with self.assertRaises(ValueError):
                meter.advance(seconds)
            self.assertEqual(meter.elapsed, 0)

    def test_invalid_interval_is_rejected(self):
        for value in ['0', '-1', 'nan', 'inf']:
            with self.subTest(value=value), redirect_stdout(io.StringIO()):
                with patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit) as exc:
                    main(['--interval', value])
                self.assertEqual(exc.exception.code, 2)


class TimerTests(unittest.IsolatedAsyncioTestCase):
    async def test_updates_without_client_and_uses_actual_elapsed_time(self):
        meter = PowerMeter()
        calls = 0

        async def wait(interval):
            nonlocal calls
            self.assertEqual(interval, 5)
            calls += 1
            if calls == 2:
                raise asyncio.CancelledError

        with patch('simulator.server.asyncio.sleep', side_effect=wait), \
             patch('simulator.server.monotonic', side_effect=[100, 107]), \
             redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(asyncio.CancelledError):
                await update_meter(meter, 5)
        self.assertEqual(meter.elapsed, 7)
        self.assertEqual(int(meter.energy_wh), 70004)
        self.assertIn('simulator_updated', output.getvalue())
