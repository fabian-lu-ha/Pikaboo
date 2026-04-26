/**
 * Shared helpers for design-sequence components.
 *
 * Keeps brand-color resolution, font defaults, and aspect-aware sizing
 * consistent across templates so a "premium release-reel" feel is uniform.
 */

import type { Aspect, Brand } from "../types";

export const DEFAULT_HEADLINE_FONT = "Inter, system-ui, -apple-system, sans-serif";
export const DEFAULT_BODY_FONT = "Inter, system-ui, -apple-system, sans-serif";
export const DEFAULT_MONO_FONT =
  "'JetBrains Mono', 'SF Mono', Menlo, Consolas, monospace";

/**
 * Resolve a brand role (e.g. "accent", "text", "background") to a hex.
 * Falls back through palette_roles → palette index → provided default.
 */
export const resolveRole = (
  brand: Brand,
  role: string,
  fallback: string,
): string => {
  const m = brand.palette_roles?.find(
    (e) => e.role.toLowerCase() === role.toLowerCase(),
  );
  return m?.hex ?? fallback;
};

/**
 * Read a palette swatch by index, with safe fallback. Used by templates
 * that want a specific number of stops (e.g. gradient backgrounds).
 */
export const palette = (brand: Brand, idx: number, fallback: string): string => {
  if (Array.isArray(brand.palette) && brand.palette[idx]) {
    return brand.palette[idx];
  }
  return fallback;
};

/**
 * Aspect-aware "short axis" dimension. Used to scale typography uniformly
 * across 9:16, 16:9, and 1:1 without per-aspect branches everywhere.
 */
export const shortAxis = (width: number, height: number): number =>
  Math.min(width, height);

/**
 * Standardised typography sizing. The base is "size as a fraction of the
 * short axis at 1080px," then scaled by the actual short axis. Keeps type
 * looking right at every aspect ratio.
 */
export const scaledSize = (
  width: number,
  height: number,
  base1080: number,
): number => Math.round((shortAxis(width, height) * base1080) / 1080);

/**
 * Hex parser with `#rrggbb` or `#rgb` support. Returns rgba string with
 * the requested alpha. Used to turn brand palette colors into translucent
 * overlays without losing the original hex authoring.
 */
export const hexToRgba = (hex: string, alpha: number): string => {
  let h = hex.replace(/^#/, "");
  if (h.length === 3) {
    h = h
      .split("")
      .map((c) => c + c)
      .join("");
  }
  if (h.length !== 6) {
    return `rgba(255,255,255,${alpha})`;
  }
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
};

/**
 * Pick a sensible (light vs dark) text color based on the background hex.
 * Quick perceived-luminance check — not gamma-correct but good enough for
 * picking foreground type that reads.
 */
export const readableTextOn = (bgHex: string): string => {
  let h = bgHex.replace(/^#/, "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  if (h.length !== 6) return "#ffffff";
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.6 ? "#0b0b0c" : "#ffffff";
};

export type DesignSequenceProps<TParams> = {
  params: TParams;
  brand: Brand;
  brandName?: string;
  durationInFrames: number;
  aspect: Aspect;
};
