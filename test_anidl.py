"""Pruebas de validación y salida de la integración AniDL."""
import tempfile
import unittest
from pathlib import Path

from utils.anidl import (
    AniDLError,
    AniDLOptions,
    build_command,
    changed_videos,
    extract_episode_id,
    parse_options,
    snapshot_videos,
)


class AniDLTests(unittest.TestCase):
    def test_extracts_episode_id_from_localized_crunchyroll_url(self):
        self.assertEqual(
            extract_episode_id("https://www.crunchyroll.com/es/watch/G6JQW4Z9X/episode-name"),
            "G6JQW4Z9X",
        )

    def test_rejects_lookalike_hosts_and_non_episode_links(self):
        for url in (
            "https://crunchyroll.com.evil.example/watch/G6JQW4Z9X",
            "http://www.crunchyroll.com/watch/G6JQW4Z9X",
            "https://www.crunchyroll.com/series/G6JQW4Z9X",
            "https://www.crunchyroll.com:bad/watch/G6JQW4Z9X",
        ):
            with self.subTest(url=url), self.assertRaises(AniDLError):
                extract_episode_id(url)

    def test_parses_drive_defaults_and_documented_options(self):
        self.assertEqual(parse_options(""), AniDLOptions())
        self.assertEqual(
            parse_options("--dubLang spa-419 --dlsubs es-419 --hslang es-419 -q 5 --mkv"),
            AniDLOptions(
                dub_language="spa-419",
                download_subtitles="es-419",
                hard_subtitle_language="es-419",
                quality=5,
                container="mkv",
            ),
        )
        self.assertEqual(parse_options("--dlsubs none").download_subtitles, "none")

    def test_rejects_unknown_flags_shell_fragments_and_invalid_quality_or_languages(self):
        for value in (
            "--password secret",
            "-q 4; touch /tmp/pwned",
            "--dubLang jpn -q 0",
            "-q 6",
            "--dlsubs es-419;touch",
            "--hslang fake-language",
            "--mp4 --mkv",
        ):
            with self.subTest(value=value), self.assertRaises(AniDLError):
                parse_options(value)

    def test_command_is_argv_and_does_not_invoke_shell(self):
        argv = build_command("/opt/anidl/aniDL", "G6JQW4Z9X", AniDLOptions())
        self.assertEqual(
            argv,
            [
                "/opt/anidl/aniDL", "--service", "crunchy", "-e", "G6JQW4Z9X",
                "--dubLang", "jpn", "--dlsubs", "all", "-q", "4", "--mp4",
                "--force", "y",
            ],
        )
        self.assertNotIn("shell", argv)

    def test_command_adds_optional_hardsub_language(self):
        options = parse_options("--dlsubs spa-419 --hslang es-419")
        argv = build_command("aniDL", "G6JQW4Z9X", options)
        self.assertIn("--dlsubs", argv)
        self.assertIn("--hslang", argv)
        self.assertEqual(argv[argv.index("--hslang") + 1], "es-419")

    def test_detects_only_new_or_changed_video_files_without_deleting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "existing.mp4"
            existing.write_bytes(b"old")
            before = snapshot_videos(root)
            added = root / "episode.mkv"
            added.write_bytes(b"new video")
            changed = changed_videos(root, before)
            self.assertEqual(changed, [added.resolve()])
            self.assertTrue(existing.exists())
            self.assertTrue(added.exists())


if __name__ == "__main__":
    unittest.main()
