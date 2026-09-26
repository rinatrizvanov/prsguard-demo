/**
 * Ancestry codes and their fixed colours.
 *
 * Colour follows the entity, never its rank: EUR is always slot 1, AFR slot 2, ...
 * The five 1000 Genomes superpopulation colours (EUR, AFR, EAS, SAS, AMR) were checked
 * with the data-viz palette validator for ALL pairs (scatter use): CVD ΔE ≥ 9.1,
 * normal-vision ΔE ≥ 16.3 on the light surface. The PCA additionally encodes group by
 * marker shape, so identity never relies on colour alone. The extra PGS Catalog codes
 * (ASN, GME) extend the order for adjacent-pair use in stacked bars (validated adjacent).
 * Non-specific codes (MAE, MAO, OTH, NR) are deliberately neutral greys: they are not
 * a population, and "not reported" should read as missing information.
 */

export interface AncestryMeta {
  code: string;
  label: string;
  color: string;
  /** neutral (non-specific) categories get a hatch in bar charts */
  neutral?: boolean;
}

const META: Record<string, AncestryMeta> = {
  EUR: { code: "EUR", label: "European", color: "#2a78d6" },
  AFR: { code: "AFR", label: "African", color: "#c2410c" },
  EAS: { code: "EAS", label: "East Asian", color: "#1baf7a" },
  SAS: { code: "SAS", label: "South Asian", color: "#4a3aa7" },
  AMR: { code: "AMR", label: "Hispanic or Latin American / admixed American", color: "#eda100" },
  ASN: { code: "ASN", label: "Additional Asian ancestries", color: "#e87ba4" },
  GME: { code: "GME", label: "Greater Middle Eastern", color: "#008300" },
  MID: { code: "MID", label: "Middle Eastern", color: "#008300" },
  MAE: { code: "MAE", label: "Multi-ancestry (including European)", color: "#8a8883", neutral: true },
  MAO: { code: "MAO", label: "Multi-ancestry (excluding European)", color: "#65635e", neutral: true },
  OTH: { code: "OTH", label: "Additional diverse ancestries", color: "#b3b1aa", neutral: true },
  NR: { code: "NR", label: "Not reported", color: "#d9d7d0", neutral: true },
};

/** Fixed display order for stacked bars and legends. */
export const ANCESTRY_ORDER = ["EUR", "AFR", "EAS", "SAS", "AMR", "ASN", "GME", "MID", "MAE", "MAO", "OTH", "NR"];

export function ancestryMeta(code: string): AncestryMeta {
  return META[code] ?? { code, label: code, color: "#9a988f", neutral: true };
}

export function sortCodes(codes: string[]): string[] {
  const idx = (c: string) => {
    const i = ANCESTRY_ORDER.indexOf(c);
    return i < 0 ? ANCESTRY_ORDER.length : i;
  };
  return [...codes].sort((a, b) => idx(a) - idx(b) || a.localeCompare(b));
}

/** 1000 Genomes superpopulations used as the reference in placement. */
export const SUPERPOPS = ["EUR", "AFR", "EAS", "SAS", "AMR"] as const;
export type Superpop = (typeof SUPERPOPS)[number];

export const SUPERPOP_LABEL: Record<Superpop, string> = {
  EUR: "European (1000G EUR)",
  AFR: "African (1000G AFR)",
  EAS: "East Asian (1000G EAS)",
  SAS: "South Asian (1000G SAS)",
  AMR: "Admixed American (1000G AMR)",
};

export type MarkerShape = "circle" | "square" | "triangle" | "diamond" | "triangle-down";

export const SUPERPOP_SHAPE: Record<Superpop, MarkerShape> = {
  EUR: "circle",
  AFR: "square",
  EAS: "triangle",
  SAS: "diamond",
  AMR: "triangle-down",
};

/** 1000 Genomes population codes → description (for PCA tooltips). */
export const POP_LABEL: Record<string, string> = {
  ACB: "African Caribbean in Barbados",
  ASW: "African Ancestry in SW USA",
  BEB: "Bengali in Bangladesh",
  CDX: "Chinese Dai in Xishuangbanna, China",
  CEU: "Utah residents with N. & W. European ancestry",
  CHB: "Han Chinese in Beijing, China",
  CHS: "Southern Han Chinese",
  CLM: "Colombians in Medellín, Colombia",
  ESN: "Esan in Nigeria",
  FIN: "Finnish in Finland",
  GBR: "British in England and Scotland",
  GIH: "Gujarati Indians in Houston, USA",
  GWD: "Gambian in Western Division, The Gambia",
  IBS: "Iberian populations in Spain",
  ITU: "Indian Telugu in the UK",
  JPT: "Japanese in Tokyo, Japan",
  KHV: "Kinh in Ho Chi Minh City, Vietnam",
  LWK: "Luhya in Webuye, Kenya",
  MSL: "Mende in Sierra Leone",
  MXL: "Mexican Ancestry in Los Angeles, USA",
  PEL: "Peruvians in Lima, Peru",
  PJL: "Punjabi in Lahore, Pakistan",
  PUR: "Puerto Ricans in Puerto Rico",
  STU: "Sri Lankan Tamil in the UK",
  TSI: "Toscani in Italia",
  YRI: "Yoruba in Ibadan, Nigeria",
};
