import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { HeadlinePunchParams } from "../types";
import {
  DEFAULT_BODY_FONT,
  DEFAULT_HEADLINE_FONT,
  type DesignSequenceProps,
  hexToRgba,
  palette,
  readableTextOn,
  resolveRole,
  scaledSize,
} from "./shared";

/**
 * HeadlinePunch — Apple-keynote single-headline punch.
 *
 * - Headline reveals: scale 0.7 → 1.05 → 1.0 with overshoot, opacity 0 → 1
 *   over 8 frames, letter-spacing relaxes from 0.5em → 0em.
 * - Holds for the middle ~50% of the duration.
 * - Subheadline fades in below after the headline settles, fades before
 *   the headline starts its zoom-past exit.
 * - Exit: zooms past camera (scale 1.0 → 4.0, opacity 1 → 0) over the last
 *   14 frames — feels like the headline punches through the lens.
 */
const HeadlinePunch: React.FC<DesignSequenceProps<HeadlinePunchParams>> = ({
  params,
  brand,
  durationInFrames,
}) => {
  const f = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const headline = (params.headline ?? "").trim();
  const subheadline = (params.subheadline ?? "").trim();

  const headlineFont = brand.headline_font ?? DEFAULT_HEADLINE_FONT;
  const bodyFont = brand.body_font ?? DEFAULT_BODY_FONT;

  const bg = resolveRole(brand, "background", palette(brand, 0, "#0b0b0c"));
  const fg = readableTextOn(bg);
  const subtleFg = hexToRgba(fg, 0.7);
  const accent = resolveRole(brand, "accent", palette(brand, 2, "#fb923c"));

  /* Timing — 8f reveal, hold middle ~50%, 14f zoom-past exit. */
  const revealEnd = 8;
  const exitFrames = 14;
  const exitStart = durationInFrames - exitFrames;
  const subStart = revealEnd + 4;
  const subInEnd = subStart + 10;
  // Subheadline fades out before the headline launches into the zoom-past.
  const subOutStart = exitStart - 8;
  const subOutEnd = exitStart;

  /* Headline reveal — scale with overshoot, opacity, kerning. */
  const revealOpacity = interpolate(f, [0, revealEnd], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  // 0.7 → 1.05 → 1.0 (overshoot at half-step)
  const revealScale = interpolate(
    f,
    [0, Math.round(revealEnd * 0.55), revealEnd],
    [0.7, 1.05, 1.0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.bezier(0.34, 1.56, 0.64, 1.0)),
    },
  );
  // 0.5em → 0em over the reveal window.
  const revealKerning = interpolate(f, [0, revealEnd], [0.5, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  /* Zoom-past exit — scale 1 → 4, opacity 1 → 0 cubic-in. */
  const exitScale = interpolate(f, [exitStart, durationInFrames], [1.0, 4.0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.in(Easing.cubic),
  });
  const exitOpacity = interpolate(
    f,
    [exitStart, durationInFrames],
    [1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.in(Easing.cubic),
    },
  );

  const headlineScale = revealScale * exitScale;
  const headlineOpacity = revealOpacity * exitOpacity;

  /* Subheadline in/out. */
  const subOpacity = Math.min(
    interpolate(f, [subStart, subInEnd], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    }),
    interpolate(f, [subOutStart, subOutEnd], [1, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.in(Easing.cubic),
    }),
  );

  const headlineSize = scaledSize(width, height, 156);
  const subSize = scaledSize(width, height, 36);

  return (
    <AbsoluteFill style={{ backgroundColor: bg, overflow: "hidden" }}>
      {/* Subtle radial vignette for depth. */}
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,0.35) 100%)",
          mixBlendMode: "multiply",
          pointerEvents: "none",
        }}
      />

      {/* Thin accent rule above the headline — punches up the layout. */}
      <div
        style={{
          position: "absolute",
          left: "50%",
          top: `calc(50% - ${Math.round(headlineSize * 0.85)}px)`,
          width: Math.round(headlineSize * 0.5),
          height: 4,
          marginLeft: -Math.round(headlineSize * 0.25),
          backgroundColor: accent,
          borderRadius: 999,
          opacity: revealOpacity * exitOpacity,
        }}
      />

      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: Math.round(subSize * 0.9),
          padding: `0 ${Math.round(width * 0.08)}px`,
          textAlign: "center",
        }}
      >
        <div
          style={{
            fontFamily: headlineFont,
            fontWeight: 800,
            fontSize: headlineSize,
            lineHeight: 1.0,
            color: fg,
            letterSpacing: `${revealKerning}em`,
            opacity: headlineOpacity,
            transform: `scale(${headlineScale})`,
            transformOrigin: "center center",
            maxWidth: "94%",
          }}
        >
          {headline}
        </div>
        {subheadline ? (
          <div
            style={{
              fontFamily: bodyFont,
              fontWeight: 500,
              fontSize: subSize,
              lineHeight: 1.3,
              color: subtleFg,
              letterSpacing: "0.02em",
              maxWidth: "70%",
              opacity: subOpacity,
            }}
          >
            {subheadline}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export default HeadlinePunch;
