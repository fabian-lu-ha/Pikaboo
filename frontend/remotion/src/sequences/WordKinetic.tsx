import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  random,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type {
  WordKineticEnter,
  WordKineticParams,
  WordKineticWord,
} from "../types";
import {
  DEFAULT_HEADLINE_FONT,
  type DesignSequenceProps,
  hexToRgba,
  palette,
  readableTextOn,
  resolveRole,
  scaledSize,
} from "./shared";

/**
 * WordKinetic — multi-word kinetic typography (Wieden+Kennedy spec).
 *
 * - 3-6 words, each absolutely positioned in a deterministic scattered
 *   layout (Remotion's seeded `random()` keeps placements stable across
 *   renders).
 * - Words appear sequentially with a 6-8 frame stagger; each runs its own
 *   enter animation per `enter` field.
 * - Exit is synchronized: every word fades together in the last 10 frames.
 */
const WordKinetic: React.FC<DesignSequenceProps<WordKineticParams>> = ({
  params,
  brand,
  durationInFrames,
}) => {
  const f = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const words = (params.words ?? []).filter(
    (w): w is WordKineticWord =>
      typeof w === "object" && w !== null && typeof w.text === "string",
  );

  const headlineFont = brand.headline_font ?? DEFAULT_HEADLINE_FONT;
  const bg = resolveRole(brand, "background", palette(brand, 0, "#0b0b0c"));
  const fg = readableTextOn(bg);
  const accent = resolveRole(brand, "accent", palette(brand, 2, "#fb923c"));

  const baseSize = scaledSize(width, height, 110);
  const stagger = 7;
  const wordEnter = 10;
  const exitFrames = 10;
  const exitStart = durationInFrames - exitFrames;

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

  const colorFor = (name: WordKineticWord["color"]): string => {
    if (name === "accent") return accent;
    if (name === "background") return bg;
    return fg;
  };

  const enterOf = (
    enter: WordKineticEnter | undefined,
    start: number,
  ): { opacity: number; transform: string } => {
    const localStart = start;
    const localEnd = start + wordEnter;
    const op = interpolate(f, [localStart, localEnd], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    });
    switch (enter) {
      case "rotate": {
        const deg = interpolate(f, [localStart, localEnd], [-25, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.out(Easing.cubic),
        });
        return { opacity: op, transform: `rotate(${deg}deg)` };
      }
      case "scale": {
        const s = interpolate(f, [localStart, localEnd], [0.5, 1.0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.out(Easing.bezier(0.34, 1.56, 0.64, 1.0)),
        });
        return { opacity: op, transform: `scale(${s})` };
      }
      case "slide": {
        const dy = interpolate(f, [localStart, localEnd], [40, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.out(Easing.cubic),
        });
        return { opacity: op, transform: `translateY(${dy}px)` };
      }
      case "flip": {
        const rx = interpolate(f, [localStart, localEnd], [90, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.out(Easing.cubic),
        });
        return { opacity: op, transform: `perspective(1200px) rotateX(${rx}deg)` };
      }
      default: {
        // Default to slide for an unspecified enter.
        const dy = interpolate(f, [localStart, localEnd], [40, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.out(Easing.cubic),
        });
        return { opacity: op, transform: `translateY(${dy}px)` };
      }
    }
  };

  return (
    <AbsoluteFill style={{ backgroundColor: bg, overflow: "hidden" }}>
      {/* Soft accent wash — a faint diagonal gradient gives the canvas weight. */}
      <AbsoluteFill
        style={{
          background: `linear-gradient(120deg, ${hexToRgba(accent, 0.15)} 0%, ${hexToRgba(bg, 0)} 60%)`,
          pointerEvents: "none",
        }}
      />

      {words.map((w, i) => {
        const enterStart = i * stagger;
        const { opacity, transform } = enterOf(w.enter, enterStart);
        const op = opacity * exitOpacity;

        // Deterministic scattered placement — each word lands in a band so
        // we don't get overlap, but seeded randomness offsets the exact
        // anchor inside its band.
        const totalRows = Math.max(words.length, 3);
        const rowFrac = (i + 0.5) / totalRows;
        const yJitter = (random(`wk-y-${i}`) - 0.5) * (height * 0.12);
        const xJitter = (random(`wk-x-${i}`) - 0.5) * (width * 0.18);
        const cy = height * rowFrac + yJitter;
        const cx = width * 0.5 + xJitter;

        const variantSize = baseSize * (0.85 + (random(`wk-s-${i}`) * 0.5));
        const fontSize = Math.round(variantSize);

        const styleName = w.style ?? "bold";
        const fontWeight = styleName === "italic" ? 600 : 800;
        const fontStyle = styleName === "italic" ? "italic" : "normal";
        const textTransform = styleName === "caps" ? "uppercase" : "none";

        const color = colorFor(w.color);

        return (
          <div
            key={`${i}-${w.text}`}
            style={{
              position: "absolute",
              left: cx,
              top: cy,
              transform: `translate(-50%, -50%) ${transform}`,
              transformOrigin: "center center",
              fontFamily: headlineFont,
              fontWeight,
              fontStyle,
              textTransform,
              fontSize,
              lineHeight: 1.0,
              color,
              letterSpacing: styleName === "caps" ? "0.02em" : "-0.01em",
              opacity: op,
              whiteSpace: "nowrap",
              textShadow:
                color === bg
                  ? `0 0 ${Math.round(fontSize * 0.08)}px ${hexToRgba(fg, 0.45)}`
                  : "0 2px 8px rgba(0,0,0,0.35)",
            }}
          >
            {w.text}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

export default WordKinetic;
