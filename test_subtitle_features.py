from utils.subtitle_tools import ALIGNMENTS, COLORS, FONTS, ass_style
from utils.video_processor import VideoProcessor

style = ass_style("yellow", "top", 32, 4, "serif")
assert "PrimaryColour=&H0000FFFF" in style
assert "Alignment=8" in style
assert "FontSize=32" in style
assert "Fontname=DejaVu Serif" in style
assert ass_style(font="jkanime").startswith("force_style='Fontname=Roboto,")
assert "MarginV=12" in ass_style(font="jkanime")
assert VideoProcessor._escape_path("/tmp/a:b.srt") == "'/tmp/a\\:b.srt'"
assert set(COLORS) >= {"white", "yellow", "cyan", "green"}
assert set(ALIGNMENTS) >= {"bottom", "top", "center"}
assert set(FONTS) >= {"jkanime", "dejavu", "liberation", "serif", "mono"}
print("subtitle feature checks: ok")
