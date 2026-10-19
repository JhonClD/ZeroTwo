"""Pruebas locales del downloader de GoFile; no realizan peticiones reales."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import downloaders.gofile_downloader as gofile_module
from downloaders.gofile_downloader import GoFileDownloader, GoFileDownloadError

SHARE_URL = "https://gofile.io/d/Ab12Cd34"
DIRECT_LINK = "https://store-1.gofile.io/download/web/file-id/video.mkv"


class FakeResponse:
    def __init__(self, data=None, body=(), headers=None, url=None, status_code=200):
        self._data = data
        self._body = list(body)
        self.headers = headers or {}
        self.url = url or DIRECT_LINK
        self.status_code = status_code
        self.closed = False

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1024):
        yield from self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True


class GoFileDownloaderTests(unittest.TestCase):
    @patch("downloaders.gofile_downloader.requests.post")
    def test_creates_and_reuses_anonymous_guest_token(self, mock_post):
        mock_post.return_value = FakeResponse(data={
            "status": "ok",
            "data": {"token": "anonymous-guest-token"},
        })
        with patch.object(gofile_module, "_guest_token", None):
            self.assertEqual(GoFileDownloader._get_guest_token(), "anonymous-guest-token")
            self.assertEqual(GoFileDownloader._get_guest_token(), "anonymous-guest-token")
        mock_post.assert_called_once()

    def test_accepts_only_gofile_file_share_urls(self):
        self.assertEqual(GoFileDownloader.parse_content_id(SHARE_URL), "Ab12Cd34")
        self.assertTrue(GoFileDownloader.is_gofile_url("https://www.gofile.io/d/Ab12Cd34?abc=1"))
        self.assertIsNone(GoFileDownloader.parse_content_id("https://gofile.io.evil.example/d/Ab12Cd34"))
        self.assertIsNone(GoFileDownloader.parse_content_id("https://example.com/d/Ab12Cd34"))
        self.assertIsNone(GoFileDownloader.parse_content_id("https://gofile.io/myfiles"))

    @patch("downloaders.gofile_downloader.time.time", return_value=14400 * 123)
    def test_website_token_uses_four_hour_bucket_and_expected_hash(self, _mock_time):
        raw = (
            f"{gofile_module._USER_AGENT}::{gofile_module._LANGUAGE}::guest::123::"
            f"{gofile_module._WT_SALT}"
        )
        self.assertEqual(GoFileDownloader.website_token("guest"), hashlib.sha256(raw.encode()).hexdigest())

    @patch("downloaders.gofile_downloader.requests.get")
    @patch.object(GoFileDownloader, "_get_guest_token", return_value="guest-token")
    def test_lists_a_single_public_file(self, _mock_token, mock_get):
        mock_get.return_value = FakeResponse(data={
            "status": "ok",
            "data": {
                "id": "file-id",
                "type": "file",
                "name": "episode.mkv",
                "size": 9,
                "link": DIRECT_LINK,
            },
        })
        result = GoFileDownloader.list_shared_files(SHARE_URL)
        self.assertEqual(result["content_id"], "Ab12Cd34")
        self.assertEqual(result["files"][0]["name"], "episode.mkv")
        self.assertEqual(result["files"][0]["size"], 9)
        self.assertEqual(result["files"][0]["link"], DIRECT_LINK)
        self.assertTrue(mock_get.call_args.kwargs["headers"]["Authorization"].startswith("Bearer "))
        self.assertIn("X-Website-Token", mock_get.call_args.kwargs["headers"])

    @patch("downloaders.gofile_downloader.time.sleep")
    @patch("downloaders.gofile_downloader.requests.get")
    @patch.object(GoFileDownloader, "_get_guest_token", return_value="guest-token")
    def test_retries_when_api_rate_limits(self, _mock_token, mock_get, mock_sleep):
        mock_get.side_effect = [
            FakeResponse(data={"status": "error-rateLimit"}, status_code=429),
            FakeResponse(data={"status": "ok", "data": {"type": "file"}}),
        ]
        payload = GoFileDownloader._fetch_content("Ab12Cd34")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    @patch("downloaders.gofile_downloader.requests.get")
    @patch.object(GoFileDownloader, "_get_guest_token", return_value="guest-token")
    def test_lists_files_inside_public_folder(self, _mock_token, mock_get):
        mock_get.return_value = FakeResponse(data={
            "status": "ok",
            "data": {
                "id": "folder-id",
                "type": "folder",
                "name": "Episodes",
                "children": {
                    "file-id": {
                        "id": "file-id",
                        "type": "file",
                        "name": "episode.mkv",
                        "size": 9,
                        "link": DIRECT_LINK,
                    }
                },
            },
            "metadata": {"totalPages": 1},
        })
        result = GoFileDownloader.list_shared_files(SHARE_URL)
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(result["files"][0]["id"], "file-id")
        self.assertEqual(result["files"][0]["name"], "episode.mkv")
        self.assertEqual(mock_get.call_count, 1)

    @patch("downloaders.gofile_downloader.requests.get")
    @patch.object(GoFileDownloader, "_get_guest_token", return_value="guest-token")
    def test_download_streams_to_part_then_renames(self, _mock_token, mock_get):
        response = FakeResponse(
            body=[b"1234", b"56789"],
            headers={"Content-Type": "video/x-matroska", "Content-Length": "9"},
        )
        mock_get.return_value = response
        entry = {"link": DIRECT_LINK, "size": 9}
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "episode.mkv"
            path, size = GoFileDownloader.download_file(entry, destination, max_bytes=100, content_id="Ab12Cd34")
            self.assertEqual(path, destination)
            self.assertEqual(size, 9)
            self.assertEqual(destination.read_bytes(), b"123456789")
            self.assertFalse(destination.with_name(destination.name + ".part").exists())
        self.assertTrue(response.closed)
        self.assertEqual(mock_get.call_args.kwargs["headers"]["Cookie"], "accountToken=guest-token")
        self.assertTrue(mock_get.call_args.kwargs["stream"])

    @patch("downloaders.gofile_downloader.requests.get")
    def test_rejects_file_over_limit_before_request(self, mock_get):
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(
            GoFileDownloadError, "supera el límite"
        ):
            GoFileDownloader.download_file(
                {"link": DIRECT_LINK, "size": 101}, Path(temporary) / "large.mkv", max_bytes=100
            )
        mock_get.assert_not_called()

    @patch("downloaders.gofile_downloader.requests.get")
    def test_rejects_untrusted_storage_host(self, mock_get):
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(
            GoFileDownloadError, "válido"
        ):
            GoFileDownloader.download_file(
                {"link": "https://evil.example/download", "size": 9},
                Path(temporary) / "bad.mkv",
                max_bytes=100,
            )
        mock_get.assert_not_called()

    @patch("downloaders.gofile_downloader.requests.get")
    @patch.object(GoFileDownloader, "_get_guest_token", return_value="guest-token")
    def test_rejects_html_response_and_removes_partial_file(self, _mock_token, mock_get):
        mock_get.return_value = FakeResponse(
            body=[b"<!doctype html><html>blocked</html>"],
            headers={"Content-Type": "text/html", "Content-Length": "36"},
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "blocked.mkv"
            with self.assertRaisesRegex(GoFileDownloadError, "página web"):
                GoFileDownloader.download_file(
                    {"link": DIRECT_LINK, "size": 0}, destination, max_bytes=100
                )
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name(destination.name + ".part").exists())


if __name__ == "__main__":
    unittest.main()
