"""Pruebas unitarias del adaptador AniDL sin ejecutar el binario externo."""
import os
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

_SPEC = importlib.util.spec_from_file_location(
    "anidl_handler_under_test", Path(__file__).parent / "handlers" / "anidl_handler.py"
)
_ANIDL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ANIDL)

_allowed_user_ids = _ANIDL._allowed_user_ids
_download_args = _ANIDL._download_args
_safe_output_text = _ANIDL._safe_output_text
_valid_episode = _ANIDL._valid_episode
_valid_id = _ANIDL._valid_id
_video_outputs = _ANIDL._video_outputs


class AniDLHandlerTests(unittest.TestCase):
    def test_allowlist_requires_explicit_positive_numeric_ids(self):
        with patch.dict(os.environ, {"ZERO_TWO_ANIDL_ALLOWED_IDS": "123, 456, bad, -7, 0"}):
            self.assertEqual(_allowed_user_ids(), {123, 456})
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_allowed_user_ids(), set())

    def test_ids_and_single_episode_selection_are_strict(self):
        self.assertTrue(_valid_id("abc_DEF-123"))
        self.assertFalse(_valid_id("a;touch /tmp/x"))
        self.assertFalse(_valid_id("../secret"))
        self.assertFalse(_valid_id("-x"))
        self.assertTrue(_valid_episode("12"))
        self.assertTrue(_valid_episode("S3"))
        self.assertFalse(_valid_episode("1-4"))
        self.assertFalse(_valid_episode("1; whoami"))
        self.assertFalse(_valid_episode("0"))

    def test_cli_arguments_are_separate_and_output_is_job_scoped(self):
        args = _download_args("season_123", "3", "zerotwo_0123456789abcdef")
        self.assertEqual(args[:6], ["--service", "crunchy", "-s", "season_123", "-e", "3"])
        self.assertIn("--fileName", args)
        filename = args[args.index("--fileName") + 1]
        self.assertTrue(filename.startswith("zerotwo_0123456789abcdef/"))
        self.assertNotIn("shell", args)
        self.assertNotIn("--auth", args)

    def test_cli_output_strips_terminal_controls_and_redacts_secret_fields(self):
        value = _safe_output_text(
            "\x1b[31mAuthorization: BearerSecret\x1b[0m\n"
            "Authorization: Bearer topsecret\npassword=hunter2"
        )
        self.assertNotIn("\x1b", value)
        self.assertNotIn("BearerSecret", value)
        self.assertNotIn("topsecret", value)
        self.assertNotIn("hunter2", value)
        self.assertIn("[oculto]", value)

    def test_video_output_scan_is_limited_to_the_job_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "videos"
            job = root / "zerotwo_job"
            job.mkdir(parents=True)
            valid = job / "episode.mkv"
            valid.write_bytes(b"video")
            external = Path(temporary) / "outside.mp4"
            external.write_bytes(b"outside")
            link = job / "outside.mp4"
            try:
                link.symlink_to(external)
            except (OSError, NotImplementedError):
                self.skipTest("El sistema no permite crear enlaces simbólicos")
            self.assertEqual(_video_outputs(job), [valid.resolve()])


class AniDLProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_launch_has_no_shell_and_does_not_inherit_bot_token(self):
        class FakeStream:
            def __init__(self):
                self.pending = b"catalog result"

            async def read(self, size):
                value, self.pending = self.pending, b""
                return value

        class FakeProcess:
            pid = 12345
            returncode = 0
            stdout = FakeStream()

            async def wait(self):
                return 0

        launch = AsyncMock(return_value=FakeProcess())
        with patch.dict(os.environ, {"BOT_TOKEN": "must-not-leak", "PATH": "/usr/bin"}, clear=True):
            with patch.object(_ANIDL.asyncio, "create_subprocess_exec", launch):
                code, output = await _ANIDL._run_cli(
                    Path("/opt/anidl/aniDL"), Path("/opt/anidl"), ["--service", "crunchy"], 10
                )

        self.assertEqual(code, 0)
        self.assertEqual(output, "catalog result")
        args = launch.call_args.args
        kwargs = launch.call_args.kwargs
        self.assertEqual(args[:3], ("/opt/anidl/aniDL", "--service", "crunchy"))
        self.assertNotIn("shell", kwargs)
        self.assertNotIn("BOT_TOKEN", kwargs["env"])


class AniDLAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_handler_fails_closed_without_an_explicit_allowlist(self):
        class FakeApp:
            def __init__(self):
                self.handlers = {}

            def on_message(self, filter_, **kwargs):
                def decorator(function):
                    self.handlers[function.__name__] = function
                    return function
                return decorator

        class FakeMessage:
            text = "/anidlsearch example"
            from_user = type("User", (), {"id": 123})()
            chat = type("Chat", (), {"type": _ANIDL.enums.ChatType.PRIVATE})()

            def __init__(self):
                self.responses = []

            async def reply_text(self, text, **kwargs):
                self.responses.append(text)

        app = FakeApp()
        _ANIDL.register(app)
        message = FakeMessage()
        with patch.dict(os.environ, {}, clear=True):
            await app.handlers["anidl_command"](None, message)
        self.assertEqual(len(message.responses), 1)
        self.assertIn("ZERO_TWO_ANIDL_ALLOWED_IDS", message.responses[0])


if __name__ == "__main__":
    unittest.main()
