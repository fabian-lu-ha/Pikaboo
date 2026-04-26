import React, { useMemo } from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  random,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { SpecCardParams } from "../types";
import {
  DEFAULT_BODY_FONT,
  DEFAULT_HEADLINE_FONT,
  type DesignSequenceProps,
  resolveRole,
  scaledSize,
} from "./shared";

/**
 * SpecCard — Apple-keynote spec beat.
 *
 * - Clean light or dark surface (params.theme).
 * - Massive numerical value, center.
 * - Small label below.
 * - Optional unit suffix that builds in independently.
 * - Number reveals with a "punch" scale (0.92 → 1.04 → 1.0) and the digits
 *   flicker through random numerals (counter-style) before settling.
 * - Thin accent underline draws in from the left.
 */
const SpecCard: React.FC<DesignSequenceProps<SpecCardParams>> = ({
  params,
  brand,
  durationInFrames,
}) => {
  const f = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const value = (params.value ?? "").toString();
  const label = (params.label ?? "").toString();
  const unit = (params.unit ?? "").toString();
  const theme = params.theme ?? "light";

  /* Themed surface colors. Brand accent is preserved across themes for the
     underline so the brand still reads through. */
  const lightBg = "#fafafa";
  const darkBg = "#0b0b0c";
  const lightFg = "#0b0b0c";
  const darkFg = "#fafafa";

  const bg = theme === "dark" ? darkBg : lightBg;
  const fg = theme === "dark" ? darkFg : lightFg;
  const subtleFg = theme === "dark" ? "rgba(250,250,250,0.65)" : "rgba(11,11,12,0.62)";
  const accent = resolveRole(brand, "accent", theme === "dark" ? "#fb923c" : "#fb923c");

  /* Animation timing. Punch over 12 frames; flicker through 8 frames; exit over 14. */
  const punchEnd = 12;
  const flickerLen = 8;
  const underlineStart = punchEnd + 2;
  const underlineEnd = underlineStart + 18;
  const labelStart = underlineEnd - 4;
  const labelInEnd = labelStart + 10;
  const exitStart = durationInFrames - 14;

  /* Counter-style flicker — each character index gets a sequence of random
     numerals that resolves to the final glyph after `flickerLen` frames.
     We compute the per-char strings ONCE per render so the random sequence
     stays stable; using `random()` (Remotion's deterministic RNG) keeps it
     reproducible across renders. */
  const valueChars = useMemo(() => Array.from(value), [value]);
  const flickerSequences = useMemo(() => {
    return valueChars.map((ch, i) => {
      // Non-numeric glyphs (e.g. "$", "×", "M") just hold their final char.
      if (!/[0-9]/.test(ch)) return Array(flickerLen).fill(ch);
      const seq: string[] = [];
      for (let k = 0; k < flickerLen; k++) {
        const r = random(`spec-${i}-${k}`);
        seq.push(Math.floor(r * 10).toString());
      }
      return seq;
    });
  }, [valueChars]);

  /* Punch scale: 0.92 → 1.04 → 1.0. Drives the value group only. */
  const punchScale = interpolate(
    f,
    [0, Math.round(punchEnd * 0.55), punchEnd],
    [0.92, 1.04, 1.0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    },
  );

  /* Punch fade — value snaps in fast. */
  const valueFadeIn = interpolate(f, [0, 4], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  /* Underline draw-in from the left. */
  const underlineWidthPct = interpolate(
    f,
    [underlineStart, underlineEnd],
    [0, 100],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    },
  );

  /* Label fade-in below the underline. */
  const labelOpacity = Math.min(
    interpolate(f, [labelStart, labelInEnd], [0, 1], {
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

  /* Unit builds in slightly after the value lands. */
  const unitOpacity = Math.min(
    interpolate(f, [punchEnd + 2, punchEnd + 12], [0, 1], {
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

  /* Whole-card exit — pulls everything back so nothing hangs at end. */
  const cardExit = interpolate(
    f,
    [exitStart, durationInFrames],
    [1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.in(Easing.cubic),
    },
  );

  /* Typography. Spec values run BIG — 280-360pt at 1080. */
  const headlineFont = brand.headline_font ?? DEFAULT_HEADLINE_FONT;
  const bodyFont = brand.body_font ?? DEFAULT_BODY_FONT;
  const valueSize = scaledSize(width, height, 320);
  const unitSize = scaledSize(width, height, 96);
  const labelSize = scaledSize(width, height, 36);

  const renderValueChars = () => {
    return valueChars.map((finalCh, i) => {
      // Pick which char to show this frame: flicker until punchEnd, then settle.
      const local = Math.max(0, f - i); // tiny stagger across digits
      let displayCh: string = finalCh;
      if (local < flickerLen && /[0-9]/.test(finalCh)) {
        displayCh = flickerSequences[i][Math.min(local, flickerLen - 1)];
      }
      return (
        <span
          key={i}
          style={{
            display: "inline-block",
            // Tabular feel — fix per-char width so flicker doesn't jitter layout.
            minWidth: /[0-9]/.test(finalCh) ? "0.62em" : undefined,
            textAlign: "center",
            whiteSpace: "pre",
          }}
        >
          {displayCh}
        </span>
      );
    });
  };

  return (
    <AbsoluteFill
      style={{
        backgroundColor: bg,
        opacity: cardExit,
      }}
    >
      {/* Center stack — value + unit row, underline, label. */}
      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: `0 ${Math.round(width * 0.08)}px`,
          gap: Math.round(valueSize * 0.06),
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: Math.round(unitSize * 0.18),
            opacity: valueFadeIn,
            transform: `scale(${punchScale})`,
            transformOrigin: "center center",
          }}
        >
          <span
            style={{
              fontFamily: headlineFont,
              fontWeight: 800,
              fontSize: valueSize,
              lineHeight: 0.95,
              color: fg,
              letterSpacing: "-0.04em",
              fontFeatureSettings: "'tnum' 1",
            }}
          >
            {renderValueChars()}
          </span>
          {unit ? (
            <span
              style={{
                fontFamily: headlineFont,
                fontWeight: 600,
                fontSize: unitSize,
                lineHeight: 0.95,
                color: subtleFg,
                letterSpacing: "-0.02em",
                opacity: unitOpacity,
              }}
            >
              {unit}
            </span>
          ) : null}
        </div>

        {/* Accent underline — draws in from the left. */}
        <div
          style={{
            width: Math.round(valueSize * 1.2),
            maxWidth: "85%",
            height: Math.max(2, Math.round(valueSize * 0.018)),
            position: "relative",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              height: "100%",
              width: `${underlineWidthPct}%`,
              backgroundColor: accent,
              borderRadius: "999px",
            }}
          />
        </div>

        {label ? (
          <div
            style={{
              fontFamily: bodyFont,
              fontWeight: 500,
              fontSize: labelSize,
              lineHeight: 1.3,
              color: subtleFg,
              letterSpacing: "0.02em",
              textAlign: "center",
              maxWidth: "70%",
              opacity: labelOpacity,
              marginTop: Math.round(labelSize * 0.4),
            }}
          >
            {label}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export default SpecCard;
