# Data, provenance and privacy

## What leaves the machine

| Destination | What is sent | When |
|---|---|---|
| PGS Catalog REST API | trait text, ontology IDs, PGS IDs | `--catalog live`, `prsguard serve` for traits other than the bundled demo, `prsguard route` |
| Europe PMC REST API | PGS IDs / trait text / PMIDs (via equity-lit-auditor) | only when the literature context is (re)generated |
| Ensembl REST, 1000 Genomes FTP | genomic positions of public reference variants | only when reference panels are rebuilt |

**Never sent anywhere:** the person's genotype file, genotypes, scores or results. The static website has no
backend; uploads are analysed only by `prsguard serve`, which binds to 127.0.0.1, rejects non-loopback Host
headers, writes the upload to a private temporary directory and deletes it after the response. Result JSON
contains counts and summary statistics, not per-variant genotypes, and no local file paths.

## Data shipped in this repository

| Path | Content | Source and terms |
|---|---|---|
| `data/reference/1000g_pca.*` | 6,557 SNPs x 2,504 samples (dosages) | 1000 Genomes phase 3 (open access, no restrictions on use); site choice described in the JSON sidecar |
| `data/reference/1000g_pgs.*` | 3,749 SNVs/indels at the demo scores' positions x 2,504 samples | 1000 Genomes phase 3 |
| `data/reference/*_positions.json`, `*_rsids.json` | GRCh38 positions and rsIDs of panel sites | Ensembl REST (GRCh37 and GRCh38) |
| `data/catalog_snapshot/` | recorded PGS Catalog REST responses and harmonised scoring files, each with URL, retrieval time and SHA-256 in `SNAPSHOT.json` | PGS Catalog (EMBL-EBI terms of use; cite Lambert et al. 2021) |
| `data/candidate_sets/` | frozen breast-cancer candidate set (digest-verified) | derived |
| `data/demo/` | 7 demo genomes | real public 1000 Genomes genotypes of named samples; only the *site content* is simulated (array mask, thin file) and every file says so in its header and label |
| `data/literature/` | trimmed equity-lit-auditor output (LIVE, 2026-09-26) | Europe PMC + PGS Catalog; context only |

Nothing in the repository is private genomic data. No result presented as real is synthetic: the demo genomes
are labelled "PUBLIC 1000 GENOMES SAMPLE ... - site content SIMULATED / restricted to panel sites"; the
equity-lit-auditor `--demo` output is labelled SYNTHETIC DEMO everywhere, and the pipeline refuses to attach
synthetic or non-live literature context to a result.

## Reproducibility

Python dependencies are pinned in `uv.lock` (installed by `scripts/setup.sh` with `uv sync --frozen`; CI checks
that the lock matches `pyproject.toml`); frontend dependencies are pinned in `frontend/package-lock.json`.

Every result carries: PRSGuard version, git commit and dirty flag, ClawBio commit (pinned
`0ba950565ee6a0fe9da3bde2164f6c814bd57dc9`), Python and package versions, SHA-256 of the genotype file, both
reference panels, the catalog snapshot manifest and the gate config, the calibration version, the candidate-set
digest, random seeds (placement bootstrap 20260926, reference subset 1000), timestamps, the exact command, and
every gate rule trace (`reproducibility/`). Runs from the snapshot are offline and deterministic apart from
timestamps (tested).
