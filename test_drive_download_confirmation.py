"""Pruebas sin red para la confirmación de descargas grandes de Drive."""
import unittest

from downloaders.drive_downloader import _open_public_drive_response


class FakeCookies(dict):
    def items(self):
        return super().items()


class FakeResponse:
    def __init__(self, content_type, text="", status=200, headers=None):
        self.status_code = status
        self.headers = headers or {"Content-Type": content_type}
        self.text = text
        self.url = "https://drive.usercontent.google.com/download?id=file-id&export=download"
        self.closed = False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("El estado debía convertirse en un error accionable")


class FakeSession:
    def __init__(self, responses):
        self.cookies = FakeCookies()
        self.responses = list(responses)
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.responses.pop(0)


class DriveDownloadConfirmationTests(unittest.TestCase):
    def test_large_file_form_sends_confirm_uuid_and_form_action(self):
        warning = FakeResponse(
            "text/html; charset=utf-8",
            '<form action="https://drive.usercontent.google.com/download">'
            '<input name="id" value="file-id">'
            '<input name="export" value="download">'
            '<input name="confirm" value="t">'
            '<input name="uuid" value="uuid-123">'
            "</form>",
        )
        media = FakeResponse("application/octet-stream")
        session = FakeSession([warning, media])

        result = _open_public_drive_response(session, "file-id")

        self.assertIs(result, media)
        self.assertTrue(warning.closed)
        url, kwargs = session.calls[1]
        self.assertEqual(url[0], "https://drive.usercontent.google.com/download")
        self.assertEqual(
            kwargs["params"],
            {"id": "file-id", "export": "download", "confirm": "t", "uuid": "uuid-123"},
        )

    def test_inaccessible_link_has_actionable_sharing_instructions(self):
        response = FakeResponse("text/html", status=404)
        with self.assertRaises(PermissionError) as caught:
            _open_public_drive_response(FakeSession([response]), "missing-id")

        self.assertTrue(response.closed)
        self.assertIn("Cualquier persona con el enlace", str(caught.exception))
        self.assertIn("Administrar acceso", str(caught.exception))

    def test_html_page_without_confirmation_is_not_returned_as_a_file(self):
        response = FakeResponse(
            "text/html; charset=utf-8",
            "<html><body>Sign in to Google</body></html>",
        )
        with self.assertRaises(PermissionError) as caught:
            _open_public_drive_response(FakeSession([response]), "private-id")

        self.assertIn("página web en vez del archivo", str(caught.exception))
        self.assertIn("Acceso general", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
