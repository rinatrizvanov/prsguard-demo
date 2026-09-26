import { Workbench } from "@/components/Workbench";
import { IconBook, IconGlobe, IconInfo, IconLock, IconShield, IconSnowflake } from "@/components/Icons";

const HERO_QUESTION = "Can this PGS result actually be interpreted for this person?";

export default function HomePage() {
  return (
    <>
      <section className="hero" aria-labelledby="hero-q">
        <p className="eyebrow">PRSGuard · trait-first, evidence-aware polygenic score routing</p>
        <h1 id="hero-q">{HERO_QUESTION}</h1>
        <p className="thesis">
          PRSGuard decides not only which polygenic score can be <em>calculated</em> from a genotype file, but whether
          its interpretation is <em>supported</em> for this individual. Orchestration (an LLM agent or the scripted
          PRSGuard CLI) gathers evidence and calls tools; deterministic code alone decides what claims are allowed.
        </p>
        <ul className="principles" aria-label="Principles">
          <li>
            <IconShield size={16} />
            <span>
              <strong>No percentile is released unless the evidence gate supports it.</strong> Each score is SUPPORTED,
              RAW_ONLY or ABSTAIN.
            </span>
          </li>
          <li>
            <IconSnowflake size={16} />
            <span>
              Candidate scores are chosen from the PGS Catalog and frozen before any personal genotype is scored.
            </span>
          </li>
          <li>
            <IconInfo size={16} />
            <span>
              <strong>Genetic reference placement is not ethnicity or identity.</strong> It only selects a reference
              distribution.
            </span>
          </li>
          <li>
            <IconGlobe size={16} />
            <span>
              <strong>Geography is not ancestry:</strong> recruitment countries show where study participants were
              enrolled.
            </span>
          </li>
          <li>
            <IconBook size={16} />
            <span>
              Literature equity and F<sub>ST</sub> are <strong>CONTEXT ONLY</strong> — never used by the applicability
              gate.
            </span>
          </li>
          <li>
            <IconLock size={16} />
            <span>Absolute risk is never provided. Genotype files never reach this website.</span>
          </li>
        </ul>
      </section>

      <noscript>
        <p className="error-box">
          This interface needs JavaScript to load the demo results. The methodology is described on the “How PRSGuard
          works” page, which works without JavaScript.
        </p>
      </noscript>

      <Workbench />
    </>
  );
}
