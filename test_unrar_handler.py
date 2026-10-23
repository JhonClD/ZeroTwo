"""Pruebas para el formato y las salvaguardas del comando /unrar."""

import time
import unittest
from pathlib import Path

from handlers.unrar_handler import _error_reason, _extract_command, _status, register
from utils.rar_archives import safe_member_path
from utils.transfer_status import TransferProgress


class UnrarHandlerTests(unittest.TestCase):
    def test_password_listener_runs_before_global_text_handlers(self):
        class FakeApp:
            def __init__(self):
                self.handlers = []

            def on_message(self, message_filter, group=0):
                def add_handler(handler):
                    self.handlers.append((group, handler))
                    return handler
                return add_handler

        app = FakeApp()
        register(app, Path("downloads"))
        group = next(group for group, handler in app.handlers if handler.__name__ == "receive_password")
        self.assertLess(group, -3)

    def test_rejects_absolute_and_traversal_member_paths(self):
        for name in ("../outside.txt", "folder/../../outside.txt", "/tmp/out.txt", "C:\\Windows\\file.txt", "\\\\server\\share\\file.txt"):
            with self.subTest(name=name):
                self.assertFalse(safe_member_path(name))

    def test_accepts_regular_nested_member_paths(self):
        self.assertTrue(safe_member_path("folder/video.mkv"))
        self.assertTrue(safe_member_path("season 1\\episode 01.srt"))

    def test_progress_card_includes_requested_fields_and_escaped_name(self):
        card = _status(
            "<serie>.rar", 94 * 1024 * 1024, 245 * 1024 * 1024,
            5, 12, time.monotonic() - 5, TransferProgress(), "X5R9",
        )
        self.assertIn("&lt;serie&gt;.rar", card)
        self.assertIn("Size: 94.0 MiB / 245.0 MiB", card)
        self.assertIn("Files: 5 / 12", card)
        self.assertIn("Mode: #Extract | #RAR", card)
        self.assertIn("/cancel X5R9", card)

    def test_final_status_is_100_percent(self):
        card = _status(
            "archive.rar", 80, 100, 2, 2, time.monotonic(),
            TransferProgress(), "ABCD", "✓ Descomprimido",
        )
        self.assertIn("100.00%", card)
        self.assertIn("Status: ✓ Descomprimido", card)
        self.assertIn("Time:", card)

    def test_progress_supports_unknown_rar_metadata(self):
        card = _status(
            "encrypted.rar", 5 * 1024 * 1024, 0, 1, 0,
            time.monotonic(), TransferProgress(), "ABCD",
        )
        self.assertIn("5.0 MiB / desconocido", card)
        self.assertIn("Files: 1 / ?", card)

    def test_extractor_command_handles_password_without_shell(self):
        command = _extract_command("7z", Path("a.rar"), Path("out"), "p a$$")
        self.assertIn("-pp a$$", command)
        self.assertIn("a.rar", command)

    def test_unar_command_passes_password_and_output_directory(self):
        command = _extract_command("unar", Path("a.rar"), Path("out"), "archive-pass")
        self.assertEqual(command, ["unar", "-f", "-o", "out", "-p", "archive-pass", "a.rar"])

    def test_error_reason_distinguishes_password_space_and_corruption(self):
        self.assertEqual(_error_reason(2, "Wrong password"), "contraseña incorrecta")
        self.assertEqual(_error_reason(2, "No space left on device"), "sin espacio disponible")
        self.assertEqual(_error_reason(2, "CRC failed: archive corrupt"), "archivo corrupto o dañado")


if __name__ == "__main__":
    unittest.main()
