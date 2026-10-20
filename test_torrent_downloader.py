"""Pruebas locales para la descarga de torrents desde enlaces directos."""

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
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


class FakeProcess:
    def __init__(self, output=""):
        self.stdout = io.StringIO(output)
        self.returncode = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


class TorrentDownloadTests(unittest.TestCase):
    def test_download_accepts_public_torrent_url_and_passes_local_file_to_aria2(self):
        async def unused():
            return None

        with tempfile.TemporaryDirectory() as temporary:
            torrent_bytes = b"d8:announce4: url4:infod4:name4:testee"
            response = FakeResponse(torrent_bytes, {"Content-Length": str(len(torrent_bytes))})
            progress = []

            def fake_popen(command, **kwargs):
                self.assertTrue(Path(command[-1]).is_file())
                self.assertEqual(Path(command[-1]).name, "source.torrent")
                (Path(temporary) / "episode.mkv").write_bytes(b"video")
                return FakeProcess("[#abc 512KiB/1MiB(50%) CN:4 DL:1MiB]\n")

            with patch("downloaders.torrent_downloader.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]), \
                 patch("downloaders.torrent_downloader.requests.get", return_value=response), \
                 patch.object(TorrentDownloader, "_aria2_binary", return_value="aria2c"), \
                 patch("downloaders.torrent_downloader.subprocess.Popen", side_effect=fake_popen):
                ok, files, error = TorrentDownloader.download(
                    "https://example.org/download/series.torrent", Path(temporary),
                    progress_callback=progress.append,
                )

            self.assertTrue(ok, error)
            self.assertEqual([path.name for path in files], ["episode.mkv"])
            self.assertTrue(response.closed)
            self.assertTrue(any(item["percent"] == 50 for item in progress))

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

    def test_magnet_uri_requires_a_torrent_identifier(self):
        magnet = "magnet:?xt=urn:btih:11570de06bb259af71aab6d2104f7321dee23&dn=Episode"
        self.assertTrue(torrent_handler._is_magnet_uri(magnet))
        self.assertFalse(torrent_handler._is_magnet_uri("magnet:?dn=Episode"))

    def test_torrent_command_accepts_magnet_as_argument(self):
        async def run_test():
            app = FakeApp()
            torrent_handler.register(app, Path("/tmp/downloads"))
            handler = app.handlers[-1][1]
            magnet = "magnet:?xt=urn:btih:11570de06bb259af71aab6d2104f7321dee23&dn=Episode"
            message = SimpleNamespace(
                text=f"/torrent {magnet}",
                from_user=SimpleNamespace(id=123),
                reply_to_message=None,
                reply_text=AsyncMock(),
            )
            with patch.object(torrent_handler, "_run_torrent", new_callable=AsyncMock) as run_torrent:
                await handler(None, message)
            run_torrent.assert_awaited_once_with(message, magnet, Path("/tmp/downloads"), "magnet")
            message.reply_text.assert_not_awaited()

        asyncio.run(run_test())

    def test_progress_template_contains_all_requested_fields(self):
        text = torrent_handler._torrent_status_text({
            "name": "Mi archivo.mkv",
            "completed_size": 1048576,
            "total_size": 10485760,
            "elapsed": 65,
            "percent": 10,
            "current_files": 1,
            "total_files": 10,
        })
        self.assertIn("Mi archivo.mkv", text)
        self.assertIn("Size:", text)
        self.assertIn("Elapsed:</b> 00:01:05", text)
        self.assertIn("Progreso:", text)
        self.assertIn("10%", text)
        self.assertIn("Total Files:</b> 1 / 10", text)

    def test_upload_template_contains_file_size_elapsed_and_progress(self):
        text = torrent_handler._upload_status_text(
            "S02E01 & S02E02.mkv", 5 * 1024 * 1024, 10 * 1024 * 1024, 65, "archivo 1/2"
        )
        self.assertIn("Enviando archivo a Telegram", text)
        self.assertIn("S02E01 &amp; S02E02.mkv", text)
        self.assertIn("5.0 MB / 10.0 MB", text)
        self.assertIn("Elapsed:</b> 00:01:05", text)
        self.assertIn(f"Progreso:</b> {torrent_handler._progress_bar(50)}", text)
        self.assertIn("50%", text)


if __name__ == "__main__":
    unittest.main()
