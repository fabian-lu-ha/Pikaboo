/**
 * Shared positioning helpers for effect components.
 *
 * Effects use the same 9-cell focal_zone vocabulary as the caption layer
 * but resolve to absolute CSS positions. This keeps the layout language
 * consistent across the composition — captions, effects, and focal-zone
 * subject placement all reference the same 9-cell grid.
 */

import type { FocalZone } from "../types";

export type Point = { x: number; y: number };

export const PADDING_PCT = 0.06;

export const zoneCenter = (
  zone: FocalZone,
  width: number,
  height: number,
): Point => {
  const padX = width * PADDING_PCT;
  const padY = height * PADDING_PCT;
  const inner = { w: width - 2 * padX, h: height - 2 * padY };
  const col = zone[1] === "l" ? 0 : zone[1] === "c" ? 0.5 : 1;
  const row = zone[0] === "t" ? 0 : zone[0] === "m" ? 0.5 : 1;
  return {
    x: padX + col * inner.w,
    y: padY + row * inner.h,
  };
};

/**
 * Resolve an effect zone to an alignment object (anchor + offset).
 * Effects are positioned absolutely; the alignment determines how the
 * effect's content flows from its anchor point.
 */
export type ZoneAlign = {
  left?: number;
  right?: number;
  top?: number;
  bottom?: number;
  textAlign: "left" | "center" | "right";
};

export const zoneAlign = (
  zone: FocalZone,
  width: number,
  height: number,
): ZoneAlign => {
  const padX = width * PADDING_PCT;
  const padY = height * PADDING_PCT;

  const horizontal: Pick<ZoneAlign, "left" | "right" | "textAlign"> =
    zone[1] === "l"
      ? { left: padX, textAlign: "left" }
      : zone[1] === "r"
        ? { right: padX, textAlign: "right" }
        : { left: padX, right: padX, textAlign: "center" };

  const vertical: Pick<ZoneAlign, "top" | "bottom"> =
    zone[0] === "t"
      ? { top: padY }
      : zone[0] === "b"
        ? { bottom: padY }
        : { top: height * 0.5 - height * 0.06 };

  return { ...horizontal, ...vertical };
};
