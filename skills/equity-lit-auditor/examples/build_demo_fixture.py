#!/usr/bin/env python3
"""Build the synthetic Europe PMC fixture used by --demo and the tests.

Every record is SYNTHETIC: titles, abstracts, authors and identifiers are
invented to exercise the pipeline (search -> citation cascade -> extraction ->
scoring -> map). Source is "DEMO" so no identifier can collide with a real
PubMed or PMC record. Do not cite these.
"""

import json
from pathlib import Path


def rec(pid, title, abstract, year, affs, seed=False, oa=False, pmcid="", cited=0, mesh=()):
    return {
        "id": pid, "source": "DEMO", "pmid": "", "pmcid": pmcid, "doi": "",
        "title": f"[SYNTHETIC] {title}", "abstractText": abstract, "pubYear": str(year),
        "authorString": "Synthetic A, Demo B, Example C.",
        "journalInfo": {"journal": {"title": "Synthetic Journal of Genomics"}},
        "isOpenAccess": "Y" if oa else "N", "citedByCount": cited,
        "authorList": {"author": [
            {"fullName": f"Author {i}", "authorAffiliationDetailsList": {"authorAffiliation": [{"affiliation": a}]}}
            for i, a in enumerate(affs)
        ]},
        "meshHeadingList": {"meshHeading": [{"descriptorName": m} for m in mesh]},
        "seed": seed,
    }


R = {}


def add(r):
    R[f"DEMO:{r['id']}"] = r


add(rec("D001", "Genome-wide association study of type 2 diabetes in a large European biobank",
        "We performed a genome-wide association study of type 2 diabetes in 452,264 individuals of European "
        "ancestry from the UK Biobank. Imputation used the Haplotype Reference Consortium panel. We identified "
        "112 loci. Because our sample was restricted to European participants, findings may not generalize to "
        "other populations.", 2019,
        ["Department of Medicine, Oxford, United Kingdom", "Institute of Genetics, Boston, MA, USA"],
        seed=True, cited=812))
add(rec("D002", "Multi-ancestry meta-analysis of type 2 diabetes across five continental groups",
        "We conducted a multi-ancestry meta-analysis of type 2 diabetes including 180,834 individuals of European "
        "ancestry, 77,418 East Asian participants, 56,092 African Americans, 33,217 Hispanic/Latino participants "
        "and 24,500 South Asian participants. Genetic ancestry was inferred from principal components. "
        "Participants were drawn from the Million Veteran Program and partner cohorts. Several loci showed "
        "ancestry-specific effects, and polygenic scores across ancestries showed reduced accuracy in African "
        "ancestry groups, underscoring the underrepresentation of non-European populations.", 2022,
        ["Department of Epidemiology, Philadelphia, PA, USA", "Genome Centre, Tokyo, Japan",
         "School of Public Health, Accra, Ghana"], seed=True, oa=True, pmcid="PMCDEMO002", cited=341))
add(rec("D003", "Genetic architecture of kidney function in the Uganda Genome Resource",
        "We genotyped 6,407 Ugandan individuals from the Uganda Genome Resource and performed genome-wide "
        "association analysis of eGFR. Community engagement meetings were held with village leaders before "
        "recruitment and results were returned to communities. Two novel loci were identified that are rare "
        "outside Africa.", 2021,
        ["Medical Research Council Unit, Entebbe, Uganda", "Department of Genetics, Kampala, Uganda",
         "Wellcome Institute, Hinxton, United Kingdom"], seed=True, cited=97))
add(rec("D004", "Sequencing study of hypertension genes in Nigerian adults",
        "Whole-exome sequencing was performed in 1,850 Nigerian adults recruited in Ibadan, Nigeria. "
        "We identified rare variants in three genes associated with blood pressure.", 2020,
        ["Department of Cardiology, Chicago, IL, USA", "Genome Institute, Toronto, Canada"],
        seed=True, cited=41))
add(rec("D005", "Candidate gene association of APOE with cognitive decline",
        "We genotyped 3,120 Caucasian subjects for APOE and tested association with cognitive decline over "
        "ten years. The e4 allele increased risk.", 2008,
        ["Department of Neurology, Munich, Germany"], seed=True, cited=150))
add(rec("D006", "Genome-wide association of height in Japanese participants from BioBank Japan",
        "A genome-wide association study of adult height was conducted in 191,787 Japanese participants from "
        "BioBank Japan. Population-specific variants explained additional heritability.", 2020,
        ["Center for Integrative Medical Sciences, Yokohama, Japan"], seed=True, cited=210))
