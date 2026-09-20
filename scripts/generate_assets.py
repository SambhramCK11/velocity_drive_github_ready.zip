"""Procedural SVG asset generator.

Every background and vehicle illustration in this project is generated here
rather than downloaded, so the app ships with no binary image dependencies and
the whole visual identity is reproducible from source.

    python tools/generate_assets.py

Writes into app/static/img/.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "static" / "img"
OUT.mkdir(parents=True, exist_ok=True)

# The fleet definition drives per-vehicle paint colours. seed.py imports only
# the standard library, so this stays a plain import with no Flask app needed.
sys.path.insert(0, str(ROOT))
from app.seed import FLEET  # noqa: E402

# Brand palette ------------------------------------------------------------
INK = "#05070d"
INK_2 = "#0b1020"
GOLD = "#c9a227"
GOLD_LT = "#f0d27a"
TEAL = "#2dd4bf"
VIOLET = "#7c5cff"
AMBER = "#ff8a3d"


def write(name: str, svg: str) -> None:
    (OUT / name).write_text(svg.strip() + "\n", encoding="utf-8")
    print(f"  wrote {name}")


# ==========================================================================
# 1. Hero background — Dubai skyline at dusk
# ==========================================================================

def skyline_layer(rng: random.Random, *, width: int, baseline: int,
                  min_h: int, max_h: int, fill: str, opacity: float,
                  spire_at: float | None = None, sparse: bool = False) -> str:
    """One depth layer of procedural towers.

    ``sparse`` widens the gaps and varies the heights more, which stops the
    nearest layer reading as a solid picket fence along the bottom edge.
    """
    parts = [f'<g fill="{fill}" opacity="{opacity}">']
    x = -20
    while x < width + 40:
        w = rng.randint(34, 96) if sparse else rng.randint(26, 74)
        h = (rng.randint(min_h, max_h) if not sparse
             else int(min_h + (max_h - min_h) * rng.random() ** 1.8))
        top = baseline - h

        # Occasional tapered / stepped tower for variety.
        style = rng.random()
        if style < 0.18:                      # stepped setback tower
            inset = w * 0.22
            mid = top + h * 0.38
            parts.append(
                f'<path d="M{x},{baseline} L{x},{mid} '
                f'L{x + inset:.1f},{mid} L{x + inset:.1f},{top} '
                f'L{x + w - inset:.1f},{top} L{x + w - inset:.1f},{mid} '
                f'L{x + w},{mid} L{x + w},{baseline} Z"/>'
            )
        elif style < 0.32:                    # tapered crown
            parts.append(
                f'<path d="M{x},{baseline} L{x},{top + 26} '
                f'L{x + w / 2:.1f},{top} L{x + w},{top + 26} '
                f'L{x + w},{baseline} Z"/>'
            )
        else:                                 # plain slab
            parts.append(
                f'<rect x="{x}" y="{top}" width="{w}" height="{h}" rx="2"/>'
            )

        # Antenna
        if rng.random() < 0.25:
            parts.append(
                f'<rect x="{x + w / 2 - 1.2:.1f}" y="{top - rng.randint(10, 30)}" '
                f'width="2.4" height="32" />'
            )
        x += w + (rng.randint(26, 74) if sparse else rng.randint(6, 20))

    # Signature tapered spire (a Burj-like anchor for the composition).
    if spire_at is not None:
        cx = width * spire_at
        h = int((baseline - min_h) * 0.94) + 130
        top = baseline - h
        parts.append(
            f'<path d="M{cx - 54:.1f},{baseline} '
            f'L{cx - 40:.1f},{top + h * 0.52:.1f} '
            f'L{cx - 25:.1f},{top + h * 0.74:.1f} '
            f'L{cx - 13:.1f},{top + h * 0.88:.1f} '
            f'L{cx - 4:.1f},{top + 56:.1f} '
            f'L{cx:.1f},{top} '
            f'L{cx + 4:.1f},{top + 56:.1f} '
            f'L{cx + 13:.1f},{top + h * 0.88:.1f} '
            f'L{cx + 25:.1f},{top + h * 0.74:.1f} '
            f'L{cx + 40:.1f},{top + h * 0.52:.1f} '
            f'L{cx + 54:.1f},{baseline} Z"/>'
        )
    parts.append("</g>")
    return "".join(parts)


def window_lights(rng: random.Random, width: int, baseline: int,
                  count: int, depth: int = 300) -> str:
    """Scattered lit windows. Warmer and denser lower down the towers."""
    dots = []
    for _ in range(count):
        x = rng.uniform(0, width)
        # Bias toward the lower half of the towers, where more floors are lit.
        y = baseline - depth * (rng.random() ** 1.7)
        o = rng.uniform(0.18, 0.85)
        w = rng.choice([1.6, 2.0, 2.6])
        dots.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w}" height="{w * 1.5:.1f}" '
            f'fill="{GOLD_LT}" opacity="{o:.2f}"/>'
        )
    return f'<g>{"".join(dots)}</g>'


def hero_background() -> None:
    rng = random.Random(20260919)
    W, H = 1600, 900
    horizon = 618          # sits on the upper third so the sky dominates

    svg = f'''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}"
     width="{W}" height="{H}" preserveAspectRatio="xMidYMid slice"
     role="img" aria-label="Stylised city skyline at dusk">
  <defs>
    <!-- Stops are tuned so the warm band lands just ABOVE the horizon line;
         push them lower and the sunset hides behind the skyline. -->
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="#04050c"/>
      <stop offset="22%"  stop-color="#0d1330"/>
      <stop offset="42%"  stop-color="#2a1f47"/>
      <stop offset="56%"  stop-color="#5d3354"/>
      <stop offset="65%"  stop-color="#a1504d"/>
      <stop offset="70%"  stop-color="#b8603c"/>
      <stop offset="74%"  stop-color="#cf7a44"/>
      <stop offset="100%" stop-color="#f8cf8c"/>
    </linearGradient>
    <radialGradient id="sunGlow" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0%"   stop-color="#fff0c4" stop-opacity="0.98"/>
      <stop offset="28%"  stop-color="#ffbe6a" stop-opacity="0.60"/>
      <stop offset="62%"  stop-color="#ff8a3d" stop-opacity="0.26"/>
      <stop offset="100%" stop-color="#ff7a18" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="ground" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="#3a2230"/>
      <stop offset="18%"  stop-color="#1a1220"/>
      <stop offset="60%"  stop-color="#08070f"/>
      <stop offset="100%" stop-color="#04050a"/>
    </linearGradient>
    <linearGradient id="reflect" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="#ffb35c" stop-opacity="0.26"/>
      <stop offset="40%"  stop-color="#ff8a3d" stop-opacity="0.08"/>
      <stop offset="100%" stop-color="#ff8a3d" stop-opacity="0"/>
    </linearGradient>
    <!-- Dims the strip of bright sky that shows between the nearest towers,
         so the horizon reads as distant city glow rather than a neon bar. -->
    <linearGradient id="basehaze" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="#150a16" stop-opacity="0"/>
      <stop offset="55%"  stop-color="#140a16" stop-opacity="0.45"/>
      <stop offset="100%" stop-color="#0d0711" stop-opacity="0.78"/>
    </linearGradient>
    <linearGradient id="vignette" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="#04050c" stop-opacity="0.85"/>
      <stop offset="45%"  stop-color="#04050c" stop-opacity="0"/>
    </linearGradient>
    <filter id="soft" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="14"/>
    </filter>
    <filter id="grain">
      <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="3" seed="7"/>
      <feColorMatrix type="saturate" values="0"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.05"/></feComponentTransfer>
    </filter>
  </defs>

  <rect width="{W}" height="{H}" fill="url(#sky)"/>

  <!-- stars, thinning out toward the lit horizon -->
  <g fill="#ffffff">
    {"".join(
        f'<circle cx="{rng.uniform(0, W):.0f}" cy="{(v := rng.uniform(0, 430)):.0f}" '
        f'r="{rng.uniform(0.5, 1.6):.2f}" '
        f'opacity="{max(0.05, (1 - v / 430) * rng.uniform(0.3, 0.9)):.2f}"/>'
        for _ in range(170)
    )}
  </g>

  <!-- setting sun, low and slightly right of centre -->
  <circle cx="{W * 0.68:.0f}" cy="{horizon - 46}" r="300" fill="url(#sunGlow)"/>
  <circle cx="{W * 0.68:.0f}" cy="{horizon - 46}" r="46" fill="#fff3d0"
          opacity="0.92" filter="url(#soft)"/>

  <!-- skyline: three depth layers, far to near -->
  {skyline_layer(rng, width=W, baseline=horizon, min_h=90, max_h=250,
                 fill="#3a3057", opacity=0.42)}
  {skyline_layer(rng, width=W, baseline=horizon + 12, min_h=150, max_h=360,
                 fill="#1b1833", opacity=0.82, spire_at=0.30)}
  {window_lights(rng, W, horizon, 260, depth=330)}
  <rect x="0" y="{horizon - 90}" width="{W}" height="120" fill="url(#basehaze)"/>
  {skyline_layer(rng, width=W, baseline=horizon + 30, min_h=60, max_h=185,
                 fill="#07070f", opacity=0.97, sparse=True)}

  <!-- ground plane, holding the sunset's reflection -->
  <rect x="0" y="{horizon + 30}" width="{W}" height="{H - horizon - 30}" fill="url(#ground)"/>
  <rect x="0" y="{horizon + 30}" width="{W}" height="180" fill="url(#reflect)"/>
  <g stroke="{GOLD}" stroke-opacity="0.10" stroke-width="1">
    {"".join(f'<line x1="0" y1="{horizon + 44 + i * i * 2.6:.0f}" x2="{W}" y2="{horizon + 44 + i * i * 2.6:.0f}"/>' for i in range(10))}
  </g>

  <rect width="{W}" height="420" fill="url(#vignette)"/>
  <rect width="{W}" height="{H}" filter="url(#grain)" opacity="0.45"/>
</svg>
'''
    write("hero-skyline.svg", svg)



# ==========================================================================
# 2. Mesh gradient — soft colour field for section backgrounds
# ==========================================================================

def mesh_background() -> None:
    W = H = 1200
    blobs = [
        (0.18, 0.22, 560, GOLD, 0.34),
        (0.82, 0.16, 520, AMBER, 0.26),
        (0.70, 0.74, 620, VIOLET, 0.30),
        (0.26, 0.82, 500, TEAL, 0.20),
        (0.50, 0.48, 460, "#ff4d6d", 0.14),
    ]
    defs, shapes = [], []
    for i, (cx, cy, r, colour, alpha) in enumerate(blobs):
        defs.append(
            f'<radialGradient id="b{i}" cx="0.5" cy="0.5" r="0.5">'
            f'<stop offset="0%" stop-color="{colour}" stop-opacity="{alpha}"/>'
            f'<stop offset="100%" stop-color="{colour}" stop-opacity="0"/>'
            f"</radialGradient>"
        )
        shapes.append(
            f'<circle cx="{cx * W:.0f}" cy="{cy * H:.0f}" r="{r}" fill="url(#b{i})"/>'
        )

    svg = f'''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"
     preserveAspectRatio="xMidYMid slice" aria-hidden="true">
  <defs>
    {"".join(defs)}
    <filter id="blur"><feGaussianBlur stdDeviation="50"/></filter>
  </defs>
  <rect width="{W}" height="{H}" fill="{INK}"/>
  <g filter="url(#blur)">{"".join(shapes)}</g>
</svg>
'''
    write("mesh.svg", svg)


# ==========================================================================
# 3. Perspective grid — technical backdrop
# ==========================================================================

def grid_background() -> None:
    W, H = 1400, 800
    vpx, vpy = W / 2, 250
    rays = []
    for i in range(-22, 23):
        x_end = vpx + i * 130
        rays.append(f'<line x1="{vpx:.0f}" y1="{vpy}" x2="{x_end:.0f}" y2="{H}"/>')
    rungs = []
    for i in range(1, 24):
        t = (i / 23) ** 2.3
        y = vpy + t * (H - vpy)
        rungs.append(f'<line x1="0" y1="{y:.1f}" x2="{W}" y2="{y:.1f}" opacity="{0.05 + t * 0.35:.2f}"/>')

    svg = f'''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"
     preserveAspectRatio="xMidYMid slice" aria-hidden="true">
  <defs>
    <linearGradient id="gfade" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{INK}" stop-opacity="1"/>
      <stop offset="35%" stop-color="{INK}" stop-opacity="0.35"/>
      <stop offset="100%" stop-color="{INK}" stop-opacity="0"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.5" cy="0.32" r="0.55">
      <stop offset="0%" stop-color="{GOLD}" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="{GOLD}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="{W}" height="{H}" fill="{INK_2}"/>
  <rect width="{W}" height="{H}" fill="url(#glow)"/>
  <g stroke="{GOLD}" stroke-opacity="0.16" stroke-width="1">{"".join(rays)}</g>
  <g stroke="{TEAL}" stroke-width="1" stroke-opacity="0.5">{"".join(rungs)}</g>
  <rect width="{W}" height="{H * 0.55:.0f}" fill="url(#gfade)"/>
</svg>
'''
    write("grid.svg", svg)


# ==========================================================================
# 4. Dunes — warm desert band for the CTA section
# ==========================================================================

def dunes_background() -> None:
    W, H = 1400, 500
    rng = random.Random(4242)
    layers = []
    palette = ["#3a2418", "#55341f", "#7a4a27", "#a2642f", "#c98a44"]
    for idx, colour in enumerate(palette):
        base = 150 + idx * 62
        pts = [f"M0,{base + rng.randint(-14, 14)}"]
        x = 0
        while x < W:
            step = rng.randint(180, 300)
            cx = x + step / 2
            cy = base + rng.randint(-70, 40)
            x += step
            pts.append(f"Q{cx:.0f},{cy:.0f} {x:.0f},{base + rng.randint(-22, 22)}")
        pts.append(f"L{W},{H} L0,{H} Z")
        layers.append(f'<path d="{" ".join(pts)}" fill="{colour}" opacity="0.95"/>')

    svg = f'''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"
     preserveAspectRatio="xMidYMid slice" aria-hidden="true">
  <defs>
    <linearGradient id="dsky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#1b1020"/>
      <stop offset="60%" stop-color="#5b2f33"/>
      <stop offset="100%" stop-color="#b5623a"/>
    </linearGradient>
  </defs>
  <rect width="{W}" height="{H}" fill="url(#dsky)"/>
  <circle cx="{W * 0.5:.0f}" cy="180" r="80" fill="#ffd89b" opacity="0.35"/>
  {"".join(layers)}
</svg>
'''
    write("dunes.svg", svg)


# ==========================================================================
# 5. Tileable texture overlays
# ==========================================================================

def texture_assets() -> None:
    write("noise.svg", '''
<svg xmlns="http://www.w3.org/2000/svg" width="220" height="220" aria-hidden="true">
  <filter id="n">
    <feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="4" seed="11"/>
    <feColorMatrix type="saturate" values="0"/>
  </filter>
  <rect width="220" height="220" filter="url(#n)" opacity="0.4"/>
</svg>
''')

    write("weave.svg", f'''
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" aria-hidden="true">
  <rect width="24" height="24" fill="none"/>
  <g stroke="{GOLD}" stroke-opacity="0.09" stroke-width="1">
    <path d="M0,24 L24,0"/><path d="M-6,6 L6,-6"/><path d="M18,30 L30,18"/>
  </g>
</svg>
''')


# ==========================================================================
# 6. Vehicle illustrations — parametric side profiles
# ==========================================================================
#
# Each profile is a set of silhouette control points in a 440x190 box.
# Wheels are drawn on top of the body in a flat-illustration style.

# Each vehicle is a parametric side profile drawn in a 460x200 box on a shared
# baseline, so every car in the fleet sits at the same scale and ride height.
#
#   wheel centres  y = 150      rocker (body sill) y = 156
#   ``top``        the upper silhouette, front bumper -> rear bumper
#   wheel arches   cut out of the lower edge automatically (see build_body)

WHEEL_CY = 150
ROCKER = 156


def build_body(front_x: int, rear_x: int, top: str,
               wheels: list[tuple[int, int]]) -> str:
    """Close a vehicle silhouette, cutting an arch above each wheel.

    ``top`` runs left to right along the roofline. The lower edge is then
    traced back right to left, arcing over each wheel so the tyre sits inside
    a wheel well instead of being pasted onto a flat sill.
    """
    d = [f"M{front_x},{ROCKER}", top.strip()]
    for cx, radius in sorted(wheels, key=lambda w: -w[0]):
        arch = radius + 9
        d.append(f"L{cx + arch},{ROCKER}")
        d.append(f"A{arch},{arch} 0 0 0 {cx - arch},{ROCKER}")
    d.append("Z")
    return " ".join(d)


VEHICLES: dict[str, dict] = {
    # Mid-engine wedge: long nose, cab pushed forward, very low roofline.
    "supercar": dict(
        front_x=10, rear_x=440, wheels=[(112, 32), (348, 32)],
        top="L10,134 Q12,122 34,118 L96,110 Q120,108 140,96 L190,76 "
            "L252,74 Q286,76 306,92 L372,116 L424,126 Q440,130 440,142 L440,156",
        glass=["M186,100 L204,80 L248,78 L252,100 Z"],
        details=["M30,120 L60,117 L62,127 L30,129 Z",
                 "M400,122 L428,128 L426,136 L400,132 Z"],
        seam="M254,100 L254,140",
    ),
    # Long-bonnet fastback coupe.
    "sports-coupe": dict(
        front_x=14, rear_x=436, wheels=[(108, 32), (344, 32)],
        top="L14,132 Q16,118 40,114 L120,106 Q150,104 168,88 L206,66 "
            "L272,64 Q296,66 312,80 L376,106 L420,112 Q436,116 436,130 L436,156",
        glass=["M202,90 L220,70 L266,68 L268,92 Z",
               "M276,68 L300,72 L322,92 L278,92 Z"],
        details=["M34,116 L66,112 L68,122 L34,124 Z",
                 "M398,110 L426,115 L424,124 L396,119 Z"],
        seam="M272,92 L272,142",
    ),
    # Grand tourer: very long bonnet, upright cabin, heavy rear haunch.
    "luxury-coupe": dict(
        front_x=10, rear_x=440, wheels=[(106, 33), (348, 33)],
        top="L10,130 Q12,114 38,110 L140,102 Q168,100 186,84 L224,62 "
            "L292,60 Q318,62 334,78 L392,100 L426,108 Q440,112 440,126 L440,156",
        glass=["M220,86 L238,66 L286,64 L288,88 Z",
               "M296,64 L320,70 L342,88 L298,88 Z"],
        details=["M30,112 L64,108 L66,118 L30,120 Z",
                 "M404,106 L430,112 L428,121 L402,115 Z"],
        seam="M292,88 L292,140",
    ),
    # Roof down: just a raked windscreen frame and a flat tonneau deck.
    "convertible": dict(
        front_x=14, rear_x=436, wheels=[(110, 32), (346, 32)],
        top="L14,134 Q16,120 42,116 L128,108 Q150,106 160,102 L182,64 "
            "L200,62 L208,100 L248,98 Q254,82 268,82 Q282,82 288,98 "
            "L332,96 Q372,94 400,102 L424,110 Q436,114 436,128 L436,156",
        glass=["M167,100 L186,66 L197,65 L204,100 Z"],
        details=["M34,118 L68,114 L70,124 L34,126 Z",
                 "M398,108 L426,114 L424,123 L396,117 Z"],
        seam="M262,98 L262,142",
    ),
    # Long-wheelbase limousine: three-box, upright glass, big rear door.
    "luxury-sedan": dict(
        front_x=8, rear_x=442, wheels=[(104, 32), (352, 32)],
        top="L8,126 Q10,110 34,106 L128,100 L160,98 Q170,96 180,82 "
            "L206,58 L306,56 Q322,56 332,72 L354,98 L420,96 "
            "Q440,96 442,110 L442,134 L442,156",
        glass=["M202,84 L222,62 L266,61 L267,84 Z",
               "M275,61 L304,61 L322,84 L276,84 Z"],
        details=["M26,108 L62,104 L64,114 L26,116 Z",
                 "M406,98 L434,103 L432,112 L404,107 Z"],
        seam="M271,84 L271,142",
    ),
    "sedan": dict(
        front_x=18, rear_x=430, wheels=[(108, 30), (342, 30)],
        top="L18,130 Q20,116 42,112 L122,108 L152,106 Q162,104 172,90 "
            "L198,70 L286,68 Q302,68 314,84 L338,104 L404,102 "
            "Q424,102 428,114 L430,138 L430,156",
        glass=["M194,90 L212,72 L254,70 L255,90 Z",
               "M263,70 L288,70 L308,90 L264,90 Z"],
        details=["M34,114 L66,110 L68,120 L34,122 Z",
                 "M396,104 L422,109 L420,118 L394,113 Z"],
        seam="M259,90 L259,140",
    ),
    # Cab-forward EV: short nose, one continuous arc from screen to tail.
    "ev-sedan": dict(
        front_x=12, rear_x=436, wheels=[(106, 31), (346, 31)],
        top="L12,128 Q14,112 36,106 L104,98 Q140,94 166,78 L214,58 "
            "L290,60 Q322,66 344,84 L400,100 L422,108 "
            "Q436,112 436,126 L436,156",
        glass=["M164,82 L200,62 L252,58 L254,84 Z",
               "M262,59 L300,66 L326,86 L264,86 Z"],
        details=["M28,108 L60,104 L62,114 L28,116 Z",
                 "M404,106 L430,112 L428,121 L402,115 Z"],
        seam="M258,84 L258,140",
    ),
    # Tall boxy body, high ride height, near-vertical tailgate.
    "suv": dict(
        front_x=16, rear_x=398, wheels=[(104, 36), (330, 36)],
        top="L16,116 Q18,96 40,90 L118,84 Q130,82 138,68 L154,44 "
            "Q158,40 172,40 L342,40 Q356,40 360,54 L370,96 L388,100 "
            "Q398,104 398,118 L398,156",
        glass=["M152,74 L166,46 L228,44 L229,74 Z",
               "M237,44 L330,44 L344,74 L238,74 Z"],
        details=["M30,92 L66,88 L68,98 L30,100 Z",
                 "M374,100 L394,105 L392,116 L372,111 Z"],
        seam="M233,74 L233,140",
    ),
    # One-box people mover: the tallest body in the fleet.
    "van": dict(
        front_x=14, rear_x=420, wheels=[(100, 33), (344, 33)],
        top="L14,110 Q16,80 34,64 L78,34 Q88,26 106,26 L346,26 "
            "Q362,26 366,42 L374,90 L396,96 Q420,100 420,116 L420,156",
        glass=["M44,64 L84,36 L118,34 L118,68 Z",
               "M128,34 L212,34 L212,68 L128,68 Z",
               "M222,34 L320,34 L320,68 L222,68 Z"],
        details=["M24,86 L58,82 L60,94 L24,96 Z",
                 "M398,98 L416,103 L414,116 L396,111 Z"],
        seam="M217,68 L217,140",
    ),
    # Short three-door with a steeply raked hatch.
    "hatchback": dict(
        front_x=18, rear_x=372, wheels=[(100, 30), (310, 30)],
        top="L18,128 Q20,112 42,108 L110,102 Q124,100 134,86 L158,62 "
            "Q164,58 176,58 L262,58 Q278,58 288,72 L316,104 L346,104 "
            "Q370,106 372,120 L372,156",
        glass=["M156,84 L172,60 L218,59 L219,84 Z",
               "M227,59 L268,59 L292,84 L228,84 Z"],
        details=["M32,110 L64,106 L66,116 L32,118 Z",
                 "M346,106 L366,111 L364,121 L344,116 Z"],
        seam="M223,84 L223,140",
    ),
}


def _shade(hex_colour: str, factor: float) -> str:
    """Lighten (factor>1) or darken (factor<1) a #rrggbb colour."""
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    out = [max(0, min(255, int(c * factor))) for c in (r, g, b)]
    return "#%02x%02x%02x" % tuple(out)


