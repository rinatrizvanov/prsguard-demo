import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ResearchBanner, SiteFooter, SiteHeader } from "@/components/SiteChrome";

export const metadata: Metadata = {
  title: {
    default: "PRSGuard — can this PGS result be interpreted for this person?",
    template: "%s · PRSGuard",
  },
  description:
    "Research prototype: a trait-first, evidence-aware polygenic score router. Orchestration gathers evidence and calls tools; deterministic code decides what claims are allowed. Not a medical device.",
  robots: { index: true, follow: true },
  referrer: "no-referrer",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#f5f5f2",
  colorScheme: "light",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <ResearchBanner />
        <SiteHeader />
        <main id="main" className="container">
          {children}
        </main>
        <SiteFooter />
      </body>
    </html>
  );
}
