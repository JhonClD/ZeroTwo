"""Pruebas locales para la descarga de torrents desde enlaces directos."""

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit

from downloaders.torrent_downloader import TorrentDownloader, _torrent_file_entries
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
        self.callback_handler = None

    def on_message(self, *args, **kwargs):
        def decorator(function):
            self.handlers.append((kwargs.get("group", 0), function))
            return function
        return decorator

    def on_callback_query(self, *args, **kwargs):
        def decorator(function):
            self.callback_handler = function
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


class FakeCallbackQuery:
    def __init__(self, data, user_id=123):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = SimpleNamespace(edits=[])

        async def edit_text(*args, **kwargs):
            self.message.edits.append((args, kwargs))
        self.message.edit_text = edit_text
        self.answers = []

    async def answer(self, *args, **kwargs):
        self.answers.append((args, kwargs))


class TorrentDownloadTests(unittest.TestCase):
    @staticmethod
    def _bencode(value):
        if isinstance(value, int):
            return b"i" + str(value).encode() + b"e"
        if isinstance(value, bytes):
            return str(len(value)).encode() + b":" + value
        if isinstance(value, list):
            return b"l" + b"".join(TorrentDownloadTests._bencode(item) for item in value) + b"e"
        if isinstance(value, dict):
            pairs = sorted(value.items())
            return b"d" + b"".join(
                TorrentDownloadTests._bencode(key) + TorrentDownloadTests._bencode(item)
                for key, item in pairs
            ) + b"e"
        raise TypeError(value)

    def _write_multi_file_torrent(self, path):
        info = {
            b"name": b"Cyberpunk Edgerunners S02",
            b"files": [
                {b"length": 100, b"path": [b"S02E01.mkv"]},
                {b"length": 200, b"path": [b"S02E02.mkv"]},
                {b"length": 300, b"path": [b"S02E03.mkv"]},
            ],
        }
        path.write_bytes(self._bencode({b"info": info}))
        return path

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

    def test_torrent_file_list_matches_aria2_indices_and_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            torrent = self._write_multi_file_torrent(Path(temporary) / "episodes.torrent")
            entries = _torrent_file_entries(torrent)
            self.assertEqual([item["index"] for item in entries], [1, 2, 3])
            self.assertEqual(Path(entries[1]["name"]).name, "S02E02.mkv")
            self.assertEqual([item["size"] for item in entries], [100, 200, 300])

    def test_prepare_selection_reads_torrent_before_starting_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            torrent = self._write_multi_file_torrent(Path(temporary) / "episodes.torrent")
            ok, source, metainfo, entries, error = TorrentDownloader.prepare_selection(torrent, Path(temporary))
            self.assertTrue(ok, error)
            self.assertEqual(source, torrent)
            self.assertEqual(metainfo, torrent)
            self.assertEqual(len(entries), 3)

    def test_download_passes_only_selected_file_indices_to_aria2(self):
        with tempfile.TemporaryDirectory() as temporary:
            torrent = self._write_multi_file_torrent(Path(temporary) / "episodes.torrent")
            captured = {}

            def fake_popen(command, **kwargs):
                captured["command"] = command
                (Path(temporary) / "S02E02.mkv").write_bytes(b"episode")
                return FakeProcess()

            with patch.object(TorrentDownloader, "_aria2_binary", return_value="aria2c"), \
                 patch("downloaders.torrent_downloader.subprocess.Popen", side_effect=fake_popen):
                ok, files, error = TorrentDownloader.download(
                    torrent, Path(temporary), selected_files=[2], metadata_source=torrent
                )

            self.assertTrue(ok, error)
            self.assertIn("--select-file=2", captured["command"])
            self.assertEqual([path.name for path in files], ["S02E02.mkv"])

    def test_selector_shows_each_chapter_and_selection_actions(self):
        state = {
            "entries": [
                {"index": 1, "name": "Season/S02E01.mkv", "size": 100},
                {"index": 2, "name": "Season/S02E02.mkv", "size": 200},
            ],
            "page": 0,
            "selected": {2},
            "name": "Cyberpunk Edgerunners S02",
        }
        text, keyboard = torrent_handler._selection_view("0123456789", state)
        buttons = [button for row in keyboard.inline_keyboard for button in row]
        labels = [button.text for button in buttons]
        self.assertIn("☐ 01 · S02E01.mkv", labels)
        self.assertIn("☑ 02 · S02E02.mkv", labels)
        self.assertIn("⬇️ Descargar seleccionados (1)", labels)
        self.assertIn("Cyberpunk Edgerunners S02", text)

    def test_callback_toggles_chapter_for_owner(self):
        async def run_test():
            app = FakeApp()
            torrent_handler.register(app, Path("/tmp/downloads"))
            selection_id = "abcdef1234"
            state = {
                "owner_id": 123,
                "entries": [{"index": 1, "name": "S02E01.mkv", "size": 100}],
                "selected": set(),
                "page": 0,
                "name": "Season",
                "job_dir": Path("/tmp/not-used"),
            }
            torrent_handler._PENDING_TORRENT_SELECTIONS[selection_id] = state
            query = FakeCallbackQuery(f"tr:{selection_id}:t:1")
            try:
                await app.callback_handler(None, query)
                self.assertEqual(state["selected"], {1})
                self.assertTrue(query.message.edits)
                self.assertFalse(query.answers[-1][1].get("show_alert", False))
            finally:
                torrent_handler._PENDING_TORRENT_SELECTIONS.pop(selection_id, None)

        asyncio.run(run_test())

    def test_callback_downloads_only_the_checked_chapters(self):
        async def run_test():
            app = FakeApp()
            torrent_handler.register(app, Path("/tmp/downloads"))
            selection_id = "fedcba9876"
            state = {
                "owner_id": 123,
                "entries": [{"index": 1, "name": "S02E01.mkv", "size": 100}],
                "selected": {1},
                "page": 0,
                "name": "Season",
                "source_message": object(),
                "job_dir": Path("/tmp/not-used"),
                "source": "magnet:?xt=urn:btih:test",
                "metainfo_path": Path("/tmp/metadata.torrent"),
            }
            torrent_handler._PENDING_TORRENT_SELECTIONS[selection_id] = state
            query = FakeCallbackQuery(f"tr:{selection_id}:go")
            try:
                with patch.object(torrent_handler, "_download_torrent_selection", new_callable=AsyncMock) as download:
                    await app.callback_handler(None, query)
                download.assert_awaited_once_with(state["source_message"], query.message, state, [1])
                self.assertNotIn(selection_id, torrent_handler._PENDING_TORRENT_SELECTIONS)
            finally:
                torrent_handler._PENDING_TORRENT_SELECTIONS.pop(selection_id, None)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
