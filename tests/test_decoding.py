import unittest

from gateway.decoding import Measurement, decode_measurement


class DecodeMeasurementTests(unittest.TestCase):
    def test_known_snapshot(self):
        self.assertEqual(decode_measurement([2300, 1000, 2300, 1, 4464]),
                         Measurement(230.0, 10.0, 2300, 70000))

    def test_energy_word_boundary(self):
        for high, low, expected in [(0, 65535, 65535), (1, 0, 65536),
                                    (1, 4464, 70000), (65535, 65535, 4294967295)]:
            with self.subTest(high=high, low=low):
                self.assertEqual(decode_measurement([2300, 1000, 2300, high, low]).energy_wh,
                                 expected)

    def test_valid_zeros_and_nominal_values(self):
        self.assertEqual(decode_measurement([0, 0, 0, 0, 0]), Measurement(0, 0, 0, 0))
        self.assertEqual(decode_measurement([3000, 3000, 5000, 0, 0]).power_w, 5000)

    def test_preserves_values_above_nominal_range(self):
        for words, expected in [
            ([4300, 4000, 6000, 1, 4464], Measurement(430.0, 40.0, 6000, 70000)),
            ([65535, 65535, 65535, 0, 0], Measurement(6553.5, 655.35, 65535, 0)),
        ]:
            with self.subTest(words=words):
                self.assertEqual(decode_measurement(words), expected)

    def test_rejects_incomplete_or_oversized_block(self):
        for words in [[2300, 1000, 2300, 1], [2300, 1000, 2300, 1, 4464, 0]]:
            with self.subTest(words=words), self.assertRaisesRegex(
                ValueError, f"Expected 5 registers, received {len(words)}"
            ):
                decode_measurement(words)

    def test_rejects_invalid_words(self):
        for invalid in [-1, 65536, 1.5, True]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                decode_measurement([2300, 1000, 2300, 0, invalid])

if __name__ == "__main__":
    unittest.main()
