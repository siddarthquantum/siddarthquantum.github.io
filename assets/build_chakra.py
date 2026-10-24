"""Generates the Sudarshana Chakra SVGs for sichakra.in.

Run from the repo root:  python assets/build_chakra.py
Writes assets/chakra-logo.svg (animated hero), assets/chakra-mark.svg (small static header mark)
and assets/favicon.svg. favicon-32.png is rendered from favicon.svg in a browser.

To change the motto, edit MOTTO / MOTTO_EN below and re-run.
"""
import math
from pathlib import Path

NAMES = ["JIYA", "SIDDARTH", "SHANTI", "RAMDEO", "NEELAM"]
MOTTO = "एक चक्र · पाँच हृदय"
MOTTO_EN = "One wheel · five hearts"

TEETH = 108
R_TOOTH_BASE, R_TOOTH_TIP = 168, 190
FLAMES = 16
R_NAMES = 130   # baseline of the names
R_MOTTO = 52    # baseline of the motto

OUT = Path(__file__).resolve().parent


def pt(r, deg):
    a = math.radians(deg - 90)  # 0 deg = top, clockwise
    return f"{r * math.cos(a):.1f},{r * math.sin(a):.1f}"


def teeth_path(n=TEETH, r_base=R_TOOTH_BASE, r_tip=R_TOOTH_TIP):
    # Serrated, forward-leaning saw teeth: slow rise, sharp drop, so the wheel reads as turning clockwise.
    step = 360 / n
    d = [f"M{pt(r_base, 0)}"]
    for i in range(n):
        a = i * step
        d.append(f"L{pt(r_tip, a + step * 0.78)}L{pt(r_base, a + step)}")
    return "".join(d) + "Z"


def ring_path(r):
    # Full circle drawn clockwise from the left, so text along the top reads left to right.
    return f"M{-r},0a{r},{r} 0 1,1 {2 * r},0a{r},{r} 0 1,1 {-2 * r},0"


def names_text():
    parts = []
    for i, name in enumerate(NAMES):
        parts.append(f'<textPath href="#ring-names" startOffset="{10 + i * 20}%">{name}</textPath>')
        parts.append(f'<textPath href="#ring-names" startOffset="{20 + i * 20}%" class="dot">•</textPath>')
    return "".join(parts)


def flames():
    return "".join(f'<use href="#flame" transform="rotate({i * 360 / FLAMES:g})"/>' for i in range(FLAMES))


def lotus():
    return "".join(f'<use href="#petal" transform="rotate({i * 45})"/>' for i in range(8))


LABEL = ("Sichakra logo: a Sudarshana Chakra carrying the names "
         + ", ".join(n.title() for n in NAMES[:-1]) + f" and {NAMES[-1].title()}")

SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="-200 -200 400 400" role="img" aria-labelledby="chakra-title chakra-desc">
<title id="chakra-title">{LABEL}</title>
<desc id="chakra-desc">Motto: {MOTTO} ({MOTTO_EN})</desc>
<style>
@import url("https://fonts.googleapis.com/css2?family=Cinzel:wght@600&amp;family=Noto+Sans+Devanagari:wght@500&amp;display=swap");
.spin,.counter,.glow{{transform-box:view-box;transform-origin:50% 50%}}
.spin{{animation:cw 30s linear infinite}}
.counter{{animation:cw 60s linear infinite reverse}}
.glow{{animation:pulse 4s ease-in-out infinite alternate}}
svg:hover .spin,svg:hover .counter,svg:hover .glow{{animation-play-state:paused}}
@keyframes cw{{to{{transform:rotate(360deg)}}}}
@keyframes pulse{{from{{transform:scale(.85)}}to{{transform:scale(1.15)}}}}
@media (prefers-reduced-motion:reduce){{.spin,.counter,.glow{{animation:none}}}}
.names{{font:600 15px Cinzel,"Trajan Pro",Georgia,serif;letter-spacing:2px;fill:#FFD36B;text-anchor:middle}}
.names .dot{{fill:#F4A300}}
.motto{{font:500 11.5px "Noto Sans Devanagari","Nirmala UI","Mangal",sans-serif;fill:#FFE6A8;text-anchor:middle}}
.gold-line{{fill:none;stroke:url(#gold);}}
</style>
<defs>
<linearGradient id="gold" x1="0" y1="-1" x2="0" y2="1" gradientUnits="objectBoundingBox">
<stop offset="0" stop-color="#FFD36B"/><stop offset="1" stop-color="#F4A300"/>
</linearGradient>
<radialGradient id="gold-r"><stop offset="0" stop-color="#FFE9A8"/><stop offset=".6" stop-color="#FFD36B"/><stop offset="1" stop-color="#F4A300"/></radialGradient>
<radialGradient id="space"><stop offset="0" stop-color="#1B2470"/><stop offset=".7" stop-color="#0E1448"/><stop offset="1" stop-color="#070A2C"/></radialGradient>
<radialGradient id="halo"><stop offset="0" stop-color="#FFD36B" stop-opacity=".9"/><stop offset=".55" stop-color="#F4A300" stop-opacity=".35"/><stop offset="1" stop-color="#F4A300" stop-opacity="0"/></radialGradient>
<path id="ring-names" d="{ring_path(R_NAMES)}"/>
<path id="ring-motto" d="{ring_path(R_MOTTO)}"/>
<path id="flame" fill="url(#gold)" d="M0,-74C7,-82 11,-92 6,-102C4,-108 6,-113 9,-118C-1,-114 -9,-106 -9,-96C-9,-88 -5,-80 0,-74Z"/>
<path id="petal" fill="url(#gold)" d="M0,-8C6,-14 7,-24 0,-34C-7,-24 -6,-14 0,-8Z"/>
</defs>

<g class="spin">
<path d="{teeth_path()}" fill="url(#gold-r)" stroke="#8A5200" stroke-width=".6" stroke-linejoin="round"/>
<circle r="169" fill="url(#space)" stroke="#8A5200" stroke-width="1"/>
<circle r="163" class="gold-line" stroke-width="2.5"/>
<circle r="118" class="gold-line" stroke-width="1"/>
<g>{flames()}</g>
</g>

<circle r="153" class="gold-line" stroke-width="1"/>
<circle r="122" class="gold-line" stroke-width="1"/>
<g class="counter"><text class="names">{names_text()}</text></g>

<circle class="glow" r="60" fill="url(#halo)" opacity=".55"/>
<circle r="70" class="gold-line" stroke-width="1.5"/>
<text class="motto" id="motto" data-en="{MOTTO_EN}"><textPath href="#ring-motto" startOffset="25%">{MOTTO}</textPath></text>
<use href="#motto" transform="rotate(180)"/>

<circle r="44" fill="#0E1448" stroke="url(#gold)" stroke-width="2"/>
<g>{lotus()}</g>
<circle r="7" fill="url(#gold-r)"/>
</svg>
"""

# Small static mark for the header and favicon: 36 bold teeth (108 / 3), no text, no animation.
MARK = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="-200 -200 400 400" role="img" aria-label="Sichakra">
<defs>
<linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFD36B"/><stop offset="1" stop-color="#F4A300"/></linearGradient>
<radialGradient id="s"><stop offset="0" stop-color="#1B2470"/><stop offset="1" stop-color="#070A2C"/></radialGradient>
<path id="f" fill="url(#g)" d="M0,-62C16,-80 22,-100 10,-122C8,-130 12,-136 16,-142C-6,-134 -22,-116 -20,-96C-19,-84 -10,-72 0,-62Z"/>
<path id="p" fill="url(#g)" d="M0,-10C12,-20 14,-34 0,-50C-14,-34 -12,-20 0,-10Z"/>
</defs>
<path d="{teeth_path(36, 158, 198)}" fill="url(#g)" stroke="#8A5200" stroke-width="3" stroke-linejoin="round"/>
<circle r="160" fill="url(#s)" stroke="#8A5200" stroke-width="3"/>
<circle r="146" fill="none" stroke="url(#g)" stroke-width="10"/>
{"".join(f'<use href="#f" transform="rotate({i * 45})"/>' for i in range(8))}
<circle r="58" fill="#0E1448" stroke="url(#g)" stroke-width="8"/>
{"".join(f'<use href="#p" transform="rotate({i * 45})"/>' for i in range(8))}
<circle r="10" fill="#FFD36B"/>
</svg>
"""

if __name__ == "__main__":
    for name, svg in [("chakra-logo.svg", SVG), ("chakra-mark.svg", MARK), ("favicon.svg", MARK)]:
        out = OUT / name
        out.write_text(svg, encoding="utf-8", newline="\n")
        print(f"{out.name}: {out.stat().st_size / 1024:.1f} KB")
