#!/usr/bin/env python3
"""Developer script: regenerate reference/countries.csv.

Needs `pycountry` and a Natural Earth 1:50m world-atlas TopoJSON for centroids:
    npm pack world-atlas@2 && tar xzf world-atlas-*.tgz
    python reference/build_countries.py package/countries-50m.json

The generated CSV is committed, so the skill itself needs neither dependency.
Edit the tables below (not the CSV) to change aliases, regions or income groups.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pycountry

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from equity_lit_geo import _decode_arcs, _ring  # noqa: E402

# UN SDG regions (M49), abbreviated.
REGIONS = {
    "Sub-Saharan Africa": "AGO BEN BWA BFA BDI CPV CMR CAF TCD COM COG COD CIV DJI GNQ ERI SWZ ETH GAB GMB GHA GIN GNB KEN LSO LBR MDG MWI MLI MRT MUS MOZ NAM NER NGA RWA STP SEN SYC SLE SOM ZAF SSD SDN TZA TGO UGA ZMB ZWE REU MYT SHN",
    "Northern Africa & Western Asia": "DZA EGY LBY MAR TUN ESH ARM AZE BHR CYP GEO IRQ ISR JOR KWT LBN OMN QAT SAU PSE SYR TUR ARE YEM",
    "Central & Southern Asia": "KAZ KGZ TJK TKM UZB AFG BGD BTN IND IRN MDV NPL PAK LKA",
    "Eastern & South-Eastern Asia": "CHN HKG MAC TWN PRK JPN MNG KOR BRN KHM IDN LAO MYS MMR PHL SGP THA TLS VNM",
    "Latin America & Caribbean": "AIA ATG ABW BHS BRB BES VGB CYM CUB CUW DMA DOM GRD GLP HTI JAM MTQ MSR PRI BLM KNA LCA MAF VCT SXM TTO TCA VIR BLZ CRI SLV GTM HND MEX NIC PAN ARG BOL BRA CHL COL ECU FLK GUF GUY PRY PER SUR URY VEN",
    "Oceania": "AUS NZL FJI NCL PNG SLB VUT GUM KIR MHL FSM NRU MNP PLW ASM COK PYF NIU PCN WSM TKL TON TUV WLF NFK",
}
# Everything else in pycountry defaults to "Europe & Northern America".

# World Bank high-income economies (FY2025 classification, July 2024).
HIGH_INCOME = set("""
AND AUT BEL BGR HRV CYP CZE DNK EST FRO FIN FRA DEU GIB GRC GRL HUN ISL IRL IMN ITA LVA LIE LTU LUX
MLT MCO NLD NOR POL PRT ROU RUS SMR SVK SVN ESP SWE CHE GBR USA CAN ABW ATG BHS BRB BMU VGB CYM CHL
CUW PAN PRI KNA MAF SXM TTO TCA URY VIR JPN KOR TWN SGP HKG MAC BRN AUS NZL NCL PYF GUM MNP PLW NRU
ISR QAT ARE SAU KWT BHR OMN SYC
""".split())

# Common names / abbreviations used in papers and affiliations.
ALIASES = {
    "USA": ["United States", "United States of America", "USA", "U.S.A.", "U.S.", "US"],
    "GBR": ["United Kingdom", "UK", "U.K.", "Great Britain", "Britain", "England", "Scotland", "Wales", "Northern Ireland"],
    "KOR": ["South Korea", "Republic of Korea", "Korea"],
    "PRK": ["North Korea"],
    "TWN": ["Taiwan"],
    "IRN": ["Iran"],
    "RUS": ["Russia", "Russian Federation"],
    "VNM": ["Vietnam", "Viet Nam"],
    "TZA": ["Tanzania"],
    "COD": ["Democratic Republic of the Congo", "DR Congo", "DRC"],
    "COG": ["Republic of the Congo"],
    "CIV": ["Côte d'Ivoire", "Cote d'Ivoire", "Ivory Coast"],
    "BOL": ["Bolivia"],
    "VEN": ["Venezuela"],
    "SYR": ["Syria"],
    "LAO": ["Laos"],
    "MDA": ["Moldova"],
    "CZE": ["Czech Republic", "Czechia"],
    "NLD": ["Netherlands", "The Netherlands", "Holland"],
    "TUR": ["Turkey", "Türkiye"],
    "PSE": ["Palestine"],
    "SWZ": ["Eswatini", "Swaziland"],
    "CPV": ["Cape Verde", "Cabo Verde"],
    "MKD": ["North Macedonia"],
    "BRN": ["Brunei"],
    "FSM": ["Micronesia"],
    "HKG": ["Hong Kong"],
    "MAC": ["Macau", "Macao"],
    "ARE": ["United Arab Emirates", "UAE"],
}

# Country names too ambiguous to match as bare words in scientific text
# ("Georgia" the US state, "Jordan" a surname, "Chad", "Guinea pig", ...).
AMBIGUOUS = {"GEO", "JOR", "TCD", "GIN", "DMA", "NER", "TGO", "MLI", "PER", "COL"}
# For these, keep only the unambiguous long forms.
AMBIGUOUS_KEEP = {
    "GEO": ["Republic of Georgia"],
    "JOR": ["Hashemite Kingdom of Jordan"],
    "GIN": ["Republic of Guinea", "Guinea-Conakry"],
    "PER": ["Peru"],     # case-sensitive matching makes 'Peru' safe; 'PER' is dropped
    "COL": ["Colombia"],
    "MLI": ["Mali"],
    "NER": ["Niger"],
    "TGO": ["Togo"],
}

DEMONYMS = {
    "USA": ["American"], "GBR": ["British", "English", "Scottish", "Welsh"], "JPN": ["Japanese"],
    "CHN": ["Chinese", "Han Chinese"], "KOR": ["Korean"], "TWN": ["Taiwanese"], "FIN": ["Finnish"],
    "ISL": ["Icelandic", "Icelander", "Icelanders"], "EST": ["Estonian"], "DNK": ["Danish"],
    "SWE": ["Swedish"], "NOR": ["Norwegian"], "NLD": ["Dutch"], "DEU": ["German"], "FRA": ["French"],
    "ITA": ["Italian", "Sardinian"], "ESP": ["Spanish"], "GRC": ["Greek"], "IRL": ["Irish"], "POL": ["Polish"],
    "MEX": ["Mexican"], "BRA": ["Brazilian"], "PER": ["Peruvian"], "COL": ["Colombian"], "CHL": ["Chilean"],
    "ARG": ["Argentine", "Argentinian"], "NGA": ["Nigerian", "Yoruba", "Igbo"], "UGA": ["Ugandan"],
    "KEN": ["Kenyan"], "GHA": ["Ghanaian"], "ZAF": ["South African"], "ETH": ["Ethiopian"],
    "TZA": ["Tanzanian"], "CMR": ["Cameroonian"], "SEN": ["Senegalese"], "MWI": ["Malawian"],
    "GMB": ["Gambian"], "BWA": ["Botswanan", "Batswana"], "ZWE": ["Zimbabwean"], "RWA": ["Rwandan"],
    "IND": ["Indian"], "PAK": ["Pakistani"], "BGD": ["Bangladeshi"], "LKA": ["Sri Lankan"],
    "NPL": ["Nepali", "Nepalese"], "IRN": ["Iranian", "Persian"], "TUR": ["Turkish"], "SAU": ["Saudi"],
    "QAT": ["Qatari"], "ARE": ["Emirati"], "LBN": ["Lebanese"], "EGY": ["Egyptian"], "MAR": ["Moroccan"],
    "TUN": ["Tunisian"], "ISR": ["Israeli"], "VNM": ["Vietnamese"], "THA": ["Thai"], "MYS": ["Malaysian"],
    "SGP": ["Singaporean"], "PHL": ["Filipino"], "IDN": ["Indonesian"], "PNG": ["Papua New Guinean"],
    "AUS": ["Australian"], "NZL": ["New Zealand"], "CAN": ["Canadian"], "RUS": ["Russian"],
}

# Ancestry implied when a paper describes participants with the demonym
# (e.g. "12,000 Japanese individuals"). Only set where the implication is
# reasonable; multi-ancestry nations (USA, GBR, BRA, ZAF, CAN, AUS...) are blank.
DEMONYM_ANCESTRY = {
    **{c: "EAS" for c in "JPN CHN KOR TWN VNM THA MYS SGP PHL IDN".split()},
    **{c: "EUR" for c in "FIN ISL EST DNK SWE NOR NLD DEU FRA ITA ESP GRC IRL POL RUS".split()},
    **{c: "AFR" for c in "NGA UGA KEN GHA ETH TZA CMR SEN MWI GMB BWA ZWE RWA".split()},
    **{c: "SAS" for c in "IND PAK BGD LKA NPL".split()},
    **{c: "MID" for c in "IRN TUR SAU QAT ARE LBN EGY MAR TUN".split()},
    **{c: "AMR" for c in "MEX PER COL".split()},
    "PNG": "OCE",
}


NAME_OVERRIDES = {
    "KOR": "South Korea", "PRK": "North Korea", "COD": "DR Congo", "COG": "Republic of the Congo",
    "VGB": "British Virgin Islands", "VIR": "US Virgin Islands",
}


def short_name(c) -> str:
    if c.alpha_3 in NAME_OVERRIDES:
        return NAME_OVERRIDES[c.alpha_3]
    name = getattr(c, "common_name", None) or c.name
    return name.split(",")[0].strip()


def centroids(topo_path: Path) -> dict[str, tuple[float, float]]:
    topo = json.loads(topo_path.read_text())
    arcs = _decode_arcs(topo)
    out = {}
    for geom in topo["objects"]["countries"]["geometries"]:
        if geom.get("type") not in {"Polygon", "MultiPolygon"} or "id" not in geom:
            continue
        polys = [geom["arcs"]] if geom["type"] == "Polygon" else geom["arcs"]
        best = None
        for poly in polys:
            ring = _ring(poly[0], arcs)
            a = cx = cy = 0.0
            for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
                cross = x0 * y1 - x1 * y0
                a += cross
                cx += (x0 + x1) * cross
                cy += (y0 + y1) * cross
            if a == 0:
                continue
            area = abs(a / 2)
            c = (cx / (3 * a), cy / (3 * a))
            if best is None or area > best[0]:
                best = (area, c)
        if best:
            out[str(geom["id"]).zfill(3)] = best[1]
    return out


def main() -> None:
    cents = centroids(Path(sys.argv[1]))
    region_of = {iso: r for r, codes in REGIONS.items() for iso in codes.split()}
    rows = []
    for c in pycountry.countries:
        iso3 = c.alpha_3
        name = short_name(c)
        if iso3 in AMBIGUOUS:
            aliases = AMBIGUOUS_KEEP.get(iso3, [])
        else:
            aliases = sorted({name, *ALIASES.get(iso3, [])})
        lon, lat = cents.get(c.numeric, (None, None))
        rows.append({
            "iso3": iso3, "iso_numeric": c.numeric, "name": name,
            "un_region": region_of.get(iso3, "Europe & Northern America"),
            "high_income": int(iso3 in HIGH_INCOME),
            "lat": f"{lat:.3f}" if lat is not None else "", "lon": f"{lon:.3f}" if lon is not None else "",
            "aliases": "|".join(aliases), "demonyms": "|".join(DEMONYMS.get(iso3, [])),
            "demonym_ancestry": DEMONYM_ANCESTRY.get(iso3, ""),
        })
    out = HERE / "countries.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} countries to {out}")


if __name__ == "__main__":
    main()
