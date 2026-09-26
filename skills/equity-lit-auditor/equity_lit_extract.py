"""equity_lit_extract.py: deterministic population extraction and equity scoring.

Everything here is rule-based and auditable: each extracted population record
carries the exact term and sentence it came from, and each rubric point
carries the phrase that earned it. No LLM is involved, so the same paper
always gets the same score.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field

from equity_lit_geo import ANCESTRY_GROUPS, NON_GROUP_CODES, load_countries

PARTICIPANT_NOUN = (
    r"(?:individuals|participants|persons|people|adults|children|adolescents|women|men|subjects|"
    r"patients|cases|controls|samples|donors|volunteers|families|trios|twins|newborns|infants|"
    r"population|populations|cohorts?|descent|ancestry|origin|biobank|participants)"
)

# (pattern, ancestry code, implied country ISO3 or None, flag or None)
# Order matters: longer / more specific phrases first. Matched spans are
# masked so that "North African" is not also counted as "African".
ANCESTRY_TERMS: list[tuple[str, str, str | None, str | None]] = [
    (r"African[- ]Americans?", "AFR", "USA", None),
    (r"African[- ]Caribbeans?|Afro[- ]Caribbeans?", "AFR", None, None),
    (r"Black (?:British|African|Caribbean)", "AFR", "GBR", None),
    (r"Black (?:Americans?|participants|individuals|women|men|adults|patients|children|people)", "AFR", None, None),
    (r"sub[- ]Saharan Africans?", "AFR", None, None),
    (r"North Africans?", "MID", None, None),
    (r"Middle[- ]Eastern|Greater Middle East(?:ern)?|Arab (?:populations?|individuals|participants|ancestry)|Arabs\b", "MID", None, None),
    (r"Mexican[- ]Americans?", "AMR", "USA", None),
    (r"Puerto Ricans?", "AMR", "PRI", None),
    (r"Hispanics?|Latin[oa]s?\b|Latinx|Latine\b|Latin Americans?|admixed Americans?", "AMR", None, None),
    (r"Native Americans?|American Indians?|Indigenous Americans?|Alaska Natives?", "AMR", None, None),
    (r"Native Hawaiians?", "OCE", "USA", None),
    (r"Pacific Islanders?|Polynesians?|Melanesians?|Micronesians|Oceanians?", "OCE", None, None),
    (r"Aboriginal(?: and Torres Strait Islander)?(?: Australians?)?|Torres Strait Islanders?", "OCE", "AUS", None),
    (r"M[āa]ori\b", "OCE", "NZL", None),
    (r"South[- ]?East Asians?|Southeast Asians?|East Asians?", "EAS", None, None),
    (r"South Asians?|Central Asians?", "SAS", None, None),
    (r"(?:white|White) British", "EUR", "GBR", None),
    (r"non[- ]Hispanic whites?", "EUR", None, None),
    (r"white (?:Europeans?|Americans?|participants|individuals|women|men|adults|patients|subjects|people)", "EUR", None, None),
    (r"Caucasians?|Caucasoid", "EUR", None, "race_term"),
    (r"Ashkenazi(?: Jewish| Jews)?", "EUR", None, None),
    (r"Europeans?(?:[- ](?:ancestry|descent|origin|Americans?))?", "EUR", None, None),
    (r"Africans?(?:[- ](?:ancestry|descent|origin))?", "AFR", None, None),
    (r"Asian[- ]Americans?", "ASN", "USA", None),
    (r"Asians?\b", "ASN", None, None),
]

DEPRECATED_RACE_TERMS = re.compile(r"\b(Caucasians?|Caucasoid|Oriental|Negroid|Mongoloid)\b", re.IGNORECASE)

# Named cohorts / biobanks -> (label, [ISO3...], ancestry or None)
BIOBANKS: list[tuple[str, str, list[str], str | None]] = [
    (r"UK Biobank|UKB\b", "UK Biobank", ["GBR"], None),
    (r"FinnGen", "FinnGen", ["FIN"], "EUR"),
    (r"BioBank Japan|\bBBJ\b", "BioBank Japan", ["JPN"], "EAS"),
    (r"Tohoku Medical Megabank", "Tohoku Medical Megabank", ["JPN"], "EAS"),
    (r"China Kadoorie Biobank|\bCKB\b", "China Kadoorie Biobank", ["CHN"], "EAS"),
    (r"Taiwan Biobank", "Taiwan Biobank", ["TWN"], "EAS"),
    (r"Korean Genome and Epidemiology Study|KoGES|Korea Biobank", "KoGES", ["KOR"], "EAS"),
    (r"Singapore Chinese Health Study", "Singapore Chinese Health Study", ["SGP"], "EAS"),
    (r"Million Veteran Program|\bMVP\b", "Million Veteran Program", ["USA"], None),
    (r"All of Us Research Program|All of Us\b", "All of Us", ["USA"], None),
    (r"Jackson Heart Study", "Jackson Heart Study", ["USA"], "AFR"),
    (r"Hispanic Community Health Study|HCHS/SOL", "HCHS/SOL", ["USA"], "AMR"),
    (r"\bPAGE (?:Study|consortium)", "PAGE", ["USA"], None),
    (r"\bBioMe\b", "BioMe", ["USA"], None),
    (r"\beMERGE\b", "eMERGE", ["USA"], None),
    (r"23andMe", "23andMe", ["USA"], None),
    (r"Women'?s Health Initiative", "Women's Health Initiative", ["USA"], None),
    (r"Multi-Ethnic Study of Atherosclerosis|\bMESA\b", "MESA", ["USA"], None),
    (r"Atherosclerosis Risk in Communities|\bARIC\b", "ARIC", ["USA"], None),
    (r"Framingham", "Framingham Heart Study", ["USA"], None),
    (r"Estonian Biobank", "Estonian Biobank", ["EST"], "EUR"),
    (r"deCODE", "deCODE genetics", ["ISL"], "EUR"),
    (r"\bHUNT\b", "HUNT Study", ["NOR"], "EUR"),
    (r"Lifelines", "Lifelines", ["NLD"], "EUR"),
    (r"Generation Scotland", "Generation Scotland", ["GBR"], "EUR"),
    (r"iPSYCH", "iPSYCH", ["DNK"], "EUR"),
    (r"Genes (?:&|and) Health", "Genes & Health", ["GBR"], "SAS"),
    (r"Mexico City Prospective Study", "Mexico City Prospective Study", ["MEX"], "AMR"),
    (r"ELSA-Brasil", "ELSA-Brasil", ["BRA"], None),
    (r"Qatar Biobank|Qatar Genome", "Qatar Biobank / QGP", ["QAT"], "MID"),
    (r"Uganda Genome Resource|General Population Cohort", "Uganda Genome Resource", ["UGA"], "AFR"),
    (r"AWI-Gen", "AWI-Gen", ["ZAF", "KEN", "GHA", "BFA"], "AFR"),
    (r"H3Africa", "H3Africa", [], "AFR"),
    (r"GenomeAsia", "GenomeAsia 100K", [], None),
    (r"Indigen\w* Genom\w* (?:project|initiative)|IndiGen", "IndiGen", ["IND"], "SAS"),
]

# Reference panels are usually used for imputation / LD, not as study
# participants, so they are noted but never counted as a cohort.
REFERENCE_PANELS = re.compile(
    r"1000 Genomes|1KG\b|1KGP|HapMap|gnomAD|Human Genome Diversity Project|HGDP|"
    r"Simons Genome Diversity|SGDP|TOPMed (?:imputation|reference)|Haplotype Reference Consortium",
    re.IGNORECASE,
)

NUMBER = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?\s*(?:million|M\b|k\b|K\b)|\d{2,7})"

# Strong: the design itself spans or dissects ancestries.
CROSS_ANCESTRY_RE = re.compile(
    r"multi[- ]?(?:ancestry|ethnic|population)|trans[- ]?(?:ancestry|ethnic)|cross[- ](?:ancestry|population|ethnic)|"
    r"admixture mapping|local ancestry|(?:portability|transferability) of|"
    r"(?:PRS|polygenic (?:risk )?scores?) (?:across|in (?:diverse|non-European))",
    re.IGNORECASE,
)
# Weak: only counts when the paper actually has >= 2 ancestry groups.
CROSS_ANCESTRY_WEAK_RE = re.compile(
    r"ancestry[- ]specific|diverse (?:ancestr|population)|across (?:ancestr|populations|ethnic)|"
    r"(?:compared|differ\w*) (?:across|between) (?:ancestr|populations)",
    re.IGNORECASE,
)
LIMITATION_RE = re.compile(
    r"generali[sz]ab|limited to (?:individuals|participants|people|those) of|under[- ]?represent|"
    r"lack of (?:diversity|non-European)|predominantly (?:European|white)|Eurocentric|"
    r"may not (?:apply|generali[sz]e|transfer)|restricted to (?:European|white)|diversity gap",
    re.IGNORECASE,
)
ANCESTRY_PRACTICE_RE = re.compile(
    r"genetic ancestry|genetically inferred ancestry|self[- ](?:reported|identified) (?:race|ethnicity|ancestry)|"
    r"principal components? of ancestry|ancestry was (?:inferred|determined|assigned)",
    re.IGNORECASE,
)
ENGAGEMENT_RE = re.compile(
    r"community (?:engagement|advisory|consultation|partners|leaders)|benefit[- ]sharing|"
    r"Indigenous data sovereignty|CARE principles|capacity[- ]building|local (?:investigators|researchers|scientists|capacity)|"
    r"participatory|returned? (?:results|findings) to (?:participants|communities)|tribal (?:council|consultation|approval)",
    re.IGNORECASE,
)


@dataclass
class PopulationRecord:
    ancestry: str | None
    iso3: str | None
    n: int | None
    term: str
    kind: str          # biobank | ancestry | demonym | country
    section: str       # abstract | methods
    confidence: str    # high | medium
    snippet: str


@dataclass
class PaperAudit:
    key: str
    records: list[PopulationRecord] = field(default_factory=list)
    ancestry_n: dict[str, int | None] = field(default_factory=dict)
    country_n: dict[str, int | None] = field(default_factory=dict)
    reference_panels: list[str] = field(default_factory=list)
    affiliation_countries: list[str] = field(default_factory=list)
    total_n: int | None = None
    score: int = 0
    components: dict[str, dict] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    text_ancestry_n: dict[str, int | None] = field(default_factory=dict)
    source: str = "text extraction"
    pgs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["records"] = [asdict(r) for r in self.records]
        return d


# ---------------------------------------------------------------------------
# Compiled lexicons
# ---------------------------------------------------------------------------

def _country_patterns():
    rows = load_countries()
    alias_pats, demonym_pats = [], []
    for iso3, row in rows.items():
        for a in sorted(row["aliases"], key=len, reverse=True):
            if len(a) < 3 and a not in {"UK", "US"}:
                continue
            alias_pats.append((re.compile(rf"(?<![\w-]){re.escape(a)}(?![\w-])"), iso3))
        for d in row["demonyms"]:
            demonym_pats.append((
                re.compile(rf"(?<![\w-]){re.escape(d)}(?=\s+(?:[\w-]+\s+){{0,3}}?{PARTICIPANT_NOUN}\b)"),
                iso3, row["demonym_ancestry"] or None,
            ))
    alias_pats.sort(key=lambda t: -len(t[0].pattern))
    demonym_pats.sort(key=lambda t: -len(t[0].pattern))
    return alias_pats, demonym_pats


_ALIAS_PATS, _DEMONYM_PATS = _country_patterns()
_ANCESTRY_PATS = [(re.compile(rf"\b(?:{p})"), code, iso, flag) for p, code, iso, flag in ANCESTRY_TERMS]
_BIOBANK_PATS = [(re.compile(p), label, isos, anc) for p, label, isos, anc in BIOBANKS]


def parse_number(tok: str) -> int | None:
    t = tok.strip().replace(",", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(million|M|k|K)?", t)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2)
    if unit in {"million", "M"}:
        val *= 1_000_000
    elif unit in {"k", "K"}:
        val *= 1_000
    return int(round(val))


def split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;!?])\s+(?=[A-Z(\[])", text) if s.strip()]


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = " "
    return "".join(chars)


# "British Bangladeshi", "American Samoan"...: recruited in the host country,
# ancestry from the second demonym.
DIASPORA_HOSTS = {"British": "GBR", "American": "USA", "Canadian": "CAN", "Australian": "AUS",
                  "Dutch": "NLD", "French": "FRA", "German": "DEU", "Swedish": "SWE", "Norwegian": "NOR"}
_DIASPORA_RE = re.compile(r"\b(" + "|".join(DIASPORA_HOSTS) + r")[\s-]+$")

# Populations named only as a comparison or as the source of external weights
# ("PRS derived in Europeans", "compared with Europeans") are not participants.
NON_PARTICIPANT_CONTEXT = re.compile(
    r"(?:derived|trained|developed|built|constructed|estimated|discovered|reported|identified|observed|"
    r"performed|conducted)\s+(?:primarily\s+|mainly\s+|largely\s+|only\s+|previously\s+)?(?:in|from|among)\s+"
    r"(?:the\s+)?(?:[\w-]+\s+){0,2}$|compared\s+(?:with|to)\s+(?:the\s+)?(?:[\w-]+\s+){0,2}$|"
    r"(?:than|unlike|beyond|outside(?:\s+of)?|previous studies in|prior studies in)\s+(?:in\s+)?(?:the\s+)?$",
    re.IGNORECASE,
)


def _find_mentions(sentence: str) -> list[dict]:
    """All population mentions in one sentence, most specific first, non-overlapping."""
    mentions: list[dict] = []
    masked = sentence
    for pat, label, isos, anc in _BIOBANK_PATS:
        for m in pat.finditer(masked):
            mentions.append({"span": m.span(), "term": label, "kind": "biobank",
                             "ancestry": anc, "isos": isos, "flag": None})
            masked = _mask(masked, [m.span()])
    for pat, code, iso, flag in _ANCESTRY_PATS:
        for m in pat.finditer(masked):
            mentions.append({"span": m.span(), "term": m.group(0), "kind": "ancestry",
                             "ancestry": code, "isos": [iso] if iso else [], "flag": flag})
            masked = _mask(masked, [m.span()])
    for pat, iso3, anc in _DEMONYM_PATS:
        for m in pat.finditer(masked):
            span, term, iso = m.span(), m.group(0), iso3
            host = _DIASPORA_RE.search(masked[:m.start()])
            if host and DIASPORA_HOSTS[host.group(1)] != iso3:
                span, term, iso = (host.start(), m.end()), sentence[host.start():m.end()], DIASPORA_HOSTS[host.group(1)]
            mentions.append({"span": span, "term": term, "kind": "demonym",
                             "ancestry": anc, "isos": [iso], "flag": None})
            masked = _mask(masked, [span])
    for pat, iso3 in _ALIAS_PATS:
        for m in pat.finditer(masked):
            mentions.append({"span": m.span(), "term": m.group(0), "kind": "country",
                             "ancestry": None, "isos": [iso3], "flag": None})
            masked = _mask(masked, [m.span()])
    mentions.sort(key=lambda d: d["span"][0])
    # "British Bangladeshi and Pakistani participants": the host carries over.
    for prev, cur in zip(mentions, mentions[1:]):
        host = prev["term"].split()[0] if prev["kind"] == "demonym" else ""
        if cur["kind"] == "demonym" and host in DIASPORA_HOSTS and len(prev["term"].split()) > 1 \
                and re.fullmatch(r"\s*(?:,|and|or|,\s*and)\s*", sentence[prev["span"][1]:cur["span"][0]]):
            cur["isos"] = [DIASPORA_HOSTS[host]]
    mentions = [m for m in mentions if not NON_PARTICIPANT_CONTEXT.search(sentence[max(0, m["span"][0] - 60):m["span"][0]])]
    mentions.sort(key=lambda d: d["span"][0])
    return mentions


def _is_count(sentence: str, m: re.Match) -> bool:
    raw = m.group(1)
    n = parse_number(raw)
    if n is None or n < 20:
        return False
    after = sentence[m.end():m.end() + 40]
    before = sentence[max(0, m.start() - 12):m.start()]
    if re.match(r"\s*(?:%|years?|yrs|SNPs|variants|loci|genes|kb|Mb|bp|mg|ml|cM|months|days|weeks|times|fold|‐fold|-fold)\b", after):
        return False
    if re.search(r"(?:rs|chr|p\s*=\s*|P\s*[<=]\s*|\d\.)$", before):
        return False
    # Bare 4-digit years need an explicit participant noun right after them.
    if "," not in raw and 1900 <= n <= 2035:
        if re.search(r"\b(?:in|since|from|during|by|until|between|and|to|of)\s+$", sentence[max(0, m.start() - 10):m.start()], re.I):
            return False
        if not re.match(rf"\s+(?:[\w-]+\s+)?{PARTICIPANT_NOUN}", after):
            return False
    return True


def _assign_numbers(sentence: str, mentions: list[dict]) -> dict[int, int]:
    """Map mention index -> sample size.

    Pattern A: "12,345 individuals of European ancestry" (number, a few words, mention).
    Pattern B: "Europeans (n = 12,345)" / "European ancestry: 12,345" (mention, then number).
    A number preceded by "n =" or "(" is only ever read with pattern B.
    Then a biobank/country mention with no number inherits the number of the
    mention right before it ("... Japanese participants from BioBank Japan").
    """
    assigned: dict[int, int] = {}
    for m in re.finditer(NUMBER, sentence):
        if not _is_count(sentence, m):
            continue
        n = parse_number(m.group(1))
        before = sentence[max(0, m.start() - 8):m.start()]
        best = None
        if not re.search(r"(?:[nN]\s*=\s*|\(\s*|:\s*)$", before):
            for i, men in enumerate(mentions):
                gap = sentence[m.end():men["span"][0]]
                if men["span"][0] >= m.end() and len(gap) <= 70 and re.fullmatch(r"[\sA-Za-z-]*", gap) \
                        and len(gap.split()) <= 6:
                    best = i
                    break
        if best is None:
            for i in range(len(mentions) - 1, -1, -1):
                end = mentions[i]["span"][1]
                gap = sentence[end:m.start()]
                if 0 <= m.start() - end <= 40 and re.search(r"(?:\(|n\s*=|N\s*=|:)", gap) \
                        and not re.search(r"\d|;", gap):
                    best = i
                    break
        if best is not None and best not in assigned:
            assigned[best] = n
        elif best is not None:
            assigned[best] = max(n, assigned[best])
    for i, men in enumerate(mentions):
        if i in assigned or i == 0 or men["kind"] not in {"biobank", "country"}:
            continue
        prev = mentions[i - 1]
        gap = sentence[prev["span"][1]:men["span"][0]]
        if (i - 1) in assigned and len(gap) <= 45 and not re.search(r"\d|;|,", gap):
            assigned[i] = assigned[i - 1]
            if men["ancestry"] is None and prev["ancestry"]:
                men["ancestry"] = prev["ancestry"]
    return assigned


def extract_populations(text: str, section: str) -> tuple[list[PopulationRecord], list[str], int | None]:
    records: list[PopulationRecord] = []
    panels = sorted({m.group(0) for m in REFERENCE_PANELS.finditer(text)})
    total_n = None
    for sent in split_sentences(text):
        clean = REFERENCE_PANELS.sub(lambda m: " " * len(m.group(0)), sent)
        mentions = _find_mentions(clean)
        numbers = _assign_numbers(clean, mentions) if mentions else {}
        for m in re.finditer(rf"{NUMBER}\s+(?:[\w-]+\s+){{0,2}}?{PARTICIPANT_NOUN}", clean):
            if _is_count(clean, m):
                val = parse_number(m.group(1))
                total_n = max(total_n or 0, val)
        for i, men in enumerate(mentions):
            isos = men["isos"] or [None]
            conf = "medium" if men["kind"] == "country" else "high"
            snippet = sent.strip()
            if len(snippet) > 260:
                a = max(0, men["span"][0] - 110)
                snippet = "…" + sent[a:a + 240].strip() + "…"
            for iso in isos:
                records.append(PopulationRecord(
                    ancestry=men["ancestry"], iso3=iso, n=numbers.get(i), term=men["term"],
                    kind=men["kind"], section=section, confidence=conf, snippet=snippet,
                ))
    return records, panels, total_n


def country_mentions(text: str) -> list[str]:
    """Every country named in a short free-text field (e.g. PGS 'ancestry_country')."""
    found, masked = [], text
    for pat, iso3 in _ALIAS_PATS:
        for m in pat.finditer(masked):
            found.append(iso3)
            masked = _mask(masked, [m.span()])
    return sorted(set(found))


def affiliation_countries(affiliations: list[str]) -> list[str]:
    found = []
    for aff in affiliations:
        for pat, iso3 in _ALIAS_PATS:
            if pat.search(aff):
                found.append(iso3)
                break  # first (longest) country per affiliation string
    return sorted(set(found))


# ---------------------------------------------------------------------------
# Equity rubric (0-100)
# ---------------------------------------------------------------------------

def _first_match(rx: re.Pattern, text: str) -> str:
    m = rx.search(text)
    if not m:
        return ""
    a, b = max(0, m.start() - 60), min(len(text), m.end() + 60)
    return "…" + text[a:b].strip() + "…"


def score_paper(audit: PaperAudit, text: str) -> None:
    """Fill audit.score / components / flags. Weights documented in SKILL.md."""
    comp: dict[str, dict] = {}
    anc = {k: v for k, v in audit.ancestry_n.items() if k and k != "NR"}

    # 1. Ancestry reporting (20)
    pts, why = 0, []
    if anc or audit.country_n:
        pts += 10
        why.append("participant population described")
    if any(v for v in anc.values()):
        pts += 10
        why.append("per-group sample size reported")
    comp["ancestry_reporting"] = {"points": pts, "max": 20, "evidence": "; ".join(why)}

    # 2. Participant diversity (30): half non-European share, half evenness
    pts, why = 0.0, ""
    if anc:
        known = {k: v for k, v in anc.items() if v}
        weights = known if known else {k: 1 for k in anc}
        total = sum(weights.values())
        shares = {k: v / total for k, v in weights.items()}
        non_eur = 1 - shares.get("EUR", 0.0)
        groups = [g for g in ANCESTRY_GROUPS if g not in NON_GROUP_CODES]
        h = -sum(s * math.log(s) for s in shares.values() if s > 0)
        even = max(0.0, h / math.log(len(groups)))
        pts = 30 * (0.5 * non_eur + 0.5 * min(1.0, even))
        basis = "sample sizes" if known else "groups mentioned (no Ns)"
        why = f"non-European share {non_eur:.0%}, evenness {even:.2f} across {len(shares)} group(s), weighted by {basis}"
    comp["participant_diversity"] = {"points": round(pts), "max": 30, "evidence": why}

    # 3. Cross-ancestry analysis (15)
    ev = _first_match(CROSS_ANCESTRY_RE, text)
    if not ev and len(anc) >= 2:
        ev = _first_match(CROSS_ANCESTRY_WEAK_RE, text)
    comp["cross_ancestry_analysis"] = {"points": 15 if ev else 0, "max": 15, "evidence": ev}

    # 4. Generalisability / limitation acknowledged (10)
    ev = _first_match(LIMITATION_RE, text)
    comp["limitations_acknowledged"] = {"points": 10 if ev else 0, "max": 10, "evidence": ev}

    # 5. Descriptor practice (10)
    pts, why = 0, []
    ev = _first_match(ANCESTRY_PRACTICE_RE, text)
    if ev:
        pts += 5
        why.append(ev)
    race = DEPRECATED_RACE_TERMS.findall(text)
    if race:
        audit.flags.append(f"deprecated racial term: {', '.join(sorted(set(race)))}")
        why.append(f"uses '{race[0]}'")
    else:
        pts += 5
    comp["descriptor_practice"] = {"points": pts, "max": 10, "evidence": "; ".join(why)}

    # 6. Local capacity & engagement (15)
    countries = load_countries()
    pts, why = 0, []
    ev = _first_match(ENGAGEMENT_RE, text)
    if ev:
        pts += 5
        why.append(ev)
    lmic = sorted(i for i in audit.country_n if i and i in countries and not countries[i]["high_income"])
    if lmic:
        if not audit.affiliation_countries:
            pts += 5
            why.append("LMIC cohort; author affiliations unavailable")
        else:
            local = [i for i in lmic if i in audit.affiliation_countries]
            if local:
                pts += 10
                why.append(f"authors affiliated in cohort country: {', '.join(local)}")
            else:
                audit.flags.append(
                    f"possible parachute research: LMIC cohort ({', '.join(lmic)}) with no author affiliated there"
                )
                why.append("no author affiliated in LMIC cohort country")
    else:
        pts += 5
        why.append("no LMIC cohort (neutral)")
    comp["local_capacity_engagement"] = {"points": pts, "max": 15, "evidence": "; ".join(why)}

    audit.components = comp
    audit.score = int(sum(c["points"] for c in comp.values()))
    if anc and set(anc) == {"EUR"}:
        audit.flags.append("European-ancestry participants only")
    if not anc and "NR" in audit.ancestry_n:
        audit.flags.append("ancestry not reported")


def aggregate_records(records: list[PopulationRecord]) -> tuple[dict, dict]:
    """Per-paper sample sizes by ancestry group and by country.

    The same cohort is often mentioned several times (discovery, replication,
    biobank name), so within one (group, country) cell the largest N is kept.
    Distinct countries of the same group are separate cohorts and are summed
    ("4,210 Ghanaian and 2,975 Kenyan adults" -> AFR 7,185), unless a single
    country-less statement for the group is larger (an overall total).
    """
    cell: dict[tuple, int] = {}
    groups: set[str] = set()
    country_n: dict[str, int | None] = {}
    for r in records:
        if r.ancestry:
            groups.add(r.ancestry)
            k = (r.ancestry, r.iso3)
            cell[k] = max(cell.get(k, 0), r.n or 0)
        if r.iso3:
            country_n[r.iso3] = max(country_n.get(r.iso3) or 0, r.n or 0) or None
    ancestry_n: dict[str, int | None] = {}
    for g in groups:
        by_country = sum(v for (a, iso), v in cell.items() if a == g and iso)
        overall = cell.get((g, None), 0)
        ancestry_n[g] = max(by_country, overall) or None
    return ancestry_n, country_n


def audit_paper(paper, curated: list[PopulationRecord] | None = None) -> PaperAudit:
    """Extract, aggregate and score one paper.

    When PGS Catalog sample sets are linked to the paper (``curated``), they
    are the authority for ancestry and country counts; the text extraction is
    kept as evidence and reported as ``text_ancestry_n`` for comparison.
    """
    audit = PaperAudit(key=paper.key)
    recs, panels, total = extract_populations(f"{paper.title}. {paper.abstract}", "abstract")
    audit.records.extend(recs)
    audit.reference_panels.extend(panels)
    audit.total_n = total
    if paper.methods_text:
        recs, panels, total = extract_populations(paper.methods_text, "methods")
        audit.records.extend(recs)
        audit.reference_panels = sorted(set(audit.reference_panels) | set(panels))
        if total:
            audit.total_n = max(audit.total_n or 0, total)
    text_anc, text_cty = aggregate_records(audit.records)
    audit.text_ancestry_n = text_anc
    if curated:
        audit.records.extend(curated)
        audit.ancestry_n, cur_cty = aggregate_curated(curated)
        # Ancestry: curation is the authority. Countries: curated sample sets cover
        # only the samples used for the score, so text-found countries are kept too.
        audit.country_n = {**text_cty, **cur_cty}
        audit.source = "PGS Catalog (curated)"
    else:
        audit.ancestry_n, audit.country_n = text_anc, text_cty
    audit.affiliation_countries = affiliation_countries(paper.affiliations)
    score_paper(audit, " ".join([paper.title, paper.abstract, paper.methods_text]))
    return audit


def aggregate_curated(records: list[PopulationRecord]) -> tuple[dict, dict]:
    """Curated sample sets are distinct samples within a stage, so Ns are summed per
    stage; across stages (GWAS / development / evaluation of the same paper) the
    largest stage total is kept to avoid counting one cohort twice."""
    by_stage_anc: dict[str, dict[str, int]] = {}
    by_stage_cty: dict[str, dict[str, int]] = {}
    groups, countries = set(), set()
    seen = set()
    for r in records:
        key = (r.section, r.snippet, r.ancestry, r.iso3)
        if key in seen:
            continue
        seen.add(key)
        if r.iso3:
            countries.add(r.iso3)
            d = by_stage_cty.setdefault(r.section, {})
            d[r.iso3] = d.get(r.iso3, 0) + (r.n or 0)
        elif r.ancestry:
            groups.add(r.ancestry)
            d = by_stage_anc.setdefault(r.section, {})
            d[r.ancestry] = d.get(r.ancestry, 0) + (r.n or 0)
    anc = {g: max((d.get(g, 0) for d in by_stage_anc.values()), default=0) or None for g in groups}
    cty = {c: max((d.get(c, 0) for d in by_stage_cty.values()), default=0) or None for c in countries}
    return anc, cty
