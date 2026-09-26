"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function ResearchBanner() {
  return (
    <div className="research-banner" role="note" aria-label="Research software notice">
      <div className="container">
        <strong>RESEARCH SOFTWARE / PROTOTYPE</strong>
        <span>
          Not a medical device. It does not diagnose, and it never converts a polygenic score into absolute risk.
        </span>
      </div>
    </div>
  );
}

function isActive(pathname: string, href: string): boolean {
  const clean = (p: string) => p.replace(/\/+$/, "") || "/";
  const p = clean(pathname);
  const h = clean(href);
  return h === "/" ? p === "/" || p === "" : p.endsWith(h);
}

export function SiteHeader() {
  const pathname = usePathname() ?? "/";
  const links = [
    { href: "/", label: "Analyse" },
    { href: "/how-it-works/", label: "How PRSGuard works" },
  ];
  return (
    <header className="site-header">
      <div className="container">
        <Link href="/" className="brand" aria-label="PRSGuard home">
          <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 2l8 3.2v6.1c0 5-3.4 8.4-8 10.2-4.6-1.8-8-5.2-8-10.2V5.2z" fill="#15171b" />
            <path
              d="M8 12.2l2.7 2.7L16.2 9"
              stroke="#fff"
              strokeWidth="2"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span>
            PRSGuard <small>evidence-aware PGS routing</small>
          </span>
        </Link>
        <nav className="site-nav" aria-label="Main">
          {links.map((l) => (
            <Link key={l.href} href={l.href} aria-current={isActive(pathname, l.href) ? "page" : undefined}>
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="container">
        <p>
          <strong>PRSGuard</strong> is research software / a prototype, not a medical device. A polygenic score is not a
          diagnosis. Genetic reference placement is not ethnicity or identity. Geography is not ancestry.
        </p>
        <p>
          Demo cases use public, open-access 1000 Genomes phase 3 genotypes; only the set of sites in each file is
          simulated. Score metadata: PGS Catalog (snapshot). World map geometry: world-atlas (ISC licence, © Mike
          Bostock), data from Natural Earth.
        </p>
        <p>
          This static site makes no network requests other than to its own files and, if you start one, to a PRSGuard
          server on 127.0.0.1. No analytics, no cookies.
        </p>
      </div>
    </footer>
  );
}