add(rec("D007", "Exome sequencing in the Qatar Biobank",
        "We analysed whole-exome sequencing data from 6,045 Qatari individuals from the Qatar Biobank, "
        "a Middle Eastern population that is underrepresented in reference databases.", 2021,
        ["Research Division, Doha, Qatar"], seed=True, cited=33))
add(rec("D008", "Genetic risk for coronary disease in South Asian British participants",
        "Genes & Health recruited 44,190 British Bangladeshi and Pakistani participants in east London. "
        "Polygenic risk scores derived in Europeans performed worse, highlighting limited transferability of "
        "polygenic scores across ancestries.", 2023,
        ["Blizard Institute, London, United Kingdom"], seed=True, cited=18))
add(rec("D009", "Admixture mapping of asthma in Hispanic/Latino children",
        "Admixture mapping and local ancestry analysis were performed in 3,902 Mexican and Puerto Rican children "
        "from the United States and Mexico. Self-reported ethnicity and genetic ancestry were both recorded.", 2018,
        ["Department of Medicine, San Francisco, CA, USA", "Instituto Nacional, Mexico City, Mexico"],
        seed=True, cited=76))
# Papers reached only through the cascade
add(rec("D101", "A toolset for whole-genome association analysis",
        "We describe software for efficient association testing and data management.", 2007,
        ["Center for Human Genetic Research, Boston, MA, USA"], cited=30000))
add(rec("D102", "Genome-wide association of type 2 diabetes in Finnish individuals",
        "A GWAS of type 2 diabetes in 29,193 Finnish individuals from FinnGen identified founder variants.", 2020,
        ["Institute for Molecular Medicine, Helsinki, Finland"], cited=120))
add(rec("D103", "Type 2 diabetes genetics in Chinese adults from the China Kadoorie Biobank",
        "We studied 100,640 Chinese adults from the China Kadoorie Biobank and replicated 40 loci.", 2021,
        ["Peking University, Beijing, China", "Nuffield Department, Oxford, United Kingdom"], cited=64))
add(rec("D104", "Polygenic prediction of diabetes in Ghanaian and Kenyan adults",
        "We evaluated the portability of polygenic scores in 4,210 Ghanaian adults and 2,975 Kenyan adults. "
        "Capacity-building for local researchers was a core aim.", 2024,
        ["University of Ghana, Accra, Ghana", "KEMRI, Nairobi, Kenya"], cited=5))
add(rec("D201", "Development of a polygenic score for type 2 diabetes",
        "We developed a polygenic score for type 2 diabetes using 112 loci and trained it in 20,000 individuals "
        "of European ancestry from the UK Biobank.", 2020,
        ["Department of Medicine, Oxford, United Kingdom"], cited=60))
add(rec("D105", "Review: the diversity gap in genomics",
        "This review discusses why genomics research remains Eurocentric and proposes remedies.", 2019,
        ["Department of Genetics, Stanford, CA, USA"], cited=900))

# ---------------------------------------------------------------------------
# Synthetic PGS Catalog block (shape of https://www.pgscatalog.org/rest/).
# IDs use the PGSDEMO prefix so they can never be mistaken for real scores.
# Publications point at demo papers through 'PMID': 'DEMO:Dxxx' (fixture-only
# convention); D202 and D203 are deliberately absent from the Europe PMC
# records to exercise the stub-paper path.
# ---------------------------------------------------------------------------
def pub(pid, title, year, first="Synthetic A"):
    return {"id": f"PGP{pid}", "PMID": f"DEMO:{pid}", "doi": "", "title": f"[SYNTHETIC] {title}",
            "journal": "Synthetic Journal of Genomics", "firstauthor": first, "date_publication": f"{year}-01-01"}


def smp(n, broad, country="", cohorts=(), source=None):
    d = {"sample_number": n, "ancestry_broad": broad, "ancestry_country": country,
         "cohorts": [{"name_short": c} for c in cohorts]}
    if source:
        d["source_PMID"] = f"DEMO:{source}"
    return d


