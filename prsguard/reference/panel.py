"""1000 Genomes phase 3 reference panel: extraction, storage and loading.

PRSGuard needs individual-level reference genotypes for two things:

* a fixed projection space for ancestry/reference placement (PCA sites), and
* empirical reference distributions of each candidate PGS (PGS sites).

Genotypes are read by indexed range requests from the public 1000 Genomes
phase 3 release (GRCh37, 2,504 unrelated samples, 26 populations; open data,
IGSR data reuse statement: https://www.internationalgenome.org/IGSR_disclaimer).
Only the requested sites are fetched; the result is a small, versioned NPZ
that the rest of the pipeline reads offline.

Rebuilding the panel needs ``pysam`` (``pip install prsguard[reference]``);
reading it needs only numpy.
"""

from __future__ import annotations

import concurrent.futures as cf
import gzip
import hashlib
import io
import json
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

BASE_URL = "https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502"
VCF_URL = BASE_URL + "/ALL.chr{chrom}.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz"
PANEL_URL = BASE_URL + "/integrated_call_samples_v3.20130502.ALL.panel"
BUILD = "GRCh37"
SUPERPOPS = ("AFR", "AMR", "EAS", "EUR", "SAS")


@dataclass(frozen=True)
class Site:
    chrom: str
    pos: int


@dataclass
class ReferencePanel:
    """Alt-allele dosages (int8, -1 missing) for ``n_variants`` x ``n_samples``."""

    dosages: np.ndarray
    chrom: np.ndarray
    pos: np.ndarray
    ids: np.ndarray
    ref: np.ndarray
    alt: np.ndarray
    samples: np.ndarray
    pop: np.ndarray
    superpop: np.ndarray
    sex: np.ndarray
    meta: dict

    def key_index(self) -> dict[tuple[str, int, str, str], int]:
        return {(str(c), int(p), str(r), str(a)): i
                for i, (c, p, r, a) in enumerate(zip(self.chrom, self.pos, self.ref, self.alt))}

    def position_index(self) -> dict[tuple[str, int], list[int]]:
        out: dict[tuple[str, int], list[int]] = {}
        for i, (c, p) in enumerate(zip(self.chrom, self.pos)):
            out.setdefault((str(c), int(p)), []).append(i)
        return out

    def alt_freq(self, mask: np.ndarray | None = None) -> np.ndarray:
        d = self.dosages if mask is None else self.dosages[:, mask]
        valid = d >= 0
        return np.where(valid.sum(1) > 0, np.where(valid, d, 0).sum(1) / (2 * np.maximum(valid.sum(1), 1)), np.nan)


def load_samples() -> list[dict]:
    with urllib.request.urlopen(PANEL_URL, timeout=60) as resp:
        text = resp.read().decode()
    rows = [line.split("\t") for line in text.strip().splitlines()[1:]]
    return [{"sample": r[0], "pop": r[1], "superpop": r[2], "sex": r[3].strip()} for r in rows]


def _parse_record(line: str, allow_indels: bool = False) -> dict | None:
    cols = line.rstrip("\n").split("\t")
    ref, alt = cols[3], cols[4]
    if "," in alt or not ref or not alt or set(ref + alt) - set("ACGT"):
        return None  # biallelic, plain-sequence alleles only (no symbolic/structural alleles)
    if (len(ref) != 1 or len(alt) != 1) and not allow_indels:
        return None  # SNV-only panels (PCA)
    gts = cols[9:]
    first = np.frombuffer("".join(g[0] for g in gts).encode(), dtype=np.uint8)
    second = np.frombuffer("".join(g[2] if len(g) > 2 else g[0] for g in gts).encode(), dtype=np.uint8)
    missing = (first == ord(".")) | (second == ord("."))
    dos = (first == ord("1")).astype(np.int8) + (second == ord("1")).astype(np.int8)
    dos[missing] = -1
    haploid = np.array([len(g) == 1 for g in gts])
    dos[haploid & ~missing] = (first[haploid & ~missing] == ord("1")).astype(np.int8) * 2  # chrX males, not used
    return {"chrom": cols[0], "pos": int(cols[1]), "id": cols[2], "ref": ref, "alt": alt, "dosages": dos}