def vehicle_svg(style: str, accent: str = GOLD) -> str:
    spec = VEHICLES.get(style, VEHICLES["sedan"])
    light, dark = _shade(accent, 1.38), _shade(accent, 0.50)
    deep = _shade(accent, 0.34)
    uid = style.replace("-", "")

    body = build_body(spec["front_x"], spec["rear_x"], spec["top"], spec["wheels"])

    wheels = []
    for cx, r in spec["wheels"]:
        cy = WHEEL_CY
        wheels.append(
            f'<g><circle cx="{cx}" cy="{cy}" r="{r}" fill="#090b11"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r - 4}" fill="#171b26"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r * 0.56:.0f}" fill="url(#rim{uid})"/>'
            + "".join(
                f'<line x1="{cx}" y1="{cy}" '
                f'x2="{cx + math.cos(math.radians(a)) * r * 0.52:.1f}" '
                f'y2="{cy + math.sin(math.radians(a)) * r * 0.52:.1f}" '
                f'stroke="#0d1017" stroke-width="3.4" stroke-linecap="round"/>'
                for a in range(0, 360, 45)
            )
            + f'<circle cx="{cx}" cy="{cy}" r="{r * 0.17:.0f}" fill="#0d1017"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
            f'stroke="#000" stroke-opacity="0.5" stroke-width="1.5"/></g>'
        )

    glass = "".join(
        f'<path d="{g}" fill="url(#glass{uid})"/>' for g in spec["glass"]
    )
    lights = "".join(
        f'<path d="{d}" fill="url(#lamp{uid})" opacity="0.95"/>'
        for d in spec.get("details", [])
    )
    seam = (
        f'<path d="{spec["seam"]}" stroke="{deep}" stroke-width="1.6" '
        f'fill="none" opacity="0.45"/>' if spec.get("seam") else ""
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 460 200" role="img"
     aria-label="{style.replace('-', ' ')} side profile illustration">
  <defs>
    <linearGradient id="paint{uid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{light}"/>
      <stop offset="42%" stop-color="{accent}"/>
      <stop offset="100%" stop-color="{dark}"/>
    </linearGradient>
    <linearGradient id="glass{uid}" x1="0" y1="0" x2="0.6" y2="1">
      <stop offset="0%" stop-color="#e8f1fb" stop-opacity="0.92"/>
      <stop offset="55%" stop-color="#7f93ab" stop-opacity="0.80"/>
      <stop offset="100%" stop-color="#2b3647" stop-opacity="0.88"/>
    </linearGradient>
    <linearGradient id="lamp{uid}" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#fffbe8"/>
      <stop offset="100%" stop-color="#ffd27a"/>
    </linearGradient>
    <radialGradient id="rim{uid}" cx="0.4" cy="0.35" r="0.7">
      <stop offset="0%" stop-color="#f4f6fa"/>
      <stop offset="100%" stop-color="#7f8796"/>
    </radialGradient>
    <linearGradient id="shine{uid}" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0"/>
      <stop offset="45%" stop-color="#ffffff" stop-opacity="0.55"/>
      <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
    <filter id="drop{uid}" x="-20%" y="-25%" width="140%" height="165%">
      <feDropShadow dx="0" dy="12" stdDeviation="11" flood-color="#000" flood-opacity="0.5"/>
    </filter>
  </defs>

  <ellipse cx="230" cy="186" rx="196" ry="10" fill="#000" opacity="0.30"/>
  <g filter="url(#drop{uid})">
    <path d="{body}" fill="url(#paint{uid})"/>
    <path d="{body}" fill="none" stroke="{deep}" stroke-width="2" opacity="0.55"/>
    {glass}
    {lights}
    {seam}
    <path d="M{spec['front_x'] + 40},146 L{spec['rear_x'] - 40},141"
          stroke="url(#shine{uid})" stroke-width="3.5" fill="none"/>
  </g>
  {"".join(wheels)}
</svg>'''


def vehicle_assets() -> None:
    """One illustration per car, painted in that car's own colour.

    A generic file per body style is written too, so a vehicle added to the
    database without regenerating assets still renders something sensible.
    """
    for style in VEHICLES:
        write(f"car-{style}.svg", vehicle_svg(style))

    for car in FLEET:
        write(f"car-{car['slug']}.svg",
              vehicle_svg(car["art_style"], car["accent_hex"]))


# ==========================================================================
# 7. Brand mark
# ==========================================================================

def logo_assets() -> None:
    write("logo.svg", f'''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48"
     role="img" aria-label="Velocity Drive logo">
  <defs>
    <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{GOLD_LT}"/>
      <stop offset="100%" stop-color="{GOLD}"/>
    </linearGradient>
  </defs>
  <rect width="48" height="48" rx="13" fill="{INK_2}"/>
  <rect width="48" height="48" rx="13" fill="none" stroke="url(#lg)" stroke-width="1.5" opacity="0.6"/>
  <path d="M12 15 L20.5 33 L24 24 L27.5 33 L36 15" fill="none" stroke="url(#lg)"
        stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="24" cy="38" r="2.2" fill="{TEAL}"/>
</svg>
''')

    write("favicon.svg", f'''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="8" fill="{INK_2}"/>
  <path d="M8 10 L13.5 22 L16 16 L18.5 22 L24 10" fill="none" stroke="{GOLD}"
        stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
''')


def main() -> None:
    print(f"Generating assets into {OUT}")
    hero_background()
    mesh_background()
    grid_background()
    dunes_background()
    texture_assets()
    vehicle_assets()
    logo_assets()
    print("Done.")


if __name__ == "__main__":
    main()
