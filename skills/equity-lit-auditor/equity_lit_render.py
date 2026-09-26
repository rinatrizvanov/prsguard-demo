"""equity_lit_render.py: geographic heat map and representation figures.

Map projection is Equal Earth (Šavrič, Patterson & Jenny 2018): an equal-area
projection, so Africa and South Asia are not visually shrunk relative to
Europe and North America, which matters for an equity figure.
"""

from __future__ import annotations

import html
import json
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from equity_lit_geo import ANCESTRY_GROUPS, REGION_POPULATION_2022, load_countries, shapes_by_iso3  # noqa: E402

# Sequential blue ramp (light -> dark) and neutrals from the ClawBio/dataviz reference palette.
RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
NO_DATA = "#e6e5e1"
UNKNOWN = "#b3b1ab"   # country reported, but no sample size could be extracted
SURFACE = "#fcfcfb"
INK = "#262624"
INK_MUTED = "#6b6a66"
BORDER = "#fcfcfb"

A1, A2, A3, A4 = 1.340264, -0.081106, 0.000893, 0.003796
M = math.sqrt(3) / 2

# Every figure made from the bundled fixture carries this label three ways: in its
# title, as a watermark across the plot (survives cropping the title off), and as a
# PNG text chunk (machine-readable: PIL.Image.open(p).text["data_provenance"]).
SYNTHETIC_LABEL = "SYNTHETIC DEMO"
SYNTHETIC_COLOR = "#b3261e"


def provenance_label(synthetic: bool) -> str:
    return SYNTHETIC_LABEL if synthetic else "LIVE (Europe PMC / PGS Catalog)"


def _titled(title: str, synthetic: bool) -> str:
    return f"{title} ({SYNTHETIC_LABEL})" if synthetic and SYNTHETIC_LABEL not in title else title


def _save(fig, path, title: str, synthetic: bool) -> None:
    if synthetic:
        width_in = fig.get_size_inches()[0]   # keep the watermark inside narrow figures
        fig.text(0.5, 0.5, f"{SYNTHETIC_LABEL} · NOT REAL LITERATURE", fontsize=2.3 * width_in,
                 color=SYNTHETIC_COLOR, alpha=0.16, rotation=18, ha="center", va="center", weight="bold",
                 zorder=100)
    fig.savefig(path, facecolor=SURFACE, metadata={
        "Title": title, "data_provenance": provenance_label(synthetic), "synthetic": str(bool(synthetic)).lower(),
        "Software": "ClawBio equity-lit-auditor"})
    plt.close(fig)


def equal_earth(lon: float, lat: float) -> tuple[float, float]:
    lam = math.radians(lon)
    phi = math.radians(max(-89.9, min(89.9, lat)))
    theta = math.asin(M * math.sin(phi))
    t2 = theta * theta
    t6 = t2 * t2 * t2
    x = 2 * math.sqrt(3) * lam * math.cos(theta) / (3 * (9 * A4 * t6 * t2 + 7 * A3 * t6 + 3 * A2 * t2 + A1))
    y = theta * (A1 + A2 * t2 + t6 * (A3 + A4 * t2))
    return x, y


def _bins(values: list[float]) -> list[float]:
    """Log-spaced class breaks (1-2-5 series) covering the data."""
    vmax = max(values) if values else 1
    steps = []
    for e in range(0, 10):
        for m in (1, 2, 5):
            steps.append(m * 10 ** e)
    lo = min(v for v in values if v > 0) if values else 1
    breaks = [s for s in steps if lo <= s * 2.5 and s <= vmax]
    # keep at most len(RAMP) classes
    while len(breaks) > len(RAMP):
        breaks = breaks[::2]
    return breaks or [1]


def _color_for(value: float, breaks: list[float]) -> str:
    idx = 0
    for i, b in enumerate(breaks):
        if value >= b:
            idx = i
    offset = len(RAMP) - len(breaks)
    return RAMP[max(0, min(len(RAMP) - 1, idx + offset))]


