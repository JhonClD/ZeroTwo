"""Pruebas del motor de procesamiento de video (sin dependencias Python nuevas)."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.video_processing import (
    build_compression_command,
    build_hardsub_command,
    build_target_size_commands,
    calculate_video_bitrate,
    compression_profile,
    has_subtitles_filter,
    probe_video,
    run_ffmpeg,
    safe_video_extension,
)


class CommandBuilderTests(unittest.TestCase):
    def test_safe_extension(self):
        self.assertEqual(safe_video_extension("clip.MKV", "video/x-matroska"), ".mkv")
        self.assertEqual(safe_video_extension("unknown", "video/webm"), ".webm")
        self.assertEqual(safe_video_extension("../something.exe", "application/octet-stream"), ".mp4")

    def test_profiles_and_compression_command(self):
        self.assertEqual(compression_profile("balanced"), (23, "veryfast", None))
        self.assertEqual(compression_profile("720")[2], "1280:720")
        command = build_compression_command("input.mp4", "compressed.mp4", crf=28, scale="854:480", threads=2)
        self.assertIn("-crf", command)
        self.assertIn("28", command)
        self.assertIn("-sn", command)
        self.assertEqual(command[-1], "compressed.mp4")
        self.assertIn("scale=854:480:force_original_aspect_ratio=decrease:force_divisible_by=2", command)
        with self.assertRaises(ValueError):
            compression_profile("ultrafast-shell")
        with self.assertRaises(ValueError):
            build_compression_command("input.mp4", "out.mp4", crf=99)

    def test_target_size_and_two_pass(self):
        bitrate = calculate_video_bitrate(700, 3600)
        self.assertGreater(bitrate, 100_000)
        first, second = build_target_size_commands("input.mp4", "out.mp4", bitrate=bitrate)
        self.assertIn("-pass", first)
        self.assertIn("-pass", second)
        self.assertIn("-f", first)
        self.assertEqual(second[-1], "out.mp4")
        with self.assertRaises(ValueError):
            calculate_video_bitrate(20, 3600)
        with self.assertRaises(ValueError):
            calculate_video_bitrate(100, 0)

    def test_hardsub_paths_and_stream_selection(self):
        external = build_hardsub_command("input.mp4", "out.mp4", subtitle_name="subtitle.srt")
        self.assertIn("subtitles=filename='subtitle.srt':force_style='FontSize=22,Outline=2,Shadow=1,MarginV=24'", external)
        internal = build_hardsub_command("input.mkv", "out.mp4", embedded_ordinal=2)
        self.assertIn("subtitles=filename='input.mkv':si=2", internal)
        with self.assertRaises(ValueError):
            build_hardsub_command("input.mp4", "out.mp4", subtitle_name="../../evil.srt")
        with self.assertRaises(ValueError):
            build_hardsub_command("input.mp4", "out.mp4", embedded_ordinal=-1)


class FfmpegIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("FFmpeg/FFprobe no están instalados")
        if not await has_subtitles_filter():
            self.skipTest("Esta build de FFmpeg no contiene subtitles/libass")
        self.tmp = tempfile.TemporaryDirectory(prefix="zerotwo-video-test-")
        self.work = Path(self.tmp.name)
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=12",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(self.work / "input.mp4"),
            ],
            capture_output=True,
            timeout=60,
        )
        if result.returncode:
            self.tmp.cleanup()
            self.skipTest("FFmpeg no puede crear un video de prueba: " + result.stderr.decode(errors="replace")[-300:])
        (self.work / "subtitle.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,900\nZeroTwo test subtitle\n",
            encoding="utf-8",
        )

    async def asyncTearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    async def test_compress_external_hardsub_and_internal_hardsub(self):
        input_path = self.work / "input.mp4"
        info = await probe_video(input_path)
        self.assertGreater(info["duration"], 1.5)
        self.assertEqual(info["subtitles"], [])

        progress = []
        async def on_progress(current, total):
            progress.append((current, total))

        compressed = self.work / "compressed.mp4"
        await run_ffmpeg(
            build_compression_command("input.mp4", compressed.name, crf=28),
            cwd=self.work, duration=info["duration"], progress_callback=on_progress, timeout_seconds=120,
        )
        self.assertGreater(compressed.stat().st_size, 0)
        self.assertTrue(progress)

        external_output = self.work / "external.mp4"
        await run_ffmpeg(
            build_hardsub_command("input.mp4", external_output.name, subtitle_name="subtitle.srt"),
            cwd=self.work, duration=info["duration"], timeout_seconds=120,
        )
        self.assertGreater(external_output.stat().st_size, 0)

        internal = self.work / "input_subbed.mkv"
        mux = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", "input.mp4",
                "-f", "srt", "-i", "subtitle.srt", "-map", "0:v:0", "-map", "0:a?",
                "-map", "1:0", "-c", "copy", "-c:s", "srt", internal.name,
            ],
            cwd=self.work, capture_output=True, timeout=60,
        )
        self.assertEqual(mux.returncode, 0, mux.stderr.decode(errors="replace"))
        embedded_info = await probe_video(internal)
        self.assertEqual(embedded_info["subtitles"][0]["ordinal"], 0)
        internal_output = self.work / "internal.mp4"
        await run_ffmpeg(
            build_hardsub_command("input_subbed.mkv", internal_output.name, embedded_ordinal=0),
            cwd=self.work, duration=embedded_info["duration"], timeout_seconds=120,
        )
        self.assertGreater(internal_output.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
