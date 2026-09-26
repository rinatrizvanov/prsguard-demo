# PRSGuard web interface

Research interface for PRSGuard, a trait-first, evidence-aware polygenic score (PGS) router. For one person it
answers: **can this PGS result actually be interpreted for this person?** It shows which scores can be calculated,
and whether interpreting them is supported for that individual.

> **Research software / prototype. Not a medical device.** It does not diagnose, and it never converts a polygenic
> score into absolute risk. Genetic reference placement is not ethnicity or identity.

The core rule: *the agent gathers evidence and orchestrates tools; deterministic code decides what claims are
allowed.* The UI only renders what a result JSON releases. It never computes a percentile, standardized score or
risk of its own. A withheld value is shown as **withheld**, together with the gate's reason codes.

## Stack

- Next.js 15 (App Router) with React 19 and strict TypeScript, built as a static export (`output: 'export'`)
- Plain CSS in `app/globals.css`, with hand-written SVG charts (no chart library)
- `d3-geo` and `topojson-client` for the recruitment-country map. The geometry comes from
  [world-atlas](https://github.com/topojson/world-atlas) (ISC licence, see `public/geo/WORLD-ATLAS-LICENSE`).

## Commands

```bash
npm install
npm run dev         # http://localhost:3000
npm run lint        # ESLint (next/core-web-vitals + next/typescript), zero warnings allowed
npm run typecheck   # tsc --noEmit
npm run build       # static export to out/
npm run smoke       # after build: key statements, demo data and release invariants in out/
```

### Building for GitHub Pages

The base path comes from `NEXT_PUBLIC_BASE_PATH`. It is empty by default; for GitHub Pages it is `/prsguard-demo`:

```bash
NEXT_PUBLIC_BASE_PATH=/prsguard-demo npm run build
```

Every static fetch (demo JSON, map geometry) goes through `assetUrl()` in `lib/paths.ts`, which adds the base path.
`public/.nojekyll` is exported too, so GitHub Pages serves `_next/`. Next.js collects anonymous build telemetry
unless you set `NEXT_TELEMETRY_DISABLED=1` (or run `npx next telemetry disable`). Nothing is collected at runtime.

## Data

| Path | What it is |
| --- | --- |
| `public/demo/cases.json` | Index of demo cases A–G (`prsguard.demo_cases.v1`) |
| `public/demo/case_{A..G}.json` | Real pipeline outputs (`prsguard.result.v1`), written by `prsguard demo` |
| `public/geo/countries-110m.json` | world-atlas 1:110m countries (ISO 3166 numeric ids) |
| `lib/geo/iso3.json` | Generated ISO3 → {numeric id, name, centroid}. Rebuild it with `npm run geo:iso3` |
| `lib/types.ts` | TypeScript types for both schemas |

The demo genotypes are public, open-access 1000 Genomes phase 3 calls. Only the set of sites in each file is
simulated (for example, a consumer-array-like subset). Compare **A** with **B**: the same person as a sparse array
and as a WGS-like file.

## Analysing your own file: the local server

The hosted site is static and runs fully on the demo JSONs. To upload a file, and to search traits, you run the
analysis server **on your own machine**:

```bash
prsguard serve            # http://127.0.0.1:8765 (loopback only)
prsguard serve --port 9000
```

The page checks `GET http://127.0.0.1:<port>/api/health`. When the server answers, the "Your file (local)" tab
turns on:

- `GET /api/traits?q=<text>`: trait autocomplete. Only the trait text is sent.
- `POST /api/analyze?trait=&sex=&build=`: the raw file is the request body, and the `X-Filename` header carries its
  name. The response is a `prsguard.result.v1` document, which is shown like a demo case.

With no server, the upload and search controls stay disabled, and the page says: *"Uploads are analysed only by a
PRSGuard server running on your own machine (`prsguard serve`). This website never receives genomic data."*

The server's default CORS allow-list already covers `http://localhost:3000`, `http://127.0.0.1:3000` and the GitHub
Pages origin. To add another origin (for example, a static preview of `out/`), pass
`prsguard serve --allow-origin http://127.0.0.1:4173`.

## Privacy model

- The site is a static export. At runtime it fetches only its own files: the demo results and the map geometry.
- A genotype file goes to only one place: `http://127.0.0.1:<port>`. The host is fixed in `lib/localServer.ts`, and
  only the port can be changed, so the code cannot send a genotype anywhere else.
- The local server writes an upload to a private temporary directory, analyses it, and deletes it after it
  responds. Its only outbound requests carry trait text and PGS IDs to the PGS Catalog.
- The site has no analytics, no cookies, no third-party scripts or fonts, and no secrets. The only environment
  variable it reads is `NEXT_PUBLIC_BASE_PATH`.

## Layout

```
app/                 layout, landing + analysis page, /how-it-works
components/          UI: result header, agent trace, PCA plot, candidate table and evidence tabs,
                     stage chart, world map, literature context, cross-PGS, reproducibility
lib/                 types, formatting, ancestry palette, reason-code glossary, data + local-server clients
scripts/             build-iso3-map.mjs (generator), smoke-check.mjs
public/demo, public/geo
```

## Accessibility

- Semantic landmarks and a skip link are included.
- Tabs follow the WAI-ARIA pattern (arrow keys, Home and End). Expanders are native `<details>` or buttons with
  `aria-expanded`.
- The trait search is an ARIA combobox.
- Status is never shown by colour alone. Every status badge has an icon and a text label, and the PCA plot also
  encodes each reference group by marker shape.
- The categorical palette was checked with a colour-vision-deficiency validator.
- The layout works down to about 380 px wide, and the page itself never scrolls sideways. Wide tables scroll inside
  their own frame.
