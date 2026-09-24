from utils.subtitle_tools import ALIGNMENTS, COLORS, FONTS, ass_font_style, ass_style
from utils.video_processor import VideoProcessor

style = ass_style("yellow", "top", 32, 4, "serif")
assert "PrimaryColour=&H0000FFFF" in style
assert "Alignment=8" in style
assert "FontSize=32" in style
assert "Fontname=DejaVu Serif" in style
assert ass_style(font="jkanime").startswith("force_style='Fontname=Roboto,")
assert "MarginV=12" in ass_style(font="jkanime")
assert ass_font_style() == ""
assert ass_font_style("montserrat") == "force_style='Fontname=Montserrat'"
assert ass_font_style("mplus", "top") == "force_style='Fontname=M PLUS 1p,Alignment=8,MarginV=12'"
assert ass_font_style("rosario") == "force_style='Fontname=Rosario,Bold=1'"
assert ass_font_style("comicsans") == "force_style='Fontname=Comic Sans MS'"
assert ass_style(font="montserrat").startswith("force_style='Fontname=Montserrat,")
assert ass_style(font="oswald").startswith("force_style='Fontname=Oswald,")
assert ass_style(font="mplus").startswith("force_style='Fontname=M PLUS 1p,")
assert VideoProcessor._escape_path("/tmp/a:b.srt") == "'/tmp/a\\:b.srt'"
assert set(COLORS) >= {"white", "yellow", "cyan", "green"}
assert set(ALIGNMENTS) >= {"bottom", "top", "center"}
assert set(FONTS) >= {"jkanime", "dejavu", "montserrat", "oswald", "mplus", "rosario", "comicsans", "liberation", "serif", "mono"}
print("subtitle feature checks: ok")
