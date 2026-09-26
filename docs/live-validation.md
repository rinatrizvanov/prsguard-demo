# Live validation (2026-09-26)

Offline tests replay committed snapshots. These runs checked the live public APIs the snapshots came from. Only
trait text, ontology IDs and PGS IDs were sent; no genotype data.

## PGS Catalog (PRSGuard router and auditor)

| Run | Result |
|---|---|
| `RUN_LIVE_TESTS=1 pytest -m network` | 4 passed (PGS Catalog auditor live test + 3 equity-lit live tests) |
| `prsguard route --trait "breast cancer" --sex female --build GRCh37 --catalog live` | term MONDO_0007254 (exact label); scope: breast cancer, breast carcinoma, female breast carcinoma (subtypes excluded); 160 scores found; 149 eligible without the engineering cap, 87 with `--max-variants 10000`; top 3 PGS000004, PGS001804, PGS001336. Recorded into `data/catalog_snapshot` and frozen in `data/candidate_sets/` |
| `prsguard route --trait "type 2 diabetes" --build GRCh37 --catalog live` (throwaway snapshot) | term MONDO_0005148 via exact synonym; 252 scores found; 68 eligible; top 3 PGS000805, PGS000868, PGS000804 |

The type 2 diabetes run found two router bugs that the breast-cancer data could not show: the resolved term's
own Catalog synonyms were not accepted as the outcome ("Type 2 diabetes" vs label "type 2 diabetes mellitus"),
and harmless parentheticals such as "(T2D)" or "(PheCode 250.2)" were treated as sub-phenotypes (the first run
returned 0 eligible). Both fixed, with tests (`tests/test_router.py`).

## Spot checks against the PGS Catalog web pages

| Value | PRSGuard (from the REST API) | pgscatalog.org score page |
|---|---|---|
| PGS000004 source GWAS | 158,648 individuals, 100% European | 158,648 individuals, European 100% |
| PGS000004 development | 10,444 individuals, 100% European | 10,444 individuals, European 100% |
| PGS000004 variants, release | 313, 2019-10-14 | 313, Oct. 14, 2019 |
| PGS000004, PSS003598 (African ancestry, PGP000249) | OR 1.26 [1.10, 1.44]; AUROC 0.55 [0.51, 0.58] | OR 1.26 [1.1, 1.44]; AUROC 0.55 [0.51, 0.58] |
| PGS001804 evaluations | 8 partial-r rows, e.g. European 10,197: 0.1101 [0.0908, 0.1292]; African 1,482: 0.0416 [-0.0097, 0.0927] | identical 8 rows |

The PGS001804 check confirmed a real auditor bug found while analysing the demo results: partial-r has a null
of 0, but the auditor knew nulls only for OR/HR/beta/AUROC, so every PGS001804 evaluation was treated as
uninformative. Fixed (`prsguard/catalog.py`) and covered by the end-to-end demo expectations.

## Europe PMC + PGS Catalog (equity-lit-auditor)

Details in [equity-lit-integration.md](equity-lit-integration.md). Summary of the live runs:

| Run | Result |
|---|---|
| `clawbio.py run equity-lit --pgs-trait "type 2 diabetes"` | 252 scores available, 50 audited; 45 papers; 18 European-only |
| `clawbio.py run equity-lit --pgs-trait "breast cancer"` | 194 scores available, 50 audited; 90 papers; 59 European-only |
| `clawbio.py run equity-lit --query "type 2 diabetes genome-wide association" --max-results 10` | 10 papers, 3 with population data |
| `equity_lit_auditor.py --pgs-ids PGS000004,PGS001804,PGS001336` (context attached to PRSGuard results) | 31 papers, all with population data; 16 European-only; data provenance LIVE |

Seven schema/logic bugs were fixed during the equity-lit live validation (double counting of reused sample
sets, child-trait scores missing, negated ancestry terms, excluded populations counted, silent partial failures,
silent trait fallback, mislabelled ASN stage), plus two found while attaching the context to PRSGuard results
(space-grouped thousands such as "70 877 women" read as 877; "PGS 313 for American women" read as 313 women).
All have offline regression tests.

## End-to-end

`prsguard demo` reproduces all seven demo cases offline (expected outcomes pinned in `tests/test_pipeline.py`);
`prsguard serve` was exercised with an upload (analysed locally, temporary file deleted, spoofed Host header
rejected).
