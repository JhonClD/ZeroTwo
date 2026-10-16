"""Pruebas del guardado de portadas y del reenvío Pyrogram con miniatura."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from handlers.video_cover_handler import _send_video_by_file_id, register


class FakeApp:
    def __init__(self):
        self.handlers = {}

    def on_message(self, filter_, **kwargs):
        def decorator(function):
            self.handlers[function.__name__] = function
            return function
        return decorator


class FakeStatus:
    def __init__(self):
        self.edited = []
        self.deleted = False

    async def edit_text(self, text):
        self.edited.append(text)

    async def delete(self):
        self.deleted = True


class FakeMessage:
    def __init__(self, user_id=123, chat_id=456):
        self.from_user = type("User", (), {"id": user_id})()
        self.chat = type("Chat", (), {"id": chat_id})()
        self.photo = []
        self.video = None
        self.document = None
        self.caption = "caption example"
        self.caption_entities = None
        self.has_protected_content = False
        self.id = 789
        self.responses = []
        self.photos = []
        self.status = FakeStatus()

    async def reply_text(self, text):
        self.responses.append(text)
        return self.status

    async def reply_photo(self, photo, caption=None):
        self.photos.append((photo, caption))


class CoverStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zerotwo-cover-test-")
        self.work = Path(self.temp.name)
        self.app = FakeApp()
        register(self.app, self.work, "test-token")

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_save_show_delete_and_persistence(self):
        message = FakeMessage()
        # Pyrogram expone message.photo como Photo; Aiogram suele usar una lista.
        message.photo = type("Photo", (), {"file_id": "cover-file-id"})()
        await self.app.handlers["save_cover"](None, message)
        await self.app.handlers["save_cover"](None, message)
        self.assertEqual(message.responses, ["Cover/Thumbnail Saved Successfully ✅"])
        db = self.work / "video_covers" / "covers.json"
        self.assertEqual(json.loads(db.read_text())["123"], "cover-file-id")

        new_app = FakeApp()
        register(new_app, self.work, "test-token")
        show_message = FakeMessage()
        await new_app.handlers["show_cover"](None, show_message)
        self.assertEqual(show_message.photos[0][0], "cover-file-id")

        await new_app.handlers["delete_cover"](None, FakeMessage())
        self.assertEqual(json.loads(db.read_text()), {})

    async def test_many_photos_keep_only_latest_cover(self):
        for message_id in range(110, 100, -1):
            message = FakeMessage()
            message.id = message_id
            message.photo = type("Photo", (), {"file_id": f"cover-{message_id}"})()
            await self.app.handlers["save_cover"](None, message)

        db = self.work / "video_covers" / "covers.json"
        self.assertEqual(json.loads(db.read_text())["123"], "cover-110")

    async def test_video_reuses_file_ids_without_downloading_or_reuploading(self):
        photo_message = FakeMessage()
        photo_message.photo = [type("Photo", (), {"file_id": "cover-file-id"})()]
        await self.app.handlers["save_cover"](None, photo_message)

        media = type("Video", (), {
            "file_id": "video-file-id", "file_size": 4_000_000,
            "file_name": "test.mp4", "duration": 12, "width": 640, "height": 360,
        })()
        message = FakeMessage()
        message.video = media
        payloads = []

        def fake_bot_api(token, payload):
            payloads.append((token, payload))
            return {"ok": True, "result": {"message_id": 1}}

        class NoDownloadClient:
            async def download_media(self, *args, **kwargs):
                raise AssertionError("El flujo video normal no debe descargar el video")

        with patch("handlers.video_cover_handler._send_video_by_file_id", side_effect=fake_bot_api):
            await self.app.handlers["add_cover"](NoDownloadClient(), message)
            await self.app.handlers["add_cover"](NoDownloadClient(), message)
        self.assertTrue(message.status.deleted)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0][0], "test-token")
        payload = payloads[0][1]
        self.assertEqual(payload["video"], "video-file-id")
        self.assertEqual(payload["cover"], "cover-file-id")
        self.assertEqual(payload["caption"], "caption example")
        self.assertEqual(payload["chat_id"], 456)

    async def test_bot_api_receives_only_file_ids(self):
        response = type("Response", (), {
            "__enter__": lambda self: self,
            "__exit__": lambda self, *args: None,
            "read": lambda self: b'{"ok":true,"result":{"message_id":9}}',
        })()
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = request.data.decode()
            captured["timeout"] = timeout
            return response

        with patch("handlers.video_cover_handler.urllib.request.urlopen", side_effect=fake_urlopen):
            result = _send_video_by_file_id("test-token", {
                "chat_id": 456, "video": "video-id", "cover": "cover-id",
            })
        self.assertTrue(result["ok"])
        self.assertTrue(captured["url"].endswith("/sendVideo"))
        from urllib.parse import parse_qs
        body = parse_qs(captured["body"])
        self.assertEqual(body["video"], ["video-id"])
        self.assertEqual(body["cover"], ["cover-id"])
        self.assertNotIn(b"video bytes", captured["body"].encode())

    async def test_thumoff_persists_and_thumon_reactivates(self):
        cover_message = FakeMessage()
        cover_message.photo = type("Photo", (), {"file_id": "cover-id"})()
        await self.app.handlers["save_cover"](None, cover_message)

        message = FakeMessage()
        await self.app.handlers["disable_cover"](None, message)
        settings = self.work / "video_covers" / "settings.json"
        self.assertEqual(json.loads(settings.read_text())["disabled_users"], ["123"])

        after_restart = FakeApp()
        register(after_restart, self.work, "test-token")
        video_message = FakeMessage()
        video_message.video = type("Video", (), {"file_id": "video-id"})()

        class NoDownloadClient:
            async def download_media(self, *args, **kwargs):
                raise AssertionError("Portadas desactivadas no deben procesar el video")

        with patch("handlers.video_cover_handler._send_video_by_file_id") as send_video:
            await after_restart.handlers["add_cover"](NoDownloadClient(), video_message)
            send_video.assert_not_called()

        new_photo = FakeMessage()
        new_photo.id = 790
        new_photo.photo = type("Photo", (), {"file_id": "new-cover-id"})()
        await after_restart.handlers["save_cover"](None, new_photo)
        self.assertEqual(new_photo.responses, ["Cover/Thumbnail Saved Successfully ✅"])

        enabled_message = FakeMessage()
        await after_restart.handlers["enable_cover"](None, enabled_message)
        self.assertEqual(json.loads(settings.read_text())["disabled_users"], [])
        self.assertIn("activadas", enabled_message.responses[0])


if __name__ == "__main__":
    unittest.main()
