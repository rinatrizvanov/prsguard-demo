import type { ReactNode } from "react";
import { reasonMeaning } from "@/lib/glossary";
import { IconAgent, IconBlock, IconCheck, IconDash, IconGear, IconHalf, IconQuestion, IconWave, IconX } from "./Icons";

const STATUS_TEXT: Record<string, string> = {
  SUPPORTED: "SUPPORTED",
  RAW_ONLY: "RAW ONLY",
  ABSTAIN: "ABSTAIN",
  RESOLVED: "RESOLVED",
  INTERMEDIATE: "INTERMEDIATE",
  UNSTABLE: "UNSTABLE",
  UNRESOLVED: "UNRESOLVED",
  CONSISTENT: "CONSISTENT",
  DISCORDANT: "DISCORDANT",
  NOT_COMPARABLE: "NOT COMPARABLE",
  pass: "pass",
  fail: "fail",
  not_applicable: "n/a",
};

function statusIcon(status: string, size: number): ReactNode {
  switch (status) {
    case "SUPPORTED":
    case "RESOLVED":
    case "CONSISTENT":
    case "pass":
      return <IconCheck size={size} />;
    case "RAW_ONLY":
    case "INTERMEDIATE":
      return <IconHalf size={size} />;
    case "UNSTABLE":
      return <IconWave size={size} />;
    case "ABSTAIN":
      return <IconBlock size={size} />;
    case "UNRESOLVED":
      return <IconQuestion size={size} />;
    case "DISCORDANT":
    case "fail":
      return <IconX size={size} />;
    default:
      return <IconDash size={size} />;
  }
}

/** Status badge: icon + text + colour (never colour alone). */
export function StatusBadge({
  status,
  size = "md",
  title,
  children,
}: {
  status: string;
  size?: "md" | "lg";
  title?: string;
  children?: ReactNode;
}) {
  const known = status in STATUS_TEXT;
  return (
    <span className={`badge ${known ? status : "neutral"} ${size === "lg" ? "lg" : ""}`} title={title}>
      {statusIcon(status, size === "lg" ? 18 : 13)}
      {children ?? STATUS_TEXT[status] ?? status}
    </span>
  );
}

export function ActorBadge({ actor }: { actor: string }) {
  if (actor === "AGENT_ACTION") {
    return (
      <span className="badge agent">
        <IconAgent size={13} />
        AGENT ACTION
      </span>
    );
  }
  return (
    <span className="badge det">
      <IconGear size={13} />
      DETERMINISTIC DECISION
    </span>
  );
}

export function SyntheticBadge({ synthetic }: { synthetic: boolean | null | undefined }) {
  if (synthetic) {
    return (
      <span className="badge synthetic" title="This case uses synthetic (made-up) data.">
        SYNTHETIC DATA
      </span>
    );
  }
  return null;
}

/** A reason code with its glossary meaning as a tooltip and accessible description. */
export function CodeChip({ code }: { code: string }) {
  const meaning = reasonMeaning(code);
  return (
    <span className="code-chip" title={meaning}>
      {code}
      {meaning !== code ? <span className="visually-hidden">: {meaning}</span> : null}
    </span>
  );
}

export function CodeList({ codes, empty = "none" }: { codes: string[] | null | undefined; empty?: string }) {
  if (!codes || codes.length === 0) return <span className="muted">{empty}</span>;
  return (
    <span className="code-list">
      {codes.map((c) => (
        <CodeChip key={c} code={c} />
      ))}
    </span>
  );
}

export function ContextOnlyLabel({ children }: { children?: ReactNode }) {
  return <span className="ctx-label">{children ?? "CONTEXT ONLY — never used by the applicability gate"}</span>;
}
