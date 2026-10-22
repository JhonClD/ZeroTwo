"""Pruebas del motor de procesamiento basado en la plantilla de FFmpeg."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.video_processing import (
    build_compression_commands,
    build_hardsub_template_commands,
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

    def test_drive_profiles_and_two_pass_commands(self):
        self.assertEqual(compression_profile("balanced"), ("3500k", "medium", None))
        self.assertEqual(compression_profile("720")[2], "1280:720")
        commands, temporary = build_compression_commands(
            "input.mp4", "compressed.mp4", bitrate="2200k", scale="854:480", threads=2,
        )
        self.assertEqual(len(commands), 3)
        joined = " ".join(" ".join(command) for command in commands)
        self.assertIn("-pass 1", joined)
        self.assertIn("-pass 2", joined)
        self.assertIn("-tune animation", joined)
        self.assertIn("scale=854:480", joined)
        self.assertIn("input_template.mp4", temporary)
        with self.assertRaises(ValueError):
            compression_profile("ultrafast-shell")
        with self.assertRaises(ValueError):
            build_compression_commands("input.mp4", "out.mp4", bitrate="bad")

    def test_target_size_uses_same_template(self):
        bitrate = calculate_video_bitrate(700, 3600)
        commands, temporary = build_target_size_commands("input.mp4", "out.mp4", bitrate=bitrate)
        self.assertEqual(len(commands), 3)
        self.assertIn("-pass", commands[1])
        self.assertIn("-pass", commands[2])
        self.assertIn("input_template.mp4", temporary)
        with self.assertRaises(ValueError):
            calculate_video_bitrate(20, 3600)
        with self.assertRaises(ValueError):
            calculate_video_bitrate(100, 0)

    def test_hardsub_template_has_no_watermark(self):
        commands, temporary = build_hardsub_template_commands(
            "input.mkv", "output.mp4", embedded_ordinal=0,
        )
        self.assertEqual(len(commands), 4)
        joined = " ".join(" ".join(command) for command in commands)
        self.assertIn("-pass 1", joined)
        self.assertIn("-pass 2", joined)
        self.assertIn("subtitles=filename='input_subs.ass'", joined)
        self.assertNotIn("marca.png", joined)
        self.assertNotIn("marca_bot.ass", joined)
        self.assertIn("input_template.mp4", temporary)


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
            ], capture_output=True, timeout=60,
        )
        if result.returncode:
            self.tmp.cleanup()
            self.skipTest("FFmpeg no puede crear un video de prueba")
        (self.work / "subtitle.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,900\nZeroTwo test subtitle\n", encoding="utf-8",
        )

    async def asyncTearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    async def _run_commands(self, commands, duration):
        for command in commands:
            await run_ffmpeg(command, cwd=self.work, duration=duration, timeout_seconds=120)

    async def test_template_compress_and_hardsub(self):
        info = await probe_video(self.work / "input.mp4")
        self.assertGreater(info["duration"], 1.5)

        compressed = self.work / "compressed.mp4"
        commands, _ = build_compression_commands("input.mp4", compressed.name, bitrate="1200k")
        await self._run_commands(commands, info["duration"])
        self.assertGreater(compressed.stat().st_size, 0)

        external_output = self.work / "external.mp4"
        commands, _ = build_hardsub_template_commands(
            "input.mp4", external_output.name, subtitle_name="subtitle.srt", bitrate="1200k",
        )
        await self._run_commands(commands, info["duration"])
        self.assertGreater(external_output.stat().st_size, 0)

        internal = self.work / "input_subbed.mkv"
        mux = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", "input.mp4",
                "-f", "srt", "-i", "subtitle.srt", "-map", "0:v:0", "-map", "0:a?",
                "-map", "1:0", "-c", "copy", "-c:s", "srt", internal.name,
            ], cwd=self.work, capture_output=True, timeout=60,
        )
        self.assertEqual(mux.returncode, 0, mux.stderr.decode(errors="replace"))
        embedded_info = await probe_video(internal)
        self.assertEqual(embedded_info["subtitles"][0]["ordinal"], 0)
        internal_output = self.work / "internal.mp4"
        commands, _ = build_hardsub_template_commands(
            internal.name, internal_output.name, embedded_ordinal=0, bitrate="1200k",
        )
        await self._run_commands(commands, embedded_info["duration"])
        self.assertGreater(internal_output.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
