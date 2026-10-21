"""Regresiones para el listado y la descarga de carpetas públicas de Drive."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from downloaders.drive_downloader import (
    DriveDownloader,
    DriveFolderError,
    _download_public_drive_file,
)


class FakeApiResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


class FakeDownloadResponse:
    def __init__(self, chunks, headers=None):
        self.chunks = chunks
        self.headers = headers or {"Content-Type": "application/octet-stream", "Content-Length": "1"}
        self.closed = False

    def iter_content(self, chunk_size):
        yield from self.chunks

    def close(self):
        self.closed = True


class DriveFolderTests(unittest.TestCase):
    def test_recognizes_folder_urls_but_not_file_urls(self):
        self.assertTrue(DriveDownloader.is_drive_folder_url(
            "https://drive.google.com/drive/folders/abcDEF_123456789?usp=sharing"
        ))
        self.assertTrue(DriveDownloader.is_drive_folder_url(
            "https://drive.google.com/drive/u/0/folders/abcDEF_123456789"
        ))
        self.assertFalse(DriveDownloader.is_drive_folder_url(
            "https://drive.google.com/file/d/abcDEF_123456789/view"
        ))

    def test_requires_api_key_only_for_folder_listing(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(DriveFolderError) as caught:
                DriveDownloader.list_public_folder_files("abcDEF_123456789")
        self.assertIn("GOOGLE_DRIVE_API_KEY", str(caught.exception))

    def test_lists_nested_files_and_omits_native_google_documents(self):
        responses = [
            FakeApiResponse({"id": "abcDEF_123456789", "name": "Anime", "mimeType": "application/vnd.google-apps.folder"}),
            FakeApiResponse({"files": [
                {"id": "file_123456789", "name": "ep1.mkv", "mimeType": "video/x-matroska", "size": "100"},
                {"id": "nested_123456789", "name": "Temporada 2", "mimeType": "application/vnd.google-apps.folder"},
                {"id": "doc_123456789", "name": "Notas", "mimeType": "application/vnd.google-apps.document"},
            ]}),
            FakeApiResponse({"files": [
                {"id": "file_223456789", "name": "ep2.mp4", "mimeType": "video/mp4", "size": "200"},
            ]}),
        ]

        def fake_get(url, **kwargs):
            return responses.pop(0)

        with patch("downloaders.drive_downloader.requests.get", side_effect=fake_get) as request:
            result = DriveDownloader.list_public_folder_files(
                "https://drive.google.com/drive/folders/abcDEF_123456789",
                api_key="test-api-key",
            )

        self.assertEqual(result["name"], "Anime")
        self.assertEqual([item["name"] for item in result["files"]], ["ep1.mkv", "ep2.mp4"])
        self.assertEqual(result["files"][1]["relative_path"], "Temporada 2/ep2.mp4")
        self.assertEqual(result["skipped_native"], 1)
        self.assertEqual(request.call_count, 3)
        for call in request.call_args_list:
            self.assertEqual(call.kwargs["params"]["key"], "test-api-key")

    def test_paginates_public_folder_listing(self):
        responses = [
            FakeApiResponse({"id": "abcDEF_123456789", "name": "Folder", "mimeType": "application/vnd.google-apps.folder"}),
            FakeApiResponse({"files": [{"id": "file_123456789", "name": "a.zip", "mimeType": "application/zip"}], "nextPageToken": "next-page"}),
            FakeApiResponse({"files": [{"id": "file_223456789", "name": "b.zip", "mimeType": "application/zip"}]}),
        ]
        with patch("downloaders.drive_downloader.requests.get", side_effect=lambda *args, **kwargs: responses.pop(0)):
            result = DriveDownloader.list_public_folder_files("abcDEF_123456789", api_key="key")
        self.assertEqual([item["name"] for item in result["files"]], ["a.zip", "b.zip"])

    def test_api_permission_error_does_not_echo_api_key(self):
        with patch(
            "downloaders.drive_downloader.requests.get",
            return_value=FakeApiResponse({"error": {"message": "API key not valid"}}, status=403),
        ):
            with self.assertRaises(DriveFolderError) as caught:
                DriveDownloader.list_public_folder_files("abcDEF_123456789", api_key="do-not-leak-this")
        self.assertNotIn("do-not-leak-this", str(caught.exception))
        self.assertIn("API key", str(caught.exception))

    def test_download_stream_enforces_limit_and_cleans_partial_file(self):
        response = FakeDownloadResponse([b"123456", b"7890"])
        with tempfile.TemporaryDirectory() as temporary:
            with patch("downloaders.drive_downloader._open_public_drive_response", return_value=response):
                with self.assertRaisesRegex(ValueError, "superó el límite"):
                    _download_public_drive_file("file_123456789", Path(temporary), max_bytes=8)
            self.assertTrue(response.closed)
            self.assertEqual(list(Path(temporary).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
