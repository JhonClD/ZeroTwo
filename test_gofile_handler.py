"""Pruebas de integración del selector y descarga GoFile en url_handler."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from handlers import url_handler


class FakeApp:
    def __init__(self):
        self.message_handler = None
        self.callback_handlers = []

    def on_message(self, *args, **kwargs):
        def decorator(function):
            self.message_handler = function
            return function
        return decorator

    def on_callback_query(self, *args, **kwargs):
        def decorator(function):
            self.callback_handlers.append(function)
            return function
        return decorator


class FakeStatusMessage:
    def __init__(self):
        self.edits = []
        self.deleted = False

    async def edit_text(self, *args, **kwargs):
        self.edits.append((args, kwargs))

    async def delete(self):
        self.deleted = True


class FakeIncomingMessage:
    def __init__(self):
        self.text = "https://gofile.io/d/Ab12Cd34"
        self.from_user = SimpleNamespace(id=7856571519, username="tester", first_name="Tester")
        self.status = FakeStatusMessage()
        self.documents = []

    async def reply_text(self, *args, **kwargs):
        return self.status

    async def reply_document(self, **kwargs):
        self.documents.append(kwargs)


class GoFileHandlerTests(unittest.TestCase):
    def test_folder_link_shows_one_button_per_file_without_downloading(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as temporary:
                app = FakeApp()
                url_handler.register(app, Path(temporary))
                message = FakeIncomingMessage()
                share = {
                    "content_id": "Ab12Cd34",
                    "files": [
                        {"id": "file-1", "name": "episode1.mkv", "size": 1024, "link": "https://store-1.gofile.io/a"},
                        {"id": "file-2", "name": "episode2.mkv", "size": 2048, "link": "https://store-1.gofile.io/b"},
                    ],
                }
                with patch.object(url_handler.GoFileDownloader, "list_shared_files", return_value=share), patch.object(
                    url_handler.GoFileDownloader, "download_file"
                ) as mock_download:
                    await app.message_handler(None, message)

                markup = message.status.edits[-1][1]["reply_markup"]
                self.assertEqual(len(markup.inline_keyboard), 2)
                self.assertTrue(markup.inline_keyboard[0][0].callback_data.startswith("gf:7856571519:"))
                self.assertLessEqual(len(markup.inline_keyboard[0][0].callback_data.encode()), 64)
                mock_download.assert_not_called()

        asyncio.run(run_test())

    def test_single_file_share_downloads_and_sends_automatically(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as temporary:
                app = FakeApp()
                url_handler.register(app, Path(temporary))
                message = FakeIncomingMessage()
                entry = {
                    "id": "file-1",
                    "name": "episode.mkv",
                    "size": 9,
                    "link": "https://store-1.gofile.io/download/web/file-id/episode.mkv",
                }
                share = {"content_id": "Ab12Cd34", "files": [entry]}

                def fake_download(selected, destination, max_bytes, progress, content_id):
                    path = Path(destination)
                    path.write_bytes(b"123456789")
                    return path, 9

                with patch.object(url_handler.GoFileDownloader, "list_shared_files", return_value=share), patch.object(
                    url_handler.GoFileDownloader, "download_file", side_effect=fake_download
                ) as mock_download:
                    await app.message_handler(None, message)

                self.assertEqual(len(message.documents), 1)
                self.assertIn("episode.mkv", message.documents[0]["caption"])
                self.assertTrue(message.status.deleted)
                self.assertEqual(mock_download.call_args.args[0], entry)
                self.assertFalse(any("No encontré archivos" in str(edit) for edit in message.status.edits))

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
