"""Pruebas de integración del selector de archivos Drime en url_handler."""
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
        self.callback_handler = None

    def on_message(self, *args, **kwargs):
        def decorator(function):
            self.message_handler = function
            return function
        return decorator

    def on_callback_query(self, *args, **kwargs):
        def decorator(function):
            self.callback_handler = function
            return function
        return decorator


class FakeStatusMessage:
    def __init__(self):
        self.edits = []

    async def edit_text(self, *args, **kwargs):
        self.edits.append((args, kwargs))

    async def delete(self):
        return None


class FakeIncomingMessage:
    def __init__(self):
        self.text = "https://app.drime.cloud/drive/s/yTElZV8zJSE9B37ejrQZHm1mznLHMG"
        self.from_user = SimpleNamespace(id=7856571519, username="tester", first_name="Tester")
        self.status = FakeStatusMessage()

    async def reply_text(self, *args, **kwargs):
        return self.status


class DrimeHandlerTests(unittest.TestCase):
    def test_shared_folder_shows_one_button_per_file_without_downloading(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as temporary:
                app = FakeApp()
                url_handler.register(app, Path(temporary))
                message = FakeIncomingMessage()
                share = {
                    "share_hash": "yTElZV8zJSE9B37ejrQZHm1mznLHMG",
                    "share_id": 175546,
                    "files": [
                        {"hash": "OTc3ODM4NTcwfA", "name": "ep2.mkv", "file_size": 1053500106},
                        {"hash": "OTYyNjczODg4fA", "name": "ep1.mkv", "file_size": 908011961},
                    ],
                }
                with patch.object(url_handler.DrimeDownloader, "list_shared_files", return_value=share):
                    await app.message_handler(None, message)

                markup = message.status.edits[-1][1]["reply_markup"]
                self.assertEqual(len(markup.inline_keyboard), 2)
                for row in markup.inline_keyboard:
                    self.assertEqual(len(row), 1)
                    button = row[0]
                    self.assertTrue(button.callback_data.startswith("d:7856571519:"))
                    self.assertLessEqual(len(button.callback_data.encode("utf-8")), 64)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
