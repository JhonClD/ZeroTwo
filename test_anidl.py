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

    def test_parses_documented_defaults_and_options(self):
        self.assertEqual(parse_options(""), AniDLOptions())
        self.assertEqual(
            parse_options("--dubLang spa-419 --hslang es-419 -q 5 --mkv"),
            AniDLOptions("spa-419", "es-419", 5, "mkv"),
        )

    def test_rejects_unknown_flags_shell_fragments_and_invalid_quality(self):
        for value in (
            "--password secret",
            "-q 4; touch /tmp/pwned",
            "--dubLang jpn -q 0",
            "--mp4 --mkv",
        ):
            with self.subTest(value=value), self.assertRaises(AniDLError):
                parse_options(value)

    def test_command_is_argv_and_does_not_invoke_shell(self):
        argv = build_command("/opt/anidl/aniDL", "G6JQW4Z9X", AniDLOptions())
        self.assertEqual(argv[:6], ["/opt/anidl/aniDL", "--service", "crunchy", "-e", "G6JQW4Z9X", "--dubLang"])
        self.assertIn("--force", argv)
        self.assertNotIn("shell", argv)

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
