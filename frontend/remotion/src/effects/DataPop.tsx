import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { Brand, EffectParams, FocalZone } from "../types";
import { zoneAlign } from "./zone";

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
 * DataPop — animated number / metric reveal.
 *
 * Three variants:
 *  - "number" (default): the value scales in with a brief overshoot.
 *  - "bar": adds a horizontal bar that grows underneath.
 *  - "dot": adds a brand-colored dot that pulses next to the value.
 *
 * The value is rendered as a string ("67%", "10x", "$0 → $1k"); we don't
 * try to count up — that pattern is overused and feels gimmicky. A pop-in
 * with restraint reads as more confident.
 */
export const DataPop: React.FC<Props> = ({
  params,
  brand,
  durationInFrames,
}) => {
  const f = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const value = (params.value ?? "").toString();
  if (!value) return null;

  const inFrames = 10;
  const outFrames = 8;

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

  // Gentle overshoot scale: 0.6 → 1.08 → 1.0
  const scale = interpolate(
    f,
    [0, inFrames * 0.7, inFrames],
    [0.6, 1.08, 1.0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  // Bar growth (variant=bar)
  const barWidth = interpolate(f, [inFrames * 0.5, inFrames * 1.6], [0, 100], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Dot pulse (variant=dot) — sin-based, after the value lands
  const dotPulse = 0.5 + 0.5 * Math.sin((f - inFrames) * 0.25);

  const accent = colorForRole(brand, "accent", "#fb923c");
  const fg = colorForRole(brand, "text", "#ffffff");

  const isPortrait = height > width;
  const valueSize = isPortrait
    ? Math.round(width * (110 / 1080))
    : Math.round(height * (118 / 1080));

  const align = zoneAlign(
    (params.zone ?? "mc") as FocalZone,
    width,
    height,
  );

  const variant = params.variant ?? "number";

  return (
    <div
      style={{
        position: "absolute",
        left: align.left,
        right: align.right,
        top: align.top,
        bottom: align.bottom,
        opacity,
        textAlign: align.textAlign,
        transform: `scale(${scale})`,
        transformOrigin:
          align.textAlign === "left"
            ? "left center"
            : align.textAlign === "right"
              ? "right center"
              : "center center",
        pointerEvents: "none",
      }}
    >
      <div style={{ display: "inline-flex", alignItems: "center", gap: Math.round(valueSize * 0.2) }}>
        {variant === "dot" && (
          <span
            style={{
              display: "inline-block",
              width: Math.round(valueSize * 0.32),
              height: Math.round(valueSize * 0.32),
              borderRadius: "999px",
              backgroundColor: accent,
              opacity: 0.4 + 0.6 * dotPulse,
              boxShadow: `0 0 ${Math.round(valueSize * 0.3)}px ${accent}`,
            }}
          />
        )}
        <span
          style={{
            fontFamily:
              brand.headline_font ?? "system-ui, -apple-system, sans-serif",
            fontWeight: 900,
            fontSize: valueSize,
            lineHeight: 0.95,
            color: fg,
            letterSpacing: "-0.03em",
            textShadow: "0 3px 12px rgba(0,0,0,0.45)",
          }}
        >
          {value}
        </span>
      </div>
      {variant === "bar" && (
        <div
          style={{
            marginTop: Math.round(valueSize * 0.15),
            height: Math.max(3, Math.round(valueSize * 0.05)),
            background: `linear-gradient(90deg, ${accent} 0%, ${accent} ${barWidth}%, transparent ${barWidth}%)`,
            width: "60%",
            marginLeft:
              align.textAlign === "left"
                ? 0
                : align.textAlign === "right"
                  ? "40%"
                  : "20%",
          }}
        />
      )}
    </div>
  );
};
