import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { LogoRevealParams } from "../types";
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
 * LogoReveal — Wieden+Kennedy / Nike brand stinger.
 *
 * - Bg uses brand.palette[0] (or theme override).
 * - Wordmark builds in CHARACTER BY CHARACTER from a slight blur (8px → 0px)
 *   with kerning starting expanded (+0.1em → 0em).
 * - After wordmark settles, a 0.3s brand-color flash (full screen, ~70%
 *   opacity) sweeps and fades.
 * - Optional tagline fades in below after the flash.
 * - On exit the wordmark blurs back out + the bg dims so nothing hangs.
 *
 * Falls back to brandName prop if params.wordmark is missing.
 */
const LogoReveal: React.FC<DesignSequenceProps<LogoRevealParams>> = ({
  params,
  brand,
  brandName,
  durationInFrames,
}) => {
  const f = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();

  const wordmark = (params.wordmark ?? params.brand_name ?? brandName ?? "").trim();
  const tagline = (params.tagline ?? "").trim();
  const theme = params.theme;

  /* Background — theme override or brand palette. */
  const themedBg =
    theme === "dark"
      ? "#0b0b0c"
      : theme === "light"
      ? "#fafafa"
      : palette(brand, 0, "#0b0b0c");
  const fg = readableTextOn(themedBg);
  const accent = resolveRole(brand, "accent", palette(brand, 2, "#fb923c"));

  /* Timing. */
  const wordmarkRevealEnd = Math.min(28, Math.floor(durationInFrames * 0.4));
  const flashStart = wordmarkRevealEnd + 4;
  const flashLen = Math.max(8, Math.round(fps * 0.3));
  const flashEnd = flashStart + flashLen;
  const taglineStart = flashEnd + 2;
  const taglineInEnd = taglineStart + 12;
  const exitStart = durationInFrames - 14;

  /* Per-character wordmark animation. */
  const chars = Array.from(wordmark);
  const perChar = Math.max(
    1,
    Math.floor(wordmarkRevealEnd / Math.max(1, chars.length)),
  );

  /* Flash — full-screen accent wash for ~0.3s. */
  const flashOpacity = interpolate(
    f,
    [flashStart, flashStart + Math.floor(flashLen * 0.3), flashEnd],
    [0, 0.7, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    },
  );

  /* Tagline in/out. */
  const taglineOpacity = Math.min(
    interpolate(f, [taglineStart, taglineInEnd], [0, 1], {
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

  /* Whole-frame exit — bg dims + wordmark blurs back out. */
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

  /* Per-character blur + kerning relax. We compute a "global" blur driven by
     overall progress through the reveal, plus per-char opacity stagger. */
  const wordmarkProgress = interpolate(f, [0, wordmarkRevealEnd], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const wordmarkBlurIn = (1 - wordmarkProgress) * 8; // 8px → 0px
  const wordmarkBlurOut = interpolate(
    f,
    [exitStart, durationInFrames],
    [0, 8],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.in(Easing.cubic),
    },
  );
  const wordmarkBlur = wordmarkBlurIn + wordmarkBlurOut;
  const wordmarkKerning = (1 - wordmarkProgress) * 0.1; // +0.1em → 0em

  const headlineFont = brand.headline_font ?? DEFAULT_HEADLINE_FONT;
  const bodyFont = brand.body_font ?? DEFAULT_BODY_FONT;

  // Wordmark scales to canvas — looks like a billboard.
  const wordmarkSize = scaledSize(width, height, 156);
  const taglineSize = scaledSize(width, height, 34);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: themedBg,
        opacity: exitOpacity,
        overflow: "hidden",
      }}
    >
      {/* Subtle radial vignette on the bg. */}
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 40%, rgba(0,0,0,0.35) 100%)",
          mixBlendMode: "multiply",
          pointerEvents: "none",
        }}
      />

      {/* Wordmark + tagline. */}
      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: `0 ${Math.round(width * 0.06)}px`,
          gap: Math.round(wordmarkSize * 0.18),
        }}
      >
        <div
          style={{
            fontFamily: headlineFont,
            fontWeight: 800,
            fontSize: wordmarkSize,
            lineHeight: 1.0,
            color: fg,
            letterSpacing: `${wordmarkKerning}em`,
            filter: `blur(${wordmarkBlur}px)`,
            textTransform: "uppercase",
            textAlign: "center",
            maxWidth: "92%",
          }}
        >
          {chars.map((ch, i) => {
            const start = i * perChar;
            const end = start + Math.max(4, perChar + 4);
            const op = interpolate(f, [start, end], [0, 1], {
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
                  whiteSpace: "pre",
                }}
              >
                {ch}
              </span>
            );
          })}
        </div>

        {tagline ? (
          <div
            style={{
              fontFamily: bodyFont,
              fontWeight: 500,
              fontSize: taglineSize,
              lineHeight: 1.3,
              color: hexToRgba(fg, 0.78),
              letterSpacing: "0.04em",
              textTransform: "uppercase",
              textAlign: "center",
              maxWidth: "70%",
              opacity: taglineOpacity,
            }}
          >
            {tagline}
          </div>
        ) : null}
      </AbsoluteFill>

      {/* Brand-color flash — full screen wash that punctuates the reveal. */}
      <AbsoluteFill
        style={{
          backgroundColor: accent,
          opacity: flashOpacity,
          mixBlendMode: "screen",
          pointerEvents: "none",
        }}
      />
    </AbsoluteFill>
  );
};

export default LogoReveal;
