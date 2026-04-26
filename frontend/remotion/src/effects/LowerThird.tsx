import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { Brand, EffectParams } from "../types";

type Props = {
  params: EffectParams;
  brand: Brand;
  durationInFrames: number;
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
 * LowerThird — bottom info bar with title + optional subtitle.
 *
 * Slides in from the left (clip-reveal style), holds, slides out. Brand
 * accent acts as the title color; subtitle uses text-role at lower opacity.
 */
export const LowerThird: React.FC<Props> = ({
  params,
  brand,
  durationInFrames,
}) => {
  const f = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const title = (params.title ?? "").toString();
  const subtitle = (params.subtitle ?? "").toString();
  if (!title && !subtitle) return null;

  const inFrames = 12;
  const outFrames = 10;

  // Reveal: a clip-path wipe from left to right.
  const revealPct = interpolate(f, [0, inFrames], [0, 100], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(
    f,
    [durationInFrames - outFrames, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  const accent = colorForRole(brand, "accent", "#ffffff");
  const fg = colorForRole(brand, "text", "#ffffff");
  const bg = colorForRole(brand, "background", "#000000");

  const isPortrait = height > width;
  const titleSize = isPortrait
    ? Math.round(width * (32 / 1080))
    : Math.round(height * (36 / 1080));
  const subtitleSize = Math.round(titleSize * 0.62);

  const padX = Math.round(width * 0.06);
  // 9:16 lower-third sits above the platform safe-bottom (~280px on Stories).
  const fromBottom = isPortrait
    ? Math.round(height * 0.18)
    : Math.round(height * 0.1);

  return (
    <div
      style={{
        position: "absolute",
        left: padX,
        bottom: fromBottom,
        opacity: fadeOut,
        clipPath: `inset(0 ${100 - revealPct}% 0 0)`,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          display: "inline-flex",
          flexDirection: "column",
          alignItems: "flex-start",
          gap: Math.round(titleSize * 0.18),
          padding: `${Math.round(titleSize * 0.42)}px ${Math.round(titleSize * 0.7)}px`,
          backgroundColor: `${bg}cc`,
          borderLeft: `${Math.max(2, Math.round(titleSize * 0.12))}px solid ${accent}`,
          backdropFilter: "blur(6px)",
        }}
      >
        {title && (
          <span
            style={{
              fontFamily:
                brand.headline_font ?? "system-ui, -apple-system, sans-serif",
              fontWeight: brand.caption_weight ?? 700,
              fontSize: titleSize,
              lineHeight: 1.05,
              color: fg,
              letterSpacing: `${brand.caption_tracking_em ?? -0.01}em`,
              textTransform: brand.caption_all_caps ? "uppercase" : "none",
              whiteSpace: "nowrap",
            }}
          >
            {title}
          </span>
        )}
        {subtitle && (
          <span
            style={{
              fontFamily: brand.body_font ?? "system-ui",
              fontWeight: 500,
              fontSize: subtitleSize,
              lineHeight: 1.2,
              color: fg,
              opacity: 0.72,
              letterSpacing: "0.02em",
              textTransform: "uppercase",
              whiteSpace: "nowrap",
            }}
          >
            {subtitle}
          </span>
        )}
      </div>
    </div>
  );
};
