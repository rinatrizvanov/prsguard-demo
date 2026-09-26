# Example gate inputs

Produced by `prsguard demo` from public 1000 Genomes phase 3 demo genomes (see `data/demo/cases.json` in the
PRSGuard repository). They contain no genotypes: only counts, correlations, placement status and PGS Catalog
metadata. Not synthetic, not private.

| File | Person | Expected status |
|---|---|---|
| `case_B_PGS001336.gate_input.json` | HG00097 (GBR), WGS-like file | SUPPORTED |
| `case_E_PGS000004.gate_input.json` | NA19625 (ASW, admixed), WGS-like file | RAW_ONLY (TARGET_REFERENCE_UNRESOLVED) |
| `case_G_PGS001336.gate_input.json` | NA18939 (JPT), 150-site file | ABSTAIN (LOW_SCOREABILITY, TARGET_REFERENCE_UNRESOLVED) |
