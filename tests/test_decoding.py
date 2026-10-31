"""測試整數、有號溫度、浮點數、字序與十進位換算。"""
from decimal import Decimal
import struct
import unittest

from gateway.device.decoding import decode_point
from gateway.device.spec import PointSpec


class DecodePointTests(unittest.TestCase):
    def point(self, data_type="uint16", **kwargs):
        return PointSpec(code="value", address=0, data_type=data_type, **kwargs)

    def test_unsigned_signed_and_64bit_boundaries(self):
        cases = [("uint16", [65535], "65535"), ("int16", [65535], "-1"),
                 ("uint32", [1, 4464], "70000"), ("int32", [65535, 65534], "-2"),
                 ("uint64", [65535] * 4, "18446744073709551615"),
                 ("int64", [65535] * 4, "-1")]
        for data_type, words, expected in cases:
            with self.subTest(data_type=data_type):
                self.assertEqual(decode_point(words, self.point(data_type)), Decimal(expected))

    def test_signed_temperature_scale_and_offset(self):
        self.assertEqual(decode_point([65413], self.point("int16", scale="0.1", offset="2")), Decimal("-10.3"))
        self.assertEqual(decode_point([3], self.point(scale="0.1")), Decimal("0.3"))

    def test_byte_and_word_orders(self):
        for words, byte_order, word_order in [
            ([0x1234, 0x5678], "big", "big"), ([0x5678, 0x1234], "big", "little"),
            ([0x3412, 0x7856], "little", "big"), ([0x7856, 0x3412], "little", "little")]:
            with self.subTest(byte_order=byte_order, word_order=word_order):
                self.assertEqual(decode_point(words, self.point("uint32", byte_order=byte_order,
                                                               word_order=word_order)), Decimal(0x12345678))

    def test_float32_and_float64(self):
        for data_type, fmt in [("float32", ">f"), ("float64", ">d")]:
            raw = struct.pack(fmt, -26.5)
            words = [int.from_bytes(raw[i:i+2], "big") for i in range(0, len(raw), 2)]
            self.assertEqual(decode_point(words, self.point(data_type)), Decimal("-26.5"))

    def test_rejects_nan_infinity_and_wrong_word_count(self):
        for words in [[0x7f80, 0], [0x7fc0, 0], [1], [1, 2, 3]]:
            with self.subTest(words=words), self.assertRaises(ValueError):
                decode_point(words, self.point("float32"))

    def test_rejects_nonregister_values(self):
        for word in [-1, 65536, True, 1.5, "1"]:
            with self.subTest(word=word), self.assertRaises(ValueError):
                decode_point([word], self.point())