def _fmt(n: float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return f"{int(n)}"


def split_antimeridian(ring):
    """Split a lon/lat ring that jumps between -180 and +180 into one ring per side."""
    pieces, cur = [], [ring[0]]
    for a, b in zip(ring, ring[1:]):
        if abs(a[0] - b[0]) > 180:
            pieces.append(cur)
            cur = []
        cur.append(b)
    pieces.append(cur)
    if len(pieces) > 1:
        pieces[0] = pieces.pop() + pieces[0]   # the ring wraps: first and last pieces are one side
    return [p for p in pieces if len(p) >= 3]


def country_rings(polys):
    """Outer rings of a country's polygons, antimeridian-safe."""
    for poly in polys:
        if len(poly[0]) >= 3:
            yield from split_antimeridian(poly[0])


def _projected_polygons(polys):
    return [[equal_earth(lon, lat) for lon, lat in ring] for ring in country_rings(polys)]


def heatmap_png(country_values: dict[str, float], metric_label: str, title: str, subtitle: str, path,
                unknown: set[str] | None = None, synthetic: bool = False) -> None:
    unknown = unknown or set()
    title = _titled(title, synthetic)
    shapes = shapes_by_iso3()
    countries = load_countries()
    vals = [v for v in country_values.values() if v > 0]
    breaks = _bins(vals)

    fig, ax = plt.subplots(figsize=(12, 6.6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    polys, colors = [], []
    for iso3, geom in shapes.items():
        if iso3 == "ATA":
            continue
        v = country_values.get(iso3, 0)
        c = _color_for(v, breaks) if v > 0 else (UNKNOWN if iso3 in unknown else NO_DATA)
        for pts in _projected_polygons(geom):
            polys.append(pts)
            colors.append(c)
    ax.add_collection(PolyCollection(polys, facecolors=colors, edgecolors=BORDER, linewidths=0.4))

    # Small countries absent at 1:110m (e.g. Singapore, Bahrain) get a marker.
    for iso3, v in country_values.items():
        if v > 0 and iso3 not in shapes and countries.get(iso3, {}).get("lat") is not None:
            x, y = equal_earth(countries[iso3]["lon"], countries[iso3]["lat"])
            ax.scatter([x], [y], s=46, color=_color_for(v, breaks), edgecolors=SURFACE, linewidths=1.2, zorder=5)

    # Outline of the globe
    edge = [equal_earth(-180, lat) for lat in range(-90, 91)] + [equal_earth(180, lat) for lat in range(90, -91, -1)]
    ax.plot([p[0] for p in edge] + [edge[0][0]], [p[1] for p in edge] + [edge[0][1]], color="#d4d3cf", lw=0.8)

    ax.set_xlim(-2.8, 2.8)
    ax.set_ylim(-1.2, 1.38)
    ax.set_aspect("equal")
    ax.axis("off")

    handles = [Patch(facecolor=NO_DATA, edgecolor="none", label="none found")]
    if unknown:
        handles.append(Patch(facecolor=UNKNOWN, edgecolor="none", label="reported, N not stated"))
    offset = len(RAMP) - len(breaks)
    for i, b in enumerate(breaks):
        hi = breaks[i + 1] if i + 1 < len(breaks) else None
        label = f"{_fmt(b)}–{_fmt(hi)}" if hi else f"≥ {_fmt(b)}"
        handles.append(Patch(facecolor=RAMP[i + offset], edgecolor="none", label=label))
    leg = ax.legend(handles=handles, title=metric_label, loc="lower left", frameon=False, fontsize=8,
                    title_fontsize=8.5, bbox_to_anchor=(0.0, 0.0), handlelength=1.4, handleheight=1.0)
    plt.setp(leg.get_texts(), color=INK_MUTED)
    leg.get_title().set_color(INK)

    fig.text(0.04, 0.955, title, fontsize=14, color=SYNTHETIC_COLOR if synthetic else INK, weight="bold",
             ha="left", va="top")
    fig.text(0.04, 0.915, subtitle, fontsize=9, color=INK_MUTED, ha="left", va="top")
    fig.subplots_adjust(left=0.02, right=0.98, top=0.9, bottom=0.02)
    _save(fig, path, title, synthetic)


def representation_png(ancestry_share: dict[str, float], basis: str, path, synthetic: bool = False) -> None:
    """Horizontal bars: share of participants by ancestry group vs coarse world population share."""
    groups = [g for g in ANCESTRY_GROUPS if g != "ASN" or ancestry_share.get("ASN")]
    world_total = sum(p for _, p in REGION_POPULATION_2022.values())
    fig, ax = plt.subplots(figsize=(8, 0.5 * len(groups) + 1.6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ys = list(range(len(groups)))[::-1]
    xmax = 5.0
    for y, g in zip(ys, groups):
        share = ancestry_share.get(g, 0.0) * 100
        ref = REGION_POPULATION_2022[g][1] / world_total * 100 if g in REGION_POPULATION_2022 else 0
        xmax = max(xmax, share, ref)
    xmax = min(100, math.ceil(xmax * 1.18 / 10) * 10)
    for y, g in zip(ys, groups):
        share = ancestry_share.get(g, 0.0)
        ax.barh(y, share * 100, height=0.56, color=RAMP[4], edgecolor=SURFACE, linewidth=2)
        ref = REGION_POPULATION_2022[g][1] / world_total * 100 if g in REGION_POPULATION_2022 else None
        if ref is not None:
            ax.plot([ref, ref], [y - 0.36, y + 0.36], color=INK, lw=2, solid_capstyle="round")
        label = f"{share:.1%}" if 0 < share < 0.01 else f"{share:.0%}"
        ax.text(max(share * 100, ref or 0) + xmax * 0.015, y, label, va="center", fontsize=8.5, color=INK)
    ax.set_yticks(ys)
    ax.set_yticklabels([f"{ANCESTRY_GROUPS[g]} ({g})" for g in groups], fontsize=8.5, color=INK)
    ax.set_xlim(0, xmax)
    ax.set_xlabel("% of total", fontsize=8.5, color=INK_MUTED)
    ax.tick_params(axis="x", colors=INK_MUTED, labelsize=8)
    ax.tick_params(axis="y", length=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#d4d3cf")
    ax.grid(axis="x", color="#ecebe7", lw=0.8)
    ax.set_axisbelow(True)
    handles = [Patch(facecolor=RAMP[4], label=f"Participants ({basis})"),
               plt.Line2D([0], [0], color=INK, lw=2, label="World pop. share, matching UN region (2022)")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.015, 0.935), ncol=2, frameon=False,
               fontsize=7.5, labelcolor=INK_MUTED)
    title = _titled("Who is in the data? Participant ancestry vs world population", synthetic)
    fig.suptitle(title, fontsize=11, color=SYNTHETIC_COLOR if synthetic else INK, weight="bold", x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    _save(fig, path, title, synthetic)


def heatmap_html(country_rows: list[dict], metric_label: str, title: str, subtitle: str, path,
                 synthetic: bool = False) -> None:
    """Self-contained interactive map (inline SVG, hover tooltips, table view, light/dark)."""
    title = _titled(title, synthetic)
    provenance = provenance_label(synthetic)
    banner = (f'<p class="synthetic" role="alert"><b>{SYNTHETIC_LABEL}.</b> Every paper, cohort and number on this '
              "page comes from the bundled synthetic fixture. It is not real literature and must not be cited.</p>"
              if synthetic else "")
    watermark = (f'<text class="wm" x="500" y="260" text-anchor="middle" transform="rotate(-12 500 260)">'
                 f"{SYNTHETIC_LABEL}</text>" if synthetic else "")
    shapes = shapes_by_iso3()
    countries = load_countries()
    vals = [r["value"] for r in country_rows if r["value"] > 0]
    breaks = _bins(vals)
    by_iso = {r["iso3"]: r for r in country_rows}
    W, H = 1000, 500
    sx = W / 5.6
    sy = sx

    def pt(lon, lat):
        x, y = equal_earth(lon, lat)
        return (x + 2.8) * sx, (1.3 - y) * sy

    paths = []
    for iso3, geom in shapes.items():
        if iso3 == "ATA":
            continue
        d = ""
        for ring in country_rings(geom):
            coords = [pt(lon, lat) for lon, lat in ring]
            d += "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in coords) + "Z"
        r = by_iso.get(iso3)
        step = RAMP.index(_color_for(r["value"], breaks)) if r and r["value"] > 0 else -1
        cls = f"c{step}" if step >= 0 else ("unk" if r else "nd")
        paths.append(f'<path class="{cls}" data-iso="{iso3}" d="{d}"/>')
    dots = []
    for r in country_rows:
        iso3 = r["iso3"]
        if r["value"] > 0 and iso3 not in shapes and countries.get(iso3, {}).get("lat") is not None:
            x, y = pt(countries[iso3]["lon"], countries[iso3]["lat"])
            step = RAMP.index(_color_for(r["value"], breaks))
            dots.append(f'<circle class="c{step} dot" data-iso="{iso3}" cx="{x:.1f}" cy="{y:.1f}" r="5"/>')
    outline = [pt(-180, lat) for lat in range(-90, 91, 2)] + [pt(180, lat) for lat in range(90, -91, -2)]
    outline_d = "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in outline) + "Z"

    legend = ['<span class="sw nd"></span>none found']
    if any(r["value"] <= 0 for r in country_rows):
        legend.append('<span class="sw unk"></span>reported, N not stated')
    offset = len(RAMP) - len(breaks)
    for i, b in enumerate(breaks):
        hi = breaks[i + 1] if i + 1 < len(breaks) else None
        label = f"{_fmt(b)}–{_fmt(hi)}" if hi else f"≥ {_fmt(b)}"
        legend.append(f'<span class="sw c{i + offset}"></span>{html.escape(label)}')

    rows_sorted = sorted(country_rows, key=lambda r: -r["value"])
    table = "".join(
        f"<tr><td>{html.escape(r['name'])}</td><td>{html.escape(r['un_region'])}</td>"
        f"<td class=num>{format(r['participants'], ',') if r['participants'] else 'not stated'}</td><td class=num>{r['papers']}</td></tr>"
        for r in rows_sorted
    )
    data = {r["iso3"]: {"name": r["name"], "participants": r["participants"], "papers": r["papers"],
                        "titles": r["titles"][:5]} for r in country_rows}
    light_vars = ";".join(f"--c{i}:{c}" for i, c in enumerate(RAMP))
    # Dark mode: ramp reversed so "more" stays the higher-contrast end on the dark surface.
    dark_vars = ";".join(f"--c{i}:{c}" for i, c in enumerate(RAMP[::-1]))
    ramp_classes = "".join(f".c{i}{{fill:var(--c{i})}} .sw.c{i}{{background:var(--c{i})}}" for i in range(len(RAMP)))

    page = f"""<!doctype html>
<html lang="en" data-provenance="{html.escape(provenance)}" data-synthetic="{str(bool(synthetic)).lower()}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="data-provenance" content="{html.escape(provenance)}">
<title>{"Genomic Cohort Map (" + SYNTHETIC_LABEL + ")" if synthetic else "Genomic Cohort Map"}</title>
<style>
:root {{ --bg:#fcfcfb; --ink:#262624; --muted:#6b6a66; --nd:#e6e5e1; --unk:#b3b1ab; --line:#d4d3cf; --tip:#ffffff; }}
:root {{ {light_vars}; }}
{ramp_classes}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#1a1a19; --ink:#ecebe7; --muted:#a3a29d; --nd:#383835; --unk:#6b6a66; --line:#4a4945; --tip:#262624; {dark_vars}; }} }}
:root[data-theme="dark"] {{ --bg:#1a1a19; --ink:#ecebe7; --muted:#a3a29d; --nd:#383835; --unk:#6b6a66; --line:#4a4945; --tip:#262624; {dark_vars}; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif; }}
main {{ max-width:1040px; margin:0 auto; padding:24px 16px 40px; }}
h1 {{ font-size:20px; margin:0 0 4px; }} p.sub {{ color:var(--muted); margin:0 0 16px; }}
svg {{ width:100%; height:auto; display:block; }}
path, circle {{ stroke:var(--bg); stroke-width:.6; }}
.nd {{ fill:var(--nd); }} .sw.nd {{ background:var(--nd); }} .unk {{ fill:var(--unk); }} .sw.unk {{ background:var(--unk); }}
.globe {{ fill:none; stroke:var(--line); stroke-width:1; }}
[data-iso]:hover {{ stroke:var(--ink); stroke-width:1.4; }}
.legend {{ display:flex; flex-wrap:wrap; gap:6px 14px; color:var(--muted); font-size:12px; margin:8px 0 20px; align-items:center; }}
.legend b {{ color:var(--ink); font-weight:600; margin-right:4px; }}
.sw {{ display:inline-block; width:14px; height:10px; border-radius:2px; margin-right:5px; vertical-align:-1px; }}
#tip {{ position:fixed; pointer-events:none; background:var(--tip); color:var(--ink); border:1px solid var(--line);
  border-radius:6px; padding:8px 10px; font-size:12px; max-width:320px; box-shadow:0 4px 14px rgba(0,0,0,.12); display:none; }}
#tip .t {{ color:var(--muted); margin-top:4px; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; }}
th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }}
th {{ color:var(--muted); font-weight:600; }} td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
details summary {{ cursor:pointer; color:var(--muted); margin-bottom:8px; }}
.wrap {{ overflow-x:auto; }}
.synthetic {{ border:2px solid #b3261e; color:#b3261e; border-radius:6px; padding:8px 12px; margin:0 0 12px; }}
h1.synthetic-title {{ color:#b3261e; }}
.wm {{ fill:#b3261e; opacity:.16; font:bold 64px system-ui,sans-serif; pointer-events:none; stroke:none; }}
</style></head><body><main>
{banner}
<h1{' class="synthetic-title"' if synthetic else ''}>{html.escape(title)}</h1>
<p class="sub">{html.escape(subtitle)}</p>
<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)}">
<path class="globe" d="{outline_d}"/>
{''.join(paths)}{''.join(dots)}{watermark}
</svg>
<div class="legend"><b>{html.escape(metric_label)}</b>{''.join(f'<span>{x}</span>' for x in legend)}</div>
<details open><summary>Table view ({len(rows_sorted)} countries)</summary>
<div class="wrap"><table><thead><tr><th>Country</th><th>UN region</th><th class=num>Participants (extracted)</th><th class=num>Papers</th></tr></thead>
<tbody>{table}</tbody></table></div></details>
<div id="tip"></div>
</main>
<script>
const DATA_PROVENANCE = {json.dumps(provenance)};
const DATA = {json.dumps(data)};
const tip = document.getElementById('tip');
function esc(s) {{ const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }}
document.querySelectorAll('[data-iso]').forEach(el => {{
  el.addEventListener('mousemove', e => {{
    const d = DATA[el.dataset.iso];
    if (!d) {{ tip.style.display = 'none'; return; }}
    tip.innerHTML = '<b>' + esc(d.name) + '</b><br>' + (d.participants ? d.participants.toLocaleString() + ' participants' : 'N not stated') + ' · ' + d.papers +
      ' paper' + (d.papers === 1 ? '' : 's') + d.titles.map(t => '<div class="t">• ' + esc(t) + '</div>').join('');
    tip.style.display = 'block';
    const x = Math.min(e.clientX + 14, window.innerWidth - 340);
    tip.style.left = x + 'px'; tip.style.top = (e.clientY + 14) + 'px';
  }});
  el.addEventListener('mouseleave', () => tip.style.display = 'none');
}});
</script></body></html>"""
    path.write_text(page, encoding="utf-8")


# Categorical slots (fixed order, from the ClawBio/dataviz reference palette).
GROUP_COLORS = {
    "EUR": "#2a78d6", "AFR": "#eb6834", "EAS": "#1baf7a", "SAS": "#eda100", "ASN": "#8c6d46",
    "AMR": "#e87ba4", "MID": "#008300", "OCE": "#4a3aa7", "OTHER": "#b3b1ab", "NR": "#e6e5e1",
}
# ASN ("Asian unspecified" in the PGS Catalog) has its own slot: folding it into
# "Multi-ancestry / other" mislabelled single-ancestry Asian samples in the figure.
GROUP_LABELS = {
    "EUR": "European", "AFR": "African", "EAS": "East/SE Asian", "SAS": "South/Central Asian",
    "ASN": "Asian (unspecified)",
    "AMR": "Hispanic/Latin American", "MID": "Middle Eastern/N. African", "OCE": "Oceanian",
    "OTHER": "Multi-ancestry / other", "NR": "Not reported",
}


def fold_stage_groups(counts: dict[str, int]) -> dict[str, int]:
    """Map ancestry codes onto the figure's colour slots (OTH and unknown codes -> OTHER)."""
    folded: dict[str, int] = {}
    for g, n in counts.items():
        key = g if g in GROUP_COLORS else "OTHER"
        folded[key] = folded.get(key, 0) + n
    return folded


def pgs_stage_png(stages: dict[str, dict[str, int]], path, demo: bool = False) -> None:
    """100% stacked bars: ancestry of participants at GWAS, development and evaluation stages."""
    rows = [(st, counts) for st, counts in stages.items() if sum(counts.values())]
    if not rows:
        rows = [("GWAS", {})]
    fig, ax = plt.subplots(figsize=(9, 1.0 * len(rows) + 1.9), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    order = list(GROUP_COLORS)
    used = set()
    for i, (st, counts) in enumerate(rows):
        folded = fold_stage_groups(counts)
        tot = sum(folded.values()) or 1
        left = 0.0
        y = len(rows) - 1 - i
        for g in order:
            share = folded.get(g, 0) / tot * 100
            if share <= 0:
                continue
            used.add(g)
            ax.barh(y, share, left=left, height=0.55, color=GROUP_COLORS[g], edgecolor=SURFACE, linewidth=2)
            if share >= 7:
                ink = "#ffffff" if g in {"EUR", "MID", "OCE", "AFR", "ASN"} else INK
                ax.text(left + share / 2, y, f"{share:.0f}%", ha="center", va="center", fontsize=8, color=ink)
            left += share
        ax.text(101, y, f"n = {_fmt(sum(counts.values()))}", va="center", fontsize=8, color=INK_MUTED)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([st.capitalize() if st != "GWAS" else "GWAS (variant source)" for st, _ in rows][::-1],
                       fontsize=9, color=INK)
    ax.set_xlim(0, 112)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0", "25", "50", "75", "100%"])
    ax.tick_params(axis="x", colors=INK_MUTED, labelsize=8)
    ax.tick_params(axis="y", length=0)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#d4d3cf")
    handles = [Patch(facecolor=GROUP_COLORS[g], label=GROUP_LABELS[g]) for g in order if g in used]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.015, 0.915), ncol=min(5, len(handles)),
               frameon=False, fontsize=7.5, labelcolor=INK_MUTED, handlelength=1.2)
    title = _titled("PGS Catalog: ancestry of participants at each stage", demo)
    fig.suptitle(title, fontsize=11, color=SYNTHETIC_COLOR if demo else INK, weight="bold", x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.8 if len(handles) > 4 else 0.85))
    _save(fig, path, title, demo)
