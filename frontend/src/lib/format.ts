import type { Variant } from "./api";

export const VARIANTS: Variant[] = ["zero_shot", "few_shot", "persona"];

export const VARIANT_LABEL: Record<Variant, string> = {
  zero_shot: "Zero-shot",
  few_shot: "Few-shot",
  persona: "Persona",
};

// Categorical palette, distinguishable in light and dark and for common colour-vision deficiencies.
export const VARIANT_COLOR: Record<Variant, string> = {
  zero_shot: "#6b8afd",
  few_shot: "#f0a030",
  persona: "#1fb89a",
};

export function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`;
  if (value >= 100) return `${Math.round(value)} ms`;
  return `${value.toFixed(1)} ms`;
}

export function num(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined ? "n/a" : value.toFixed(digits);
}

export function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "n/a" : `${(value * 100).toFixed(0)}%`;
}

export function titleCase(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Map a 0-5 overall score to an opacity-based heat colour (teal ramp). */
export function heat(score: number): string {
  const t = Math.max(0, Math.min(1, score / 5));
  return `color-mix(in srgb, var(--heat) ${Math.round(12 + t * 68)}%, transparent)`;
}
