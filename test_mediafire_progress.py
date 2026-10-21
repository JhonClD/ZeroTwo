"""Pruebas de progreso en la descarga por requests de MediaFire."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from downloaders.mediafire_downloader import MediaFireDownloader


class FakeResponse:
    status_code = 200
    headers = {"Content-Type": "application/octet-stream", "Content-Length": "6"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        yield b"abc"
        yield b"def"


class MediaFireProgressTests(unittest.TestCase):
    def test_requests_fallback_reports_transfer_card_and_file_size(self):
        async def run_test():
            with tempfile.TemporaryDirectory() as temporary:
                statuses = []

                async def progress(text):
                    statuses.append(text)

                with patch.object(
                    MediaFireDownloader,
                    "get_direct_link",
                    new=AsyncMock(return_value=("https://download.example/file", "sample.bin")),
                ), patch("downloaders.mediafire_downloader.shutil.which", return_value=None), patch(
                    "downloaders.mediafire_downloader.requests.get", return_value=FakeResponse()
                ):
                    ok, path, error = await MediaFireDownloader.download(
                        "https://www.mediafire.com/file/example", Path(temporary), progress,
                    )

                self.assertTrue(ok)
                self.assertIsNone(error)
                self.assertEqual(path.read_bytes(), b"abcdef")
                self.assertTrue(any("MediaFire" in status and "sample.bin" in status for status in statuses))
                self.assertTrue(any("Descarga completada" in status for status in statuses))

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
