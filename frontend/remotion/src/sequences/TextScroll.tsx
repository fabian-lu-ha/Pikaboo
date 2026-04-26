import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { TextScrollParams } from "../types";
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
 * TextScroll — vertical end-credits scroll.
 *
 * - Lines drift bottom→top at a constant linear speed (true scroll feel).
 * - Each line independently fades in/out as it crosses the viewport top/
 *   bottom using cubic-out, so edges stay soft rather than ASCII-clipped.
 * - theme="overlay" => transparent bg (composited on Veo footage); "full" =>
 *   brand background-role solid.
 * - Whole composition fades on the last 14 frames so nothing hangs.
 */
const TextScroll: React.FC<DesignSequenceProps<TextScrollParams>> = ({
  params,
  brand,
  durationInFrames,
}) => {
  const f = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const lines = (params.lines ?? []).filter((l) => typeof l === "string");
  const theme = params.theme ?? "overlay";

  const headlineFont = brand.headline_font ?? DEFAULT_HEADLINE_FONT;
  const bodyFont = brand.body_font ?? DEFAULT_BODY_FONT;

  const bgFull = resolveRole(brand, "background", palette(brand, 0, "#0b0b0c"));
  const fg =
    theme === "full" ? readableTextOn(bgFull) : resolveRole(brand, "text", "#ffffff");
  const subtleFg = hexToRgba(fg, 0.7);

  const fontSize = scaledSize(width, height, 56);
  const lineGap = Math.round(fontSize * 1.55);

  // The scroll travels from off-bottom to off-top. Total scroll distance
  // equals the stack height plus a viewport's worth of breathing room on
  // either side, but the actual travel is bounded by the start/end Y values
  // we pass to interpolate().
  const stackHeight = lineGap * Math.max(lines.length, 1);

  const exitStart = durationInFrames - 14;

  // Linear travel — the bg motion exception called out in the spec.
  const baseY = interpolate(
    f,
    [0, durationInFrames],
    [height + height * 0.05, -(stackHeight)],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.linear,
    },
  );

  const wholeOpacity = interpolate(f, [exitStart, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.in(Easing.cubic),
  });

  // Soft fade band at the top + bottom edges so lines bloom in/out.
  const fadeBand = Math.round(height * 0.18);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: theme === "full" ? bgFull : "transparent",
        opacity: wholeOpacity,
        overflow: "hidden",
      }}
    >
      {theme === "full" ? (
        <AbsoluteFill
          style={{
            background: `radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,0.32) 100%)`,
            mixBlendMode: "multiply",
            pointerEvents: "none",
          }}
        />
      ) : null}

      <AbsoluteFill
        style={{
          alignItems: "center",
          justifyContent: "flex-start",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: baseY,
            left: 0,
            right: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 0,
          }}
        >
          {lines.map((text, i) => {
            // Where this line sits in the global Y ordering.
            const lineCenterY = baseY + i * lineGap + fontSize * 0.5;
            // Edge-aware opacity — soft fade as the line crosses the band.
            const topFade = interpolate(
              lineCenterY,
              [0, fadeBand],
              [0, 1],
              {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
                easing: Easing.out(Easing.cubic),
              },
            );
            const bottomFade = interpolate(
              lineCenterY,
              [height - fadeBand, height],
              [1, 0],
              {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
                easing: Easing.in(Easing.cubic),
              },
            );
            const op = Math.min(topFade, bottomFade);
            const accent =
              i === 0 ? fg : i % 3 === 0 ? subtleFg : fg;
            return (
              <div
                key={`${i}-${text}`}
                style={{
                  height: lineGap,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: i === 0 ? headlineFont : bodyFont,
                  fontWeight: i === 0 ? 800 : 500,
                  fontSize: i === 0 ? fontSize * 1.15 : fontSize,
                  letterSpacing: i === 0 ? "-0.01em" : "0.01em",
                  color: accent,
                  opacity: op,
                  textAlign: "center",
                  width: "100%",
                  padding: `0 ${Math.round(width * 0.08)}px`,
                  textShadow:
                    theme === "overlay"
                      ? "0 2px 8px rgba(0,0,0,0.55), 0 4px 18px rgba(0,0,0,0.45)"
                      : "none",
                }}
              >
                {text}
              </div>
            );
          })}
        </div>
      </AbsoluteFill>

      {/* Top + bottom soft-mask gradients — present in 'full' theme only. */}
      {theme === "full" ? (
        <>
          <div
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              right: 0,
              height: fadeBand,
              background: `linear-gradient(to bottom, ${bgFull} 0%, ${hexToRgba(bgFull, 0)} 100%)`,
              pointerEvents: "none",
            }}
          />
          <div
            style={{
              position: "absolute",
              bottom: 0,
              left: 0,
              right: 0,
              height: fadeBand,
              background: `linear-gradient(to top, ${bgFull} 0%, ${hexToRgba(bgFull, 0)} 100%)`,
              pointerEvents: "none",
            }}
          />
        </>
      ) : null}

    </AbsoluteFill>
  );
};

export default TextScroll;
