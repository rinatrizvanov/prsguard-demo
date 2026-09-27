"""PRSGuard command line.

    prsguard run --genotype FILE --trait "breast cancer" --sex female [--build GRCh37] --out DIR
    prsguard route --trait "breast cancer" --sex female --build GRCh37 --out candidates.frozen.json
    prsguard demo [--case A ... | --all] [--out runs/demo]
    prsguard make-demo-data
    prsguard serve [--port 8765]          # local-only API for the web interface

Catalog access defaults to the committed snapshot (offline, reproducible); ``--catalog live`` queries the PGS
Catalog REST API and records every response into the snapshot directory. Genotypes are never sent anywhere.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from prsguard import catalog, router
from prsguard.clawbio_env import REPO_ROOT

DEMO_CANDIDATES = REPO_ROOT / "data" / "candidate_sets" / "breast_cancer_female_GRCh37.frozen.json"
DEMO_LITERATURE = REPO_ROOT / "data" / "literature" / "breast_cancer_equity_lit.json"


def _run(args) -> int:
    from prsguard.pipeline import RunConfig, run

    cfg = RunConfig(genotype=Path(args.genotype), trait=args.trait, out_dir=Path(args.out), sex=args.sex,
                    declared_build=args.build, catalog_mode=args.catalog,
                    snapshot_dir=Path(args.snapshot), candidates=Path(args.candidates) if args.candidates else None,
                    top_k=args.top_k, max_variants=args.max_variants,
                    literature_context=Path(args.literature) if args.literature else None, command=sys.argv,
                    orchestrated_by=args.orchestrated_by, sample=args.sample,
                    orchestrator_kind="llm_agent" if args.orchestrated_by else "scripted_cli")
    from prsguard.genotypes import GenotypeInputError

    try:
        r = run(cfg)
    except GenotypeInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{r['headline']['answer']}: {r['headline']['text']}")
    for c in r["candidates"]:
        print(f"  {c['pre_rank']:>3} {c['pgs_id']} {c['gate']['status']:<9} {', '.join(c['gate']['reason_codes'])}")
    print(f"cross-PGS {r['cross_pgs']['status']}; primary {r['primary']['pgs_id']}; wrote {cfg.out_dir}/result.json")
    return 0


def _route(args) -> int:
    src = catalog.open_source(args.catalog, Path(args.snapshot))
    cs, _ = router.route(args.trait, src, router.RouterOptions(sex=args.sex, build=args.build,
                                                               max_variants=args.max_variants, top_k=args.top_k),
                         log=print)
    if args.catalog == "live":
        src.save()
    router.write_frozen(cs, Path(args.out))
    print(f"{cs['status']}: {cs.get('n_found')} found, {cs.get('n_eligible')} eligible, selected "
          f"{cs.get('selected')}; digest {cs.get('digest')}")
    return 0 if cs["status"] == "FROZEN" else 2


def _demo(args) -> int:
    from prsguard.pipeline import RunConfig, run

    manifest = json.loads((REPO_ROOT / "data" / "demo" / "cases.json").read_text())
    wanted = {c.upper() for c in args.case} if args.case else {c["id"] for c in manifest["cases"]}
    out_root = Path(args.out)
    index = []
    for case in manifest["cases"]:
        if case["id"] not in wanted:
            continue
        out = out_root / f"case_{case['id']}"
        cfg = RunConfig(genotype=REPO_ROOT / "data" / "demo" / case["file"], trait=case["trait"], out_dir=out,
                        sex=case["sex"], candidates=DEMO_CANDIDATES,
                        literature_context=DEMO_LITERATURE if DEMO_LITERATURE.exists() else None,
                        case={"id": case["id"], "title": case["title"], "provenance": case["provenance"],
                              "synthetic": case["synthetic"], "description": case["description"] + " "
                              + case["derivation"] + ".", "label": case["label"]},
                        command=["prsguard", "demo", "--case", case["id"], "--out", str(out_root)])
        r = run(cfg)
        print(f"case {case['id']} ({case['population']}): {r['headline']['answer']} - "
              + "; ".join(f"{c['pgs_id']} {c['gate']['status']}" for c in r["candidates"])
              + f"; cross-PGS {r['cross_pgs']['status']}")
        index.append({"id": case["id"], "title": case["title"], "answer": r["headline"]["answer"],
                      "result": f"case_{case['id']}/result.json", "label": case["label"]})
        if args.frontend:
            dest = REPO_ROOT / "frontend" / "public" / "demo"
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy(out / "result.json", dest / f"case_{case['id']}.json")
    (out_root / "index.json").write_text(json.dumps({"cases": index}, indent=2) + "\n")
    if args.frontend:
        shutil.copy(REPO_ROOT / "data" / "demo" / "cases.json",
                    REPO_ROOT / "frontend" / "public" / "demo" / "cases.json")
    return 0


def _serve(args) -> int:
    from prsguard import server

    server.serve(args.port, server.DEFAULT_ORIGINS | set(args.allow_origin or []))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="prsguard", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--trait", required=True)
        p.add_argument("--sex", choices=("female", "male"))
        p.add_argument("--catalog", choices=("snapshot", "live"), default="snapshot")
        p.add_argument("--snapshot", default=str(REPO_ROOT / "data" / "catalog_snapshot"))
        p.add_argument("--top-k", type=int, default=3)
        p.add_argument("--max-variants", type=int, default=10_000,
                       help="router E8 engineering constraint (reference panel size); 0 disables")

    p = sub.add_parser("run", help="analyse one genotype file")
    common(p)
    p.add_argument("--genotype", required=True)
    p.add_argument("--build", choices=("GRCh37", "GRCh38", "NCBI36"), help="build declared by the user")
    p.add_argument("--sample", help="VCF sample to analyse (required when the VCF has several sample columns)")
    p.add_argument("--candidates", help="reuse a frozen candidate set (digest verified)")
    p.add_argument("--literature", help="precomputed equity-lit-auditor JSON to attach as context")
    p.add_argument("--orchestrated-by", help="set by an LLM agent driving PRSGuard (e.g. 'LLM agent: <name>'); "
                                             "default: the deterministic scripted PRSGuard CLI orchestrator")
    p.add_argument("--out", required=True)
    p.set_defaults(func=_run)

    p = sub.add_parser("route", help="resolve trait, search, pre-rank and freeze candidates (no genotype)")
    common(p)
    p.add_argument("--build", choices=("GRCh37", "GRCh38"))
    p.add_argument("--out", required=True)
    p.set_defaults(func=_route)

    p = sub.add_parser("demo", help="run the public demo cases A-G")
    p.add_argument("--case", nargs="*")
    p.add_argument("--out", default="runs/demo")
    p.add_argument("--frontend", action="store_true", help="also copy results into frontend/public/demo")
    p.set_defaults(func=_demo)

    p = sub.add_parser("serve", help="local-only analysis server for the web interface (127.0.0.1)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--allow-origin", action="append", help="extra CORS origin (default: localhost:3000, GitHub Pages)")
    p.set_defaults(func=_serve)

    p = sub.add_parser("make-demo-data", help="regenerate data/demo from the reference panels")
    p.set_defaults(func=lambda a: (__import__("prsguard.demo").demo.make(), 0)[1])

    args = ap.parse_args(argv)
    if getattr(args, "max_variants", None) == 0:
        args.max_variants = None
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