T2D = [{"id": "EFO_0001360", "label": "type II diabetes mellitus"}]
pgs = {
    "traits": [{"id": "EFO_0001360", "label": "type II diabetes mellitus",
                "associated_pgs_ids": ["PGSDEMO01", "PGSDEMO02", "PGSDEMO03"]}],
    "scores": {
        "PGSDEMO01": {"id": "PGSDEMO01", "name": "T2D_PRS_112", "trait_reported": "Type 2 diabetes", "trait_efo": T2D,
                      "variants_number": 112,
                      "publication": pub("D201", "Development of a polygenic score for type 2 diabetes", 2020),
                      "samples_variants": [smp(452264, "European", "U.K.", ["UKB"], source="D001")],
                      "samples_training": [smp(20000, "European", "U.K.", ["UKB"])]},
        "PGSDEMO02": {"id": "PGSDEMO02", "name": "T2D_multiancestry", "trait_reported": "Type 2 diabetes",
                      "trait_efo": T2D, "variants_number": 1289000,
                      "publication": pub("D002", "Multi-ancestry meta-analysis of type 2 diabetes across five continental groups", 2022),
                      "samples_variants": [
                          smp(180834, "European", "U.S.", ["MVP"], source="D002"),
                          smp(77418, "East Asian", "Japan", ["BBJ"], source="D002"),
                          smp(56092, "African American or Afro-Caribbean", "U.S.", ["MVP"], source="D002"),
                          smp(33217, "Hispanic or Latin American", "U.S.", ["MVP"], source="D002"),
                          smp(24500, "South Asian", "India", source="D002")],
                      "samples_training": [smp(12000, "Multi-ancestry (including European)", "U.S.", ["MVP"])]},
        "PGSDEMO03": {"id": "PGSDEMO03", "name": "T2D_FIN", "trait_reported": "Type 2 diabetes", "trait_efo": T2D,
                      "variants_number": 40,
                      "publication": pub("D203", "A Finnish polygenic score for type 2 diabetes", 2021),
                      "samples_variants": [smp(29193, "European", "Finland", ["FinnGen"], source="D102")],
                      "samples_training": [smp(5000, "Not reported")]},
    },
    "performance": {
        "PGSDEMO01": [
            {"id": "PPMDEMO1", "publication": pub("D104", "Polygenic prediction of diabetes in Ghanaian and Kenyan adults", 2024),
             "sampleset": {"id": "PSSDEMO1", "samples": [smp(4210, "Sub-Saharan African", "Ghana"),
                                                         smp(2975, "Sub-Saharan African", "Kenya")]}},
            {"id": "PPMDEMO2", "publication": pub("D202", "Evaluation of a type 2 diabetes polygenic score in Japanese adults", 2023),
             "sampleset": {"id": "PSSDEMO2", "samples": [smp(15000, "East Asian", "Japan", ["BBJ"])]}},
        ],
        "PGSDEMO02": [
            {"id": "PPMDEMO3", "publication": pub("D008", "Genetic risk for coronary disease in South Asian British participants", 2023),
             "sampleset": {"id": "PSSDEMO3", "samples": [smp(44190, "South Asian", "U.K.", ["G&H"])]}},
        ],
    },
}

fulltext = {
    "PMCDEMO002": (
        "<article><body>"
        "<sec><title>Introduction</title><p>Previous studies in Europeans and in Iceland have ...</p></sec>"
        "<sec sec-type='methods'><title>Methods</title>"
        "<sec><title>Study participants</title><p>Participants were recruited in the United States, Japan, "
        "Ghana and India. The Ghanaian arm included 3,400 Ghanaian adults recruited in Accra. "
        "The South Asian arm comprised 24,500 Indian participants.</p></sec></sec>"
        "<sec><title>Discussion</title><p>Future work in Brazil is needed.</p></sec>"
        "</body></article>"
    )
}

refs = {
    "DEMO:D001": [{"id": "D101", "source": "DEMO"}, {"id": "D102", "source": "DEMO"}],
    "DEMO:D002": [{"id": "D001", "source": "DEMO"}, {"id": "D103", "source": "DEMO"}, {"id": "D101", "source": "DEMO"}],
}
cites = {
    "DEMO:D001": [{"id": "D002", "source": "DEMO"}, {"id": "D105", "source": "DEMO"}],
    "DEMO:D002": [{"id": "D104", "source": "DEMO"}],
}

out = {"_note": "SYNTHETIC demo data for equity-lit-auditor. Not real publications.",
       "search": {}, "records": R, "pgs": pgs, "references": refs, "citations": cites, "fulltext": fulltext}
Path(__file__).with_name("demo_epmc_fixture.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
print(f"{len(R)} synthetic records written")
