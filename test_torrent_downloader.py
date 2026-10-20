"""Pruebas locales para la descarga de torrents desde enlaces directos."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from downloaders.torrent_downloader import TorrentDownloader
from handlers import torrent_handler


class FakeResponse:
    def __init__(self, content, headers=None, status=200):
        self.content = content
        self.headers = headers or {}
        self.status_code = status
        self.closed = False
        self.is_redirect = 300 <= status < 400
        self.is_permanent_redirect = status in {301, 308}

    def iter_content(self, chunk_size):
        yield self.content[:8]
        yield self.content[8:]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")

    def close(self):
        self.closed = True


class FakeApp:
    def __init__(self):
        self.handlers = []

    def on_message(self, *args, **kwargs):
        def decorator(function):
            self.handlers.append((kwargs.get("group", 0), function))
            return function
        return decorator


class TorrentDownloadTests(unittest.TestCase):
    def test_download_accepts_public_torrent_url_and_passes_local_file_to_aria2(self):
        async def unused():
            return None

        with tempfile.TemporaryDirectory() as temporary:
            torrent_bytes = b"d8:announce4: url4:infod4:name4:testee"
            response = FakeResponse(torrent_bytes, {"Content-Length": str(len(torrent_bytes))})
            completed = SimpleNamespace(returncode=0, stdout="", stderr="")

            def fake_run(command, **kwargs):
                self.assertTrue(Path(command[-1]).is_file())
                self.assertEqual(Path(command[-1]).name, "source.torrent")
                (Path(temporary) / "episode.mkv").write_bytes(b"video")
                return completed

            with patch("downloaders.torrent_downloader.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]), \
                 patch("downloaders.torrent_downloader.requests.get", return_value=response), \
                 patch.object(TorrentDownloader, "_aria2_binary", return_value="aria2c"), \
                 patch("downloaders.torrent_downloader.subprocess.run", side_effect=fake_run):
                ok, files, error = TorrentDownloader.download(
                    "https://example.org/download/series.torrent", Path(temporary)
                )

            self.assertTrue(ok, error)
            self.assertEqual([path.name for path in files], ["episode.mkv"])
            self.assertTrue(response.closed)

    def test_download_rejects_a_private_address(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch("downloaders.torrent_downloader.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
                ok, files, error = TorrentDownloader.download(
                    "https://localhost/data.torrent", Path(temporary)
                )
            self.assertFalse(ok)
            self.assertEqual(files, [])
            self.assertIn("servidor público", error)

    def test_direct_torrent_url_is_routed_to_torrent_handler(self):
        async def run_test():
            app = FakeApp()
            torrent_handler.register(app, Path("/tmp/downloads"))
            handler = next(function for group, function in app.handlers if group == 1)
            message = SimpleNamespace(
                text="https://nyaa.land/download/2176425.torrent",
                from_user=SimpleNamespace(id=123),
            )
            with patch.object(torrent_handler, "_run_torrent") as run_torrent:
                await handler(None, message)
            run_torrent.assert_awaited_once_with(
                message, message.text, Path("/tmp/downloads"), "enlace .torrent"
            )

        asyncio.run(run_test())

    def test_torrent_url_validator_rejects_non_torrent_paths(self):
        self.assertTrue(torrent_handler._is_torrent_url("https://example.org/a.torrent?download=1"))
        self.assertFalse(torrent_handler._is_torrent_url("https://example.org/view/2176425"))
        self.assertFalse(torrent_handler._is_torrent_url("file:///tmp/a.torrent"))


if __name__ == "__main__":
    unittest.main()
