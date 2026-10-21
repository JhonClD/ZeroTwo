"""Pruebas de la lectura de estados de aria2 para torrents."""

import unittest

from downloaders.torrent_downloader import parse_aria2_progress


class TorrentProgressParsingTests(unittest.TestCase):
    def test_parses_current_total_and_speed_from_aria2_line(self):
        parsed = parse_aria2_progress(
            "[#a1b2c3 25.0MiB/100.0MiB(25%) CN:8 SD:0 DL:2.5MiB ETA:30s]"
        )
        self.assertEqual(parsed, (25 * 1024 * 1024, 100 * 1024 * 1024, int(2.5 * 1024 * 1024)))

    def test_ignores_lines_without_transfer_totals(self):
        self.assertIsNone(parse_aria2_progress("[#a1b2c3 GID#1 STATUS:ACTIVE]") )

    def test_parses_progress_without_speed(self):
        self.assertEqual(parse_aria2_progress("[#a1 50KiB/100KiB(50%)]"), (51200, 102400, None))


if __name__ == "__main__":
    unittest.main()
