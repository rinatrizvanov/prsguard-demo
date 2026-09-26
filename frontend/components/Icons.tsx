/** Small inline SVG icons (decorative: aria-hidden; meaning is always carried by adjacent text). */

interface IconProps {
  size?: number;
  className?: string;
}

function Svg({ size = 14, className, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      {children}
    </svg>
  );
}

export function IconCheck(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="8" cy="8" r="6.5" />
      <path d="M5 8.2l2 2 4-4.4" />
    </Svg>
  );
}

export function IconHalf(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="8" cy="8" r="6.5" />
      <path d="M8 1.5v13A6.5 6.5 0 0 1 8 1.5z" fill="currentColor" stroke="none" />
    </Svg>
  );
}

export function IconBlock(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="8" cy="8" r="6.5" />
      <path d="M3.5 12.5l9-9" />
    </Svg>
  );
}

export function IconDash(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="8" cy="8" r="6.5" />
      <path d="M5 8h6" />
    </Svg>
  );
}

export function IconQuestion(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="8" cy="8" r="6.5" />
      <path d="M6.2 6.2a1.9 1.9 0 1 1 2.6 1.8c-.5.2-.8.6-.8 1.1v.4" />
      <circle cx="8" cy="11.6" r=".4" fill="currentColor" />
    </Svg>
  );
}

export function IconWave(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="8" cy="8" r="6.5" />
      <path d="M4.5 8.5c1-1.6 2-1.6 3 0s2 1.6 3 0" />
    </Svg>
  );
}

export function IconX(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="8" cy="8" r="6.5" />
      <path d="M5.6 5.6l4.8 4.8M10.4 5.6l-4.8 4.8" />
    </Svg>
  );
}

export function IconInfo(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="8" cy="8" r="6.5" />
      <path d="M8 7.2v4" />
      <circle cx="8" cy="4.9" r=".4" fill="currentColor" />
    </Svg>
  );
}

export function IconLock(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="3" y="7" width="10" height="7" rx="1.5" />
      <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
    </Svg>
  );
}

export function IconAgent(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M8 1.8l1.4 3.4 3.4 1.4-3.4 1.4L8 11.4 6.6 8 3.2 6.6l3.4-1.4z" />
      <path d="M12.5 11l.6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4-1.4-.6 1.4-.6z" />
    </Svg>
  );
}

export function IconGear(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="2.5" y="2.5" width="11" height="11" rx="2" />
      <path d="M5.5 6h5M5.5 8h5M5.5 10h3" />
    </Svg>
  );
}

export function IconBook(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M2.5 3.5c2-.8 3.8-.8 5.5.5v9.5c-1.7-1.3-3.5-1.3-5.5-.5z" />
      <path d="M13.5 3.5c-2-.8-3.8-.8-5.5.5v9.5c1.7-1.3 3.5-1.3 5.5-.5z" />
    </Svg>
  );
}

export function IconSnowflake(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M8 1.5v13M2.4 4.75l11.2 6.5M2.4 11.25l11.2-6.5" />
      <path d="M6.5 2.8L8 4.2l1.5-1.4M6.5 13.2L8 11.8l1.5 1.4" />
    </Svg>
  );
}

export function IconGlobe(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="8" cy="8" r="6.5" />
      <path d="M1.5 8h13M8 1.5c2 2.2 2 10.8 0 13M8 1.5c-2 2.2-2 10.8 0 13" />
    </Svg>
  );
}

export function IconShield(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M8 1.8l5 2v4c0 3.2-2.2 5.3-5 6.4-2.8-1.1-5-3.2-5-6.4v-4z" />
    </Svg>
  );
}

export function IconChevronDown(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M4 6l4 4 4-4" />
    </Svg>
  );
}

export function IconUpload(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M8 10.5V2.5M5 5.3l3-2.8 3 2.8M2.5 10.5v2a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-2" />
    </Svg>
  );
}

export function IconExternal(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M9 2.5h4.5V7M13.5 2.5L7 9M11.5 9.5v3a1 1 0 0 1-1 1h-7a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3" />
    </Svg>
  );
}
