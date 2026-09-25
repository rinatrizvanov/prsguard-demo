export const metadata = { title: "PRSGuard", description: "Whose genome does this PRS fail on?" };

const css = `
:root { color-scheme: light dark; --bg:#f7f7f5; --fg:#1d1d1b; --muted:#6b6b66; --card:#ffffff; --line:#e2e2dc;
  --ok:#1f7a3f; --okbg:#e6f4ea; --warn:#8a5a00; --warnbg:#fff4d6; --bad:#a3231d; --badbg:#fde8e6; }
@media (prefers-color-scheme: dark) { :root { --bg:#141413; --fg:#ecece8; --muted:#a3a39c; --card:#1e1e1c;
  --line:#33332f; --okbg:#10301c; --warnbg:#3a2c05; --badbg:#3d1412; --ok:#7fd49b; --warn:#f0c14b; --bad:#ff8a80; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, -apple-system, Segoe UI, sans-serif; }
main { max-width: 1120px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 26px; margin: 0 0 4px; } h2 { font-size: 18px; margin: 28px 0 10px; }
.muted { color: var(--muted); } .mono { font-family: ui-monospace, Menlo, monospace; font-size: 12.5px; word-break: break-all; }
.grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px; }
.card.ABSTAIN { border: 2px solid var(--bad); background: var(--badbg); }
.card.RAW_SCORE_ONLY { border: 2px solid var(--warn); background: var(--warnbg); }
.card.refused { border: 2px solid var(--bad); }
.card.ABSTAIN, .card.RAW_SCORE_ONLY { color: var(--fg); }
.badge { display:inline-block; font-weight:700; font-size:12.5px; padding:3px 9px; border-radius:999px; letter-spacing:.02em; }
.PERCENTILE_SUPPORTED { color:var(--ok); background:var(--okbg); }
.RAW_SCORE_ONLY { color:var(--warn); background:var(--warnbg); }
.ABSTAIN { color:var(--bad); background:var(--badbg); }
.kv { display:grid; grid-template-columns: 130px 1fr; gap: 4px 10px; margin-top: 10px; font-size: 14px; }
.kv dt { color: var(--muted); } .kv dd { margin: 0; }
.primary { border-left: 5px solid var(--ok); }
.note { border: 1px dashed var(--bad); padding: 10px 12px; border-radius: 8px; margin-top: 24px; }
main { max-width: 1080px; padding: 40px 20px 56px; }
.hero { margin-bottom: 32px; } .hero h1 { font-size: 34px; margin: 0; }
.trait { font-size: 20px; color: var(--muted); margin: 2px 0 14px; }
.primaryline { font-size: 22px; } .hero p { margin: 8px 0 0; font-size: 16px; }
.grid { grid-template-columns: repeat(auto-fit, minmax(310px, 1fr)); gap: 22px; }
.card { padding: 22px; } .card h3 { margin: 4px 0 10px; font-size: 19px; }
.reason { margin: 14px 0 6px; font-size: 15px; }
.small { font-size: 13px; }
details { margin-top: 16px; } summary { cursor: pointer; color: var(--muted); font-size: 14px; }
details .kv { grid-template-columns: 120px 1fr; }
.banner { margin: 28px 0; padding: 14px 18px; border-radius: 10px; border: 1px solid var(--line); background: var(--card); font-size: 16px; }
.banner.NOT_COMPARABLE, .banner.UNSTABLE { border-color: var(--warn); background: var(--warnbg); }
.banner.STABLE { border-color: var(--ok); background: var(--okbg); }
.selection { margin-top: 8px; font-size: 15px; }
.disclaimer { margin-top: 40px; font-size: 11.5px; color: var(--muted); }
table { border-collapse: collapse; width: 100%; font-size: 14px; } td, th { border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left; }
`;

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head><style>{css}</style></head>
      <body>{children}</body>
    </html>
  );
}
