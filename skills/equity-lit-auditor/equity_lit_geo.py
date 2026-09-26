"""equity_lit_geo.py: country geometry and reference tables for Equity Lit Auditor.

No third-party GIS dependency. Country outlines come from the bundled
world-atlas TopoJSON (Natural Earth 1:110m, public domain; ISC-licensed
packaging), decoded here with a minimal TopoJSON reader.
"""

from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "reference"
TOPOJSON_PATH = DATA_DIR / "countries-110m.json"
COUNTRIES_CSV = DATA_DIR / "countries.csv"

# Continental ancestry groups used throughout the skill. Codes follow the
# 1000 Genomes super-population convention, extended with MID and OCE as in
# the GWAS Diversity Monitor / Mills & Rahal (2019) categories.
ANCESTRY_GROUPS = {
    "AFR": "African",
    "AMR": "Hispanic / Latin American / Indigenous American",
    "EAS": "East & South-East Asian",
    "EUR": "European",
    "MID": "Middle Eastern & North African",
    "OCE": "Oceanian / Pacific Islander",
    "SAS": "South & Central Asian",
    "ASN": "Asian (unspecified)",
    "OTH": "Multi-ancestry / admixed / other",
    "NR": "Ancestry not reported",
}
# Buckets that are not a single continental group (excluded from evenness).
NON_GROUP_CODES = {"ASN", "OTH", "NR"}

# UN World Population Prospects 2022, SDG regions, 2022 population (billions).
# Used ONLY as coarse context for the representation figure: geography is not
# ancestry (e.g. Europe & Northern America contains many non-European-ancestry
# people). Source: UN DESA, World Population Prospects 2022: Summary of Results.
REGION_POPULATION_2022 = {
    "AFR": ("Sub-Saharan Africa", 1.152),
    "EUR": ("Europe & Northern America", 1.120),
    "EAS": ("Eastern & South-Eastern Asia", 2.342),
    "SAS": ("Central & Southern Asia", 2.075),
    "AMR": ("Latin America & Caribbean", 0.658),
    "MID": ("Northern Africa & Western Asia", 0.549),
    "OCE": ("Oceania", 0.045),
}


@lru_cache(maxsize=1)
def load_countries() -> dict[str, dict]:
    """Return {ISO3: row} from reference/countries.csv."""
    rows: dict[str, dict] = {}
    with COUNTRIES_CSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            row["lat"] = float(row["lat"]) if row["lat"] else None
            row["lon"] = float(row["lon"]) if row["lon"] else None
            row["high_income"] = row["high_income"] == "1"
            row["aliases"] = [a for a in row["aliases"].split("|") if a]
            row["demonyms"] = [d for d in row["demonyms"].split("|") if d]
            rows[row["iso3"]] = row
    return rows


def _decode_arcs(topo: dict) -> list[list[tuple[float, float]]]:
    scale = topo.get("transform", {}).get("scale", [1, 1])
    translate = topo.get("transform", {}).get("translate", [0, 0])
    quantized = "transform" in topo
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for p in arc:
            if quantized:
                x += p[0]
                y += p[1]
                pts.append((x * scale[0] + translate[0], y * scale[1] + translate[1]))
            else:
                pts.append((p[0], p[1]))
        arcs.append(pts)
    return arcs


def _ring(arc_ids: list[int], arcs: list[list[tuple[float, float]]]) -> list[tuple[float, float]]:
    ring: list[tuple[float, float]] = []
    for idx in arc_ids:
        pts = arcs[idx] if idx >= 0 else list(reversed(arcs[~idx]))
        ring.extend(pts[1:] if ring else pts)
    return ring


@lru_cache(maxsize=1)
def load_country_shapes() -> dict[str, list[list[list[tuple[float, float]]]]]:
    """Return {ISO numeric string: [polygon, ...]}, polygon = [outer ring, holes...]."""
    topo = json.loads(TOPOJSON_PATH.read_text(encoding="utf-8"))
    arcs = _decode_arcs(topo)
    shapes: dict[str, list] = {}
    for geom in topo["objects"]["countries"]["geometries"]:
        gid = geom.get("id")
        if gid is None or geom.get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        polys = [geom["arcs"]] if geom["type"] == "Polygon" else geom["arcs"]
        shapes[str(gid)] = [[_ring(r, arcs) for r in poly] for poly in polys]
    return shapes


def shapes_by_iso3() -> dict[str, list]:
    """Country polygons keyed by ISO3 (countries missing at 1:110m are absent)."""
    numeric_to_iso3 = {row["iso_numeric"]: iso3 for iso3, row in load_countries().items()}
    out = {}
    for num, polys in load_country_shapes().items():
        iso3 = numeric_to_iso3.get(num.zfill(3))
        if iso3:
            out[iso3] = polys
    return out
