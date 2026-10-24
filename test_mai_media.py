import unittest
from pathlib import Path

from utils.mai_media import (
    EncodeOptions,
    ffmpeg_pass_one,
    ffmpeg_pass_two,
    parse_encode_options,
    safe_filename,
)


class MaiMediaTests(unittest.TestCase):
    def test_parses_documented_hardsub_options(self):
        self.assertEqual(
            parse_encode_options("-s 1 -a 2 -vb 4800k -p veryfast", burn_subtitles=True),
            EncodeOptions(audio_index=2, subtitle_index=1, bitrate="4800k", preset="veryfast"),
        )

    def test_ec2_does_not_accept_source_subtitle_selection(self):
        with self.assertRaises(ValueError):
            parse_encode_options("-s 1", burn_subtitles=False)

    def test_rejects_untrusted_values_and_flags(self):
        for text in ("-a 51", "-vb 4800k;touch /tmp/x", "-p fast;id", "--output /tmp/file", "-a 1 -a 2"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_encode_options(text, burn_subtitles=True)

    def test_filename_is_confined_to_a_single_safe_name(self):
        self.assertEqual(safe_filename("../../episode.mkv"), "episode.mkv")
        self.assertNotIn("/", safe_filename(r"..\\outside\\episode.mkv"))

    def test_ffmpeg_builders_return_argument_arrays_without_shell(self):
        options = EncodeOptions()
        first = ffmpeg_pass_one(Path("/input/video.mkv"), Path("/tmp/pass"), options, ["subtitles=filename='embedded.ass'"])
        second = ffmpeg_pass_two(Path("/input/video.mkv"), Path("/output/video.mp4"), Path("/tmp/pass"), options, [])
        self.assertIsInstance(first, list)
        self.assertIsInstance(second, list)
        self.assertIn("-pass", first)
        self.assertIn("0:a:0", second)
        self.assertNotIn("shell", first + second)


if __name__ == "__main__":
    unittest.main()
