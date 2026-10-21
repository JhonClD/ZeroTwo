"""Pruebas del formato de progreso y de la información de archivo."""

import tempfile
import unittest
from pathlib import Path

from utils.transfer_status import (
    TransferProgress,
    format_bytes,
    format_duration,
    format_file_info,
    parse_bytes,
    progress_bar,
    render_transfer_status,
)


class TransferStatusTests(unittest.TestCase):
    def test_formats_bytes_and_duration(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_duration(65), "01:05")
        self.assertEqual(format_duration(3661), "1:01:01")
        self.assertEqual(format_duration(None), "—")

    def test_progress_bar_clamps_percent(self):
        self.assertEqual(progress_bar(-5, 4), "░░░░")
        self.assertEqual(progress_bar(100, 4), "▓▓▓▓")

    def test_parses_binary_and_decimal_style_engine_units(self):
        self.assertEqual(parse_bytes("2.5 MiB"), int(2.5 * 1024 * 1024))
        self.assertEqual(parse_bytes("3 MB"), 3 * 1024 * 1024)
        self.assertEqual(parse_bytes("4K"), 4096)

    def test_transfer_card_includes_bytes_speed_eta_and_escaped_name(self):
        ticks = iter([0.0, 2.0])
        tracker = TransferProgress(clock=lambda: next(ticks))
        render_transfer_status("Descargando", "GoFile", "<video>.mkv", 0, 2048, tracker)
        card = render_transfer_status("Descargando", "GoFile", "<video>.mkv", 1024, 2048, tracker)
        self.assertIn("&lt;video&gt;.mkv", card)
        self.assertIn("1.0 KB / 2.0 KB · 50%", card)
        self.assertIn("512 B/s", card)
        self.assertIn("00:02", card)

    def test_explicit_engine_speed_is_rendered(self):
        card = render_transfer_status(
            "Descargando", "MEGA", "video.mkv", 512, 2048,
            TransferProgress(), speed_override=512,
        )
        self.assertIn("512 B/s", card)
        self.assertIn("00:03", card)

    def test_unknown_total_is_explained(self):
        card = render_transfer_status("Subiendo", "Telegram", "archivo.bin", 25, 0, TransferProgress())
        self.assertIn("25 B transferidos", card)
        self.assertIn("tamaño total desconocido", card)

    def test_file_info_includes_type_size_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "<clip>.mp4"
            path.write_bytes(b"1234")
            info = format_file_info(path, "Google Drive")
        self.assertIn("&lt;clip&gt;.mp4", info)
        self.assertIn("MP4", info)
        self.assertIn("4 B", info)
        self.assertIn("Google Drive", info)


if __name__ == "__main__":
    unittest.main()
