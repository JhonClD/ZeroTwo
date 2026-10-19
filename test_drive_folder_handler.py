"""Pruebas del selector y botón de descarga total para carpetas de Drive."""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
        self.documents = []
        self.deleted = False

    async def edit_text(self, *args, **kwargs):
        self.edits.append((args, kwargs))

    async def delete(self):
        self.deleted = True

    async def reply_document(self, **kwargs):
        self.documents.append(kwargs)


class FakeIncomingMessage:
    def __init__(self, text):
        self.text = text
        self.from_user = SimpleNamespace(id=7856571519, username="tester", first_name="Tester")
        self.status = FakeStatusMessage()
        self.documents = []

    async def reply_text(self, *args, **kwargs):
        return self.status

    async def reply_document(self, **kwargs):
        self.documents.append(kwargs)

    async def reply_video(self, **kwargs):
        self.documents.append(kwargs)

    async def reply_audio(self, **kwargs):
        self.documents.append(kwargs)

    async def reply_photo(self, **kwargs):
        self.documents.append(kwargs)


class FakeCallbackQuery:
    def __init__(self, data, user, message):
        self.data = data
        self.from_user = user
        self.message = message
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append((text, kwargs))


class DriveFolderHandlerTests(unittest.TestCase):
    def test_folder_lists_files_and_has_download_all_button_even_for_one_file(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as temporary:
                app = FakeApp()
                url_handler.register(app, Path(temporary))
                message = FakeIncomingMessage("https://drive.google.com/drive/folders/abcDEF_123456789")
                folder = {
                    "name": "Temporada",
                    "truncated": False,
                    "skipped_native": 0,
                    "files": [{
                        "id": "file_123456789",
                        "name": "ep1.mp4",
                        "relative_path": "ep1.mp4",
                        "size": 1024,
                    }],
                }
                with patch.object(url_handler.DriveDownloader, "list_public_folder_files", return_value=folder), patch.object(
                    url_handler.DriveDownloader, "download", new_callable=AsyncMock
                ) as download:
                    await app.message_handler(None, message)

                markup = message.status.edits[-1][1]["reply_markup"]
                self.assertEqual(len(markup.inline_keyboard), 2)
                self.assertIn("ep1.mp4", markup.inline_keyboard[0][0].text)
                self.assertIn("Descargar todo (1)", markup.inline_keyboard[1][0].text)
                self.assertTrue(all(button[0].callback_data.startswith("gd:7856571519:") for button in markup.inline_keyboard))
                download.assert_not_called()

        asyncio.run(run_test())

    def test_download_all_callback_sends_each_file_in_sequence(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as temporary:
                app = FakeApp()
                url_handler.register(app, Path(temporary))
                message = FakeIncomingMessage("https://drive.google.com/drive/folders/abcDEF_123456789")
                folder = {
                    "name": "Temporada",
                    "truncated": False,
                    "skipped_native": 0,
                    "files": [
                        {"id": "file_123456789", "name": "ep1.mkv", "relative_path": "ep1.mkv", "size": 4},
                        {"id": "file_223456789", "name": "ep2.mkv", "relative_path": "ep2.mkv", "size": 5},
                    ],
                }
                with patch.object(url_handler.DriveDownloader, "list_public_folder_files", return_value=folder):
                    await app.message_handler(None, message)

                all_button = message.status.edits[-1][1]["reply_markup"].inline_keyboard[-1][0]
                query = FakeCallbackQuery(all_button.callback_data, message.from_user, message.status)
                names_by_id = {item["id"]: item["name"] for item in folder["files"]}
                downloaded_ids = []

                async def fake_download(file_id, output_dir, progress_callback=None, max_bytes=None):
                    downloaded_ids.append(file_id)
                    path = Path(output_dir) / names_by_id[file_id]
                    path.write_bytes(b"12345")
                    return True, path, None

                with patch.object(url_handler.DriveDownloader, "download", new=AsyncMock(side_effect=fake_download)) as download:
                    await app.callback_handlers[-1](None, query)

                self.assertEqual(downloaded_ids, ["file_123456789", "file_223456789"])
                self.assertEqual(len(message.status.documents), 2)
                self.assertIn("Enviados: 2/2", message.status.edits[-1][0][0])
                self.assertLessEqual(len(all_button.callback_data.encode("utf-8")), 64)
                self.assertTrue(query.answers)
                self.assertEqual(download.await_count, 2)

        asyncio.run(run_test())

    def test_individual_file_link_does_not_get_folder_buttons(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as temporary:
                app = FakeApp()
                url_handler.register(app, Path(temporary))
                message = FakeIncomingMessage("https://drive.google.com/file/d/fileID123456789/view")
                file_path = Path(temporary) / "file.pdf"
                file_path.write_bytes(b"pdf")
                with patch.object(
                    url_handler.DriveDownloader,
                    "download",
                    new=AsyncMock(return_value=(True, file_path, None)),
                ):
                    await app.message_handler(None, message)

                self.assertEqual(len(message.documents), 1)
                self.assertFalse(any("reply_markup" in kwargs for _, kwargs in message.status.edits))

        asyncio.run(run_test())

    def test_download_all_caps_actual_total_when_drive_omits_sizes(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as temporary, patch.dict(
                os.environ, {"ZERO_TWO_DRIVE_ALL_MAX_MB": "100"}
            ):
                app = FakeApp()
                url_handler.register(app, Path(temporary))
                message = FakeIncomingMessage("https://drive.google.com/drive/folders/abcDEF_123456789")
                folder = {
                    "name": "Folder",
                    "truncated": False,
                    "skipped_native": 0,
                    "files": [
                        {"id": "file_123456789", "name": "first.bin", "relative_path": "first.bin", "size": 0},
                        {"id": "file_223456789", "name": "second.bin", "relative_path": "second.bin", "size": 0},
                    ],
                }
                with patch.object(url_handler.DriveDownloader, "list_public_folder_files", return_value=folder):
                    await app.message_handler(None, message)

                all_button = message.status.edits[-1][1]["reply_markup"].inline_keyboard[-1][0]
                query = FakeCallbackQuery(all_button.callback_data, message.from_user, message.status)
                limits = []
                megabyte = 1024 * 1024

                async def fake_download(file_id, output_dir, progress_callback=None, max_bytes=None):
                    limits.append(max_bytes)
                    if len(limits) == 1:
                        path = Path(output_dir) / "first.bin"
                        with path.open("wb") as output:
                            output.truncate(60 * megabyte)
                        return True, path, None
                    return False, None, "excedió el límite restante"

                with patch.object(
                    url_handler.DriveDownloader, "download", new=AsyncMock(side_effect=fake_download)
                ):
                    await app.callback_handlers[-1](None, query)

                self.assertEqual(limits, [100 * megabyte, 40 * megabyte])
                self.assertEqual(len(message.status.documents), 1)
                self.assertIn("Enviados: 1/2", message.status.edits[-1][0][0])

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
