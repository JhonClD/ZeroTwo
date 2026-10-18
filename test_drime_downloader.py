"""Pruebas locales del downloader de enlaces públicos de Drime."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from downloaders.drime_downloader import DrimeDownloader, DrimeDownloadError

SHARE_URL = "https://app.drime.cloud/drive/s/yTElZV8zJSE9B37ejrQZHm1mznLHMG"
SHARE_HASH = "yTElZV8zJSE9B37ejrQZHm1mznLHMG"
ENTRY_HASH = "OTc3ODM4NTcwfA"


def _listing(allow_download: bool = True):
    return {
        "status": "success",
        "link": {"id": 175546, "hash": SHARE_HASH, "allow_download": allow_download},
        "folderChildren": {
            "current_page": 1,
            "last_page": 1,
            "data": [{
                "id": 977838570,
                "hash": ENTRY_HASH,
                "name": "episode.mkv",
                "type": "video",
                "file_size": 9,
            }],
        },
    }


class FakeResponse:
    def __init__(self, status_code=200, data=None, body=None, headers=None):
        self.status_code = status_code
        self._data = data
        self._body = body or []
        self.headers = headers or {}
        self.closed = False

    def json(self):
        return self._data

    def iter_content(self, chunk_size=1024):
        yield from self._body

    def close(self):
        self.closed = True


class DrimeDownloaderTests(unittest.TestCase):
    def test_accepts_only_drime_public_share_urls(self):
        self.assertEqual(DrimeDownloader.share_hash(SHARE_URL), SHARE_HASH)
        self.assertTrue(DrimeDownloader.is_drime_url(SHARE_URL))
        self.assertIsNone(DrimeDownloader.share_hash("https://app.drime.cloud.evil.example/drive/s/abcdefgh"))
        self.assertIsNone(DrimeDownloader.share_hash("https://example.com/drive/s/abcdefgh"))
        self.assertIsNone(DrimeDownloader.share_hash("https://app.drime.cloud/account-settings"))

    @patch("downloaders.drime_downloader.requests.get")
    def test_lists_public_folder_entries_without_account_token(self, mock_get):
        mock_get.return_value = FakeResponse(data=_listing())
        result = DrimeDownloader.list_shared_files(SHARE_URL)
        self.assertEqual(result["share_hash"], SHARE_HASH)
        self.assertEqual(result["share_id"], 175546)
        self.assertEqual(result["files"][0]["hash"], ENTRY_HASH)
        self.assertNotIn("Authorization", mock_get.call_args.kwargs["headers"])

    @patch("downloaders.drime_downloader.requests.get")
    def test_refuses_shares_with_download_disabled(self, mock_get):
        mock_get.return_value = FakeResponse(data=_listing(allow_download=False))
        with self.assertRaisesRegex(DrimeDownloadError, "desactivó la descarga"):
            DrimeDownloader.list_shared_files(SHARE_URL)

    @patch("downloaders.drime_downloader.requests.get")
    def test_download_writes_stream_to_part_then_renames(self, mock_get):
        response = FakeResponse(
            body=[b"1234", b"56789"],
            headers={"Content-Type": "video/matroska", "Content-Length": "9"},
        )
        mock_get.return_value = response
        entry = {"hash": ENTRY_HASH, "file_size": 9}
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "episode.mkv"
            path, size = DrimeDownloader.download_file(
                SHARE_HASH, 175546, entry, destination, max_bytes=100,
            )
            self.assertEqual(path, destination)
            self.assertEqual(size, 9)
            self.assertEqual(destination.read_bytes(), b"123456789")
            self.assertFalse(destination.with_name(destination.name + ".part").exists())
        self.assertTrue(response.closed)
        self.assertEqual(mock_get.call_args.kwargs["params"], {"shareable_link": 175546, "password": "null"})
        self.assertTrue(mock_get.call_args.kwargs["stream"])
        self.assertTrue(mock_get.call_args.kwargs["allow_redirects"])

    @patch("downloaders.drime_downloader.requests.get")
    def test_rejects_file_larger_than_configured_limit_before_request(self, mock_get):
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(
            DrimeDownloadError, "supera el límite"
        ):
            DrimeDownloader.download_file(
                SHARE_HASH, 175546, {"hash": ENTRY_HASH, "file_size": 101},
                Path(temporary) / "large.mkv", max_bytes=100,
            )
        mock_get.assert_not_called()

    @patch("downloaders.drime_downloader.requests.get")
    def test_rejects_html_response_and_removes_partial_file(self, mock_get):
        mock_get.return_value = FakeResponse(
            body=[b"<!doctype html><html>blocked</html>"],
            headers={"Content-Type": "text/html", "Content-Length": "36"},
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "blocked.mkv"
            with self.assertRaisesRegex(DrimeDownloadError, "página web"):
                DrimeDownloader.download_file(
                    SHARE_HASH, 175546, {"hash": ENTRY_HASH, "file_size": 0},
                    destination, max_bytes=100,
                )
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name(destination.name + ".part").exists())


if __name__ == "__main__":
    unittest.main()
