"""Pruebas del guardado de portadas y del reenvío Pyrogram con miniatura."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from handlers.video_cover_handler import register


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
        register(self.app, self.work)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_save_show_delete_and_persistence(self):
        message = FakeMessage()
        message.photo = [type("Photo", (), {"file_id": "cover-file-id"})()]
        await self.app.handlers["save_cover"](None, message)
        db = self.work / "video_covers" / "covers.json"
        self.assertEqual(json.loads(db.read_text())["123"], "cover-file-id")

        new_app = FakeApp()
        register(new_app, self.work)
        show_message = FakeMessage()
        await new_app.handlers["show_cover"](None, show_message)
        self.assertEqual(show_message.photos[0][0], "cover-file-id")

        await new_app.handlers["delete_cover"](None, FakeMessage())
        self.assertEqual(json.loads(db.read_text()), {})

    async def test_video_is_resent_with_normalized_thumb(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("FFmpeg no instalado")
        with tempfile.TemporaryDirectory(prefix="zerotwo-cover-assets-") as asset_dir:
            asset = Path(asset_dir)
            video = asset / "source.mp4"
            cover = asset / "cover.png"
            make_video = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=160x120:r=10", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
                capture_output=True, timeout=30,
            )
            self.assertEqual(make_video.returncode, 0, make_video.stderr.decode(errors="replace"))
            make_cover = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=640x480", "-frames:v", "1", str(cover)],
                capture_output=True, timeout=30,
            )
            self.assertEqual(make_cover.returncode, 0, make_cover.stderr.decode(errors="replace"))

            photo_message = FakeMessage()
            photo_message.photo = [type("Photo", (), {"file_id": "cover-file-id"})()]
            await self.app.handlers["save_cover"](None, photo_message)

            media = type("Video", (), {"file_size": video.stat().st_size, "file_name": "test.mp4", "duration": 1, "width": 160, "height": 120})()
            message = FakeMessage()
            message.video = media
            sent = {}

            class FakeClient:
                async def download_media(self, source, file_name):
                    from shutil import copyfile
                    origin = video if source is message else cover
                    target = Path(file_name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    copyfile(origin, target)
                    return str(target)

                async def send_video(self, **kwargs):
                    sent.update(kwargs)
                    sent["thumb_bytes"] = Path(kwargs["thumb"]).read_bytes()

            await self.app.handlers["add_cover"](FakeClient(), message)
            self.assertTrue(message.status.deleted)
            self.assertEqual(sent["caption"], "caption example")
            self.assertEqual(sent["thumb_bytes"][:2], b"\xff\xd8")
            self.assertLessEqual(len(sent["thumb_bytes"]), 200 * 1024)
            self.assertEqual(sent["duration"], 1)
            self.assertEqual(list((self.work / "video_covers").glob("cover_*/")), [])


if __name__ == "__main__":
    unittest.main()
