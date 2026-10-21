"""Pruebas del parseo de progreso de megatools."""

import unittest

from downloaders.mega_downloader import parse_megatools_progress


class MegaProgressTests(unittest.TestCase):
    def test_parses_percent_total_and_speed(self):
        parsed = parse_megatools_progress("45.23% of 234.50 MB, 3.20 MB/s")
        total = int(234.50 * 1024 * 1024)
        self.assertEqual(parsed, (45.23, int(total * 45.23 / 100), total, int(3.2 * 1024 * 1024)))

    def test_parses_progress_without_speed(self):
        parsed = parse_megatools_progress("50% of 2.00 GiB")
        self.assertEqual(parsed, (50.0, 1024 ** 3, 2 * 1024 ** 3, None))

    def test_ignores_non_progress_lines(self):
        self.assertIsNone(parse_megatools_progress("Connecting to mega.nz"))


if __name__ == "__main__":
    unittest.main()
