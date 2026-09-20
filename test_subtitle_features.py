from utils.subtitle_tools import ALIGNMENTS, COLORS, ass_style
from utils.video_processor import VideoProcessor

style = ass_style("yellow", "top", 32, 4)
assert "PrimaryColour=&H0000FFFF" in style
assert "Alignment=8" in style
assert "FontSize=32" in style
assert VideoProcessor._escape_path("/tmp/a:b.srt") == "'/tmp/a\\:b.srt'"
assert set(COLORS) >= {"white", "yellow", "cyan", "green"}
assert set(ALIGNMENTS) >= {"bottom", "top", "center"}
print("subtitle feature checks: ok")