def _fetch_chunk(chrom: str, positions: list[int], retries: int = 4, allow_indels: bool = False) -> list[dict]:
    import pysam  # optional dependency, only for rebuilding

    for attempt in range(retries):
        try:
            vf = pysam.VariantFile(VCF_URL.format(chrom=chrom))
            out = []
            for pos in positions:
                for rec in vf.fetch(chrom, pos - 1, pos):
                    if rec.pos == pos:
                        parsed = _parse_record(str(rec), allow_indels)
                        if parsed:
                            out.append(parsed)
            vf.close()
            return out
        except (OSError, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    return []


def _window_pick(chrom: str, windows: list[tuple[int, int]], allowed_ids: frozenset, min_maf: float,
                 retries: int = 4) -> list[dict]:
    """For each window, the first biallelic, non-palindromic SNV with an allowed rsID and MAF >= min_maf."""
    import pysam

    for attempt in range(retries):
        try:
            vf = pysam.VariantFile(VCF_URL.format(chrom=chrom))
            out = []
            for start, end in windows:
                for rec in vf.fetch(chrom, start, end):
                    if rec.id not in allowed_ids:
                        continue
                    parsed = _parse_record(str(rec))
                    if not parsed or {parsed["ref"], parsed["alt"]} in ({"A", "T"}, {"C", "G"}):
                        continue
                    d = parsed["dosages"]
                    valid = d >= 0
                    af = d[valid].sum() / (2 * valid.sum()) if valid.any() else 0.0
                    if min(af, 1 - af) >= min_maf:
                        out.append(parsed)
                        break
            vf.close()
            return out
        except (OSError, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    return []


def fetch_windows(windows: list[tuple[str, int, int]], allowed_ids: set[str], min_maf: float, threads: int = 12,
                  chunk: int = 20, log=print) -> list[dict]:
    by_chrom: dict[str, list[tuple[int, int]]] = {}
    for c, s, e in windows:
        by_chrom.setdefault(c, []).append((s, e))
    jobs = [(c, ws[i:i + chunk]) for c, ws in by_chrom.items() for i in range(0, len(ws), chunk)]
    allowed = frozenset(allowed_ids)
    records: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(_window_pick, c, ws, allowed, min_maf) for c, ws in jobs]
        for n, fut in enumerate(cf.as_completed(futures), 1):
            records.extend(fut.result())
            if n % 25 == 0 or n == len(jobs):
                log(f"  windows: {n}/{len(jobs)} chunks, {len(records)} sites", flush=True) if log is print \
                    else log(f"  windows: {n}/{len(jobs)} chunks, {len(records)} sites")
    return sorted(records, key=lambda r: (int(r["chrom"]), r["pos"]))


def fetch_sites(sites: list[Site], threads: int = 12, chunk: int = 40, log=print,
                allow_indels: bool = False) -> list[dict]:
    """Fetch every biallelic SNV (and indel if allowed) at the requested GRCh37 positions (deduplicated)."""
    by_chrom: dict[str, list[int]] = {}
    for s in sorted(set(sites), key=lambda s: (s.chrom, s.pos)):
        by_chrom.setdefault(s.chrom, []).append(s.pos)
    jobs = [(c, ps[i:i + chunk]) for c, ps in by_chrom.items() for i in range(0, len(ps), chunk)]
    records: list[dict] = []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(_fetch_chunk, c, ps, 4, allow_indels) for c, ps in jobs]
        for fut in cf.as_completed(futures):
            records.extend(fut.result())
            done += 1
            if done % 20 == 0 or done == len(jobs):
                log(f"  fetched {done}/{len(jobs)} chunks, {len(records)} records")
    seen, unique = set(), []
    def order(r):
        return (int(r["chrom"]) if r["chrom"].isdigit() else 99, r["pos"], r["ref"], r["alt"])

    for r in sorted(records, key=order):
        key = (r["chrom"], r["pos"], r["ref"], r["alt"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def save_panel(path: Path, records: list[dict], samples: list[dict], meta: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {
        "dosages": np.vstack([r["dosages"] for r in records]).astype(np.int8) if records
        else np.zeros((0, len(samples)), np.int8),
        "chrom": np.array([r["chrom"] for r in records]), "pos": np.array([r["pos"] for r in records], np.int64),
        "ids": np.array([r["id"] for r in records]), "ref": np.array([r["ref"] for r in records]),
        "alt": np.array([r["alt"] for r in records]),
        "samples": np.array([s["sample"] for s in samples]), "pop": np.array([s["pop"] for s in samples]),
        "superpop": np.array([s["superpop"] for s in samples]), "sex": np.array([s["sex"] for s in samples]),
    }
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    content = buf.getvalue()
    path.write_bytes(content)
    meta = dict(meta, n_variants=len(records), n_samples=len(samples), build=BUILD, source=BASE_URL,
                sha256=hashlib.sha256(content).hexdigest())
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def load_panel(path: Path) -> ReferencePanel:
    with np.load(path, allow_pickle=False) as z:
        arrays = {k: z[k] for k in z.files}
    meta_path = Path(path).with_suffix(".json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    return ReferencePanel(meta=meta, **arrays)


def merge_panels(*panels: ReferencePanel) -> ReferencePanel:
    """Union of sites across panels built from the same sample list (first occurrence wins)."""
    base = panels[0]
    for p in panels[1:]:
        if not np.array_equal(p.samples, base.samples):
            raise ValueError("panels were built from different sample lists")
    keep: dict[tuple, tuple[int, int]] = {}
    for pi, p in enumerate(panels):
        for i, key in enumerate(zip(p.chrom, p.pos, p.ref, p.alt)):
            keep.setdefault(tuple(map(str, key)), (pi, i))
    order = sorted(keep.items(), key=lambda kv: (int(kv[0][0]) if kv[0][0].isdigit() else 99, int(kv[0][1])))
    rows = [panels[pi] for _, (pi, _) in order]
    idx = [i for _, (_, i) in order]

    def col(name):
        return np.array([getattr(p, name)[i] for p, i in zip(rows, idx)])

    return ReferencePanel(
        dosages=np.vstack([p.dosages[i] for p, i in zip(rows, idx)]) if idx else base.dosages[:0],
        chrom=col("chrom"), pos=col("pos"), ids=col("ids"), ref=col("ref"), alt=col("alt"),
        samples=base.samples, pop=base.pop, superpop=base.superpop, sex=base.sex,
        meta={"merged_from": [p.meta.get("name") for p in panels]})


def read_chip_sites(paths: list[Path]) -> dict[str, tuple[str, int]]:
    """rsID -> (chrom, pos) for sites assayed on every given 23andMe-format file (chip content only)."""
    common: dict[str, tuple[str, int]] | None = None
    for path in paths:
        sites: dict[str, tuple[str, int]] = {}
        with gzip.open(path, "rt") if str(path).endswith(".gz") else open(path) as fh:
            for line in fh:
                if line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 4 or not parts[0].startswith("rs") or not parts[2].isdigit():
                    continue
                sites[parts[0]] = (parts[1], int(parts[2]))
        common = sites if common is None else {k: v for k, v in common.items() if sites.get(k) == v}
    return common or {}


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
