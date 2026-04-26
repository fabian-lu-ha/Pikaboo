import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { Brand, EffectParams, FocalZone } from "../types";
import { zoneAlign } from "./zone";

type Props = {
  params: EffectParams;
  brand: Brand;
  durationInFrames: number;
};

const sizeMultiplier = (size?: string): number => {
  switch (size) {
    case "sm":
      return 0.7;
    case "lg":
      return 1.6;
    default:
      return 1.0;
  }
};

const colorForRole = (
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
 * KineticText — animated word/phrase accent.
 *
 * Punches in over 8 frames (scale 0.6 → 1.0, opacity 0 → 1, slight upward
 * drift), holds for the middle, slides + fades out over 6 frames.
 *
 * NOT the caption — this is sparse punctuation for hook beats / reveals.
 */
export const KineticText: React.FC<Props> = ({
  params,
  brand,
  durationInFrames,
}) => {
  const f = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const text = (params.text ?? "").toString();
  if (!text) return null;

  const inFrames = 8;
  const outFrames = 6;
  const opacity = Math.min(
    interpolate(f, [0, inFrames], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
    interpolate(
      f,
      [durationInFrames - outFrames, durationInFrames],
      [1, 0],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
    ),
  );

  const scale = interpolate(f, [0, inFrames], [0.6, 1.0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const drift = interpolate(f, [0, inFrames], [12, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const colorRole = params.color ?? "accent";
  const color = colorForRole(brand, colorRole, "#ffffff");

  // Base kinetic-text size is roughly 1.2× the caption font; size param scales further.
  const isPortrait = height > width;
  const base = isPortrait
    ? Math.round(width * (66 / 1080))
    : Math.round(height * (74 / 1080));
  const fontSize = Math.round(base * sizeMultiplier(params.size));

  const align = zoneAlign(
    (params.zone ?? "tc") as FocalZone,
    width,
    height,
  );

  return (
    <div
      style={{
        position: "absolute",
        left: align.left,
        right: align.right,
        top: align.top,
        bottom: align.bottom,
        textAlign: align.textAlign,
        opacity,
        transform: `translateY(${drift}px) scale(${scale})`,
        transformOrigin:
          align.textAlign === "left"
            ? "left center"
            : align.textAlign === "right"
              ? "right center"
              : "center center",
        pointerEvents: "none",
      }}
    >
      <span
        style={{
          fontFamily:
            brand.headline_font ?? "system-ui, -apple-system, sans-serif",
          fontWeight: brand.caption_weight ?? 800,
          fontSize,
          lineHeight: 1.0,
          color,
          letterSpacing: `${(brand.caption_tracking_em ?? -0.01) - 0.005}em`,
          textTransform: brand.caption_all_caps ? "uppercase" : "none",
          textShadow: "0 2px 8px rgba(0,0,0,0.45)",
          whiteSpace: "nowrap",
        }}
      >
        {text}
      </span>
    </div>
  );
};
