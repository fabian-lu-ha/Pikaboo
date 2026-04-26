import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { GradientKineticParams } from "../types";
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
 * GradientKinetic — Linear / Vercel release-reel beat.
 *
 * - Bold gradient bg from 2-3 colors of brand.palette.
 * - Headline reveals letter-by-letter (cubic-out).
 * - Subtitle fades in after the headline lands.
 * - Two soft floating gradient "orbs" drift across the bg for depth.
 * - Subtle 1.0 → 1.04 push-in over the duration; everything pulls back
 *   on exit so nothing hangs at the end of the sequence.
 */
const GradientKinetic: React.FC<DesignSequenceProps<GradientKineticParams>> = ({
  params,
  brand,
  durationInFrames,
}) => {
  const f = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const headline = (params.headline ?? "").trim();
  const subtitle = (params.subtitle ?? "").trim();

  /* Gradient stops — at least 2 colors. Fall back to brand-aware defaults. */
  const stop0 = palette(brand, 0, "#0f172a");
  const stop1 = palette(brand, 1, "#1e293b");
  const stop2 = palette(brand, 2, stop1);
  const accent = resolveRole(brand, "accent", stop2);

  /* Foreground type color — pick light or dark based on the gradient's first stop. */
  const fg = readableTextOn(stop0);
  const subtleFg = hexToRgba(fg, 0.72);

  /* Camera-feel: 1.0 → 1.04 over the full duration (cubic in-out). */
  const cameraScale = interpolate(f, [0, durationInFrames], [1.0, 1.04], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });

  /* Headline letter-by-letter reveal. */
  const headlineChars = Array.from(headline);
  const headlineRevealWindow = Math.max(8, Math.floor(durationInFrames * 0.45));
  const perChar = Math.max(
    1,
    Math.floor(headlineRevealWindow / Math.max(1, headlineChars.length)),
  );

  /* Subtitle in/out — starts after headline window, exits with the camera. */
  const subStart = headlineRevealWindow + 4;
  const subInEnd = subStart + 12;
  const exitStart = durationInFrames - 14;

  const subtitleOpacity = Math.min(
    interpolate(f, [subStart, subInEnd], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    }),
    interpolate(f, [exitStart, durationInFrames], [1, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.in(Easing.cubic),
    }),
  );

  /* Headline exit — letters fade out collectively (cubic in). */
  const headlineExit = interpolate(
    f,
    [exitStart, durationInFrames],
    [1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.in(Easing.cubic),
    },
  );

  /* Background gradient angle drifts gently for liveness. */
  const angle = 130 + interpolate(f, [0, durationInFrames], [0, 12], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });

  /* Orb motion — two large blurred circles that drift across the canvas. */
  const orbA = {
    x: interpolate(f, [0, durationInFrames], [width * 0.15, width * 0.35], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.cubic),
    }),
    y: interpolate(f, [0, durationInFrames], [height * 0.25, height * 0.18], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.cubic),
    }),
  };
  const orbB = {
    x: interpolate(f, [0, durationInFrames], [width * 0.8, width * 0.62], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.cubic),
    }),
    y: interpolate(f, [0, durationInFrames], [height * 0.7, height * 0.78], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.cubic),
    }),
  };

  const headlineFont = brand.headline_font ?? DEFAULT_HEADLINE_FONT;
  const bodyFont = brand.body_font ?? DEFAULT_BODY_FONT;

  const headlineSize = scaledSize(width, height, 132);
  const subtitleSize = scaledSize(width, height, 38);

  const orbSize = Math.round(Math.max(width, height) * 0.55);

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(${angle}deg, ${stop0} 0%, ${stop1} 55%, ${stop2} 100%)`,
        overflow: "hidden",
      }}
    >
      {/* Floating orbs — blurred radial glows for depth. */}
      <div
        style={{
          position: "absolute",
          left: orbA.x - orbSize / 2,
          top: orbA.y - orbSize / 2,
          width: orbSize,
          height: orbSize,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${hexToRgba(accent, 0.45)} 0%, ${hexToRgba(accent, 0)} 70%)`,
          filter: "blur(40px)",
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: orbB.x - orbSize / 2,
          top: orbB.y - orbSize / 2,
          width: orbSize,
          height: orbSize,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${hexToRgba(stop2, 0.55)} 0%, ${hexToRgba(stop2, 0)} 70%)`,
          filter: "blur(50px)",
          pointerEvents: "none",
        }}
      />

      {/* Subtle grain — 4% white noise via tiled SVG, gives premium texture. */}
      <AbsoluteFill
        style={{
          opacity: 0.04,
          mixBlendMode: "overlay",
          backgroundImage:
            "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>\")",
          pointerEvents: "none",
        }}
      />

      {/* Headline + subtitle. Camera scale wraps the whole content stack. */}
      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: `0 ${Math.round(width * 0.08)}px`,
          textAlign: "center",
          gap: Math.round(headlineSize * 0.35),
          transform: `scale(${cameraScale})`,
          transformOrigin: "center center",
        }}
      >
        <div
          style={{
            fontFamily: headlineFont,
            fontWeight: 800,
            fontSize: headlineSize,
            lineHeight: 1.02,
            color: fg,
            letterSpacing: "-0.02em",
            maxWidth: "90%",
            opacity: headlineExit,
          }}
        >
          {headlineChars.map((ch, i) => {
            const start = i * perChar;
            const end = start + Math.max(4, perChar + 4);
            const op = interpolate(f, [start, end], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.out(Easing.cubic),
            });
            const dy = interpolate(f, [start, end], [18, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.out(Easing.cubic),
            });
            return (
              <span
                key={i}
                style={{
                  display: "inline-block",
                  opacity: op,
                  transform: `translateY(${dy}px)`,
                  whiteSpace: "pre",
                }}
              >
                {ch}
              </span>
            );
          })}
        </div>
        {subtitle ? (
          <div
            style={{
              fontFamily: bodyFont,
              fontWeight: 500,
              fontSize: subtitleSize,
              lineHeight: 1.3,
              color: subtleFg,
              letterSpacing: "0.01em",
              maxWidth: "70%",
              opacity: subtitleOpacity,
            }}
          >
            {subtitle}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export default GradientKinetic;
