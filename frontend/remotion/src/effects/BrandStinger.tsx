import React from "react";
import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
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

// Coerce an array of stop frames into a strictly monotonically increasing
// sequence by lifting each stop to be at least 1 greater than the previous.
// Negative stops are clamped to 0. Used to keep ``interpolate`` from blowing
// up on short durations where computed stops would collide.
const monotonic = (stops: number[]): number[] => {
  const out: number[] = [];
  for (let i = 0; i < stops.length; i++) {
    const v = i === 0 ? Math.max(0, stops[i]) : Math.max(out[i - 1] + 1, stops[i]);
    out.push(v);
  }
  return out;
};

/**
 * BrandStinger — short brand-color flash with optional wordmark.
 *
 * Acts like a punctuation mark between major beats. Three phases:
 *   1. Flash in (4 frames): accent color washes across the frame.
 *   2. Hold (6 frames): wordmark visible if provided.
 *   3. Flash out (4 frames): wash retracts.
 *
 * Designed to feel like a real broadcast bumper, not a fade.
 */
export const BrandStinger: React.FC<Props> = ({
  params,
  brand,
  durationInFrames,
}) => {
  const f = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const text = (params.text ?? "").toString();

  // Use a fixed 14-frame stinger if duration allows; scale otherwise.
  const stingerLen = Math.max(8, Math.min(durationInFrames, 14));
  const inEnd = Math.floor(stingerLen * 0.3);
  const outStart = Math.floor(stingerLen * 0.7);

  // ``inputRange`` for ``interpolate`` MUST be strictly monotonically
  // increasing. Short stingers (~8-11 frames) collapse the desired
  // wordOpacity stops onto each other — e.g. a 9-frame stinger gives
  // ``[inEnd-1, inEnd+2, outStart-2, outStart+1] = [1,4,4,7]``, which
  // Remotion rejects. Force each subsequent stop to be at least 1 frame
  // greater than the previous; clamp extrapolation handles overflow.
  const cover = interpolate(
    f,
    monotonic([0, inEnd, outStart, stingerLen]),
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  const wordOpacity = interpolate(
    f,
    monotonic([inEnd - 1, inEnd + 2, outStart - 2, outStart + 1]),
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  const accent = colorForRole(brand, "accent", "#fb923c");
  const fg = colorForRole(brand, "background", "#000000");

  const isPortrait = height > width;
  const wordSize = isPortrait
    ? Math.round(width * (88 / 1080))
    : Math.round(height * (96 / 1080));

  return (
    <AbsoluteFill
      style={{
        // The wash uses a slanted clip so it has motion direction, not just a flat fill.
        clipPath: `polygon(0 0, ${100 * cover}% 0, ${100 * cover - 8}% 100%, 0% 100%)`,
        backgroundColor: accent,
        pointerEvents: "none",
      }}
    >
      {text && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "grid",
            placeItems: "center",
            opacity: wordOpacity,
          }}
        >
          <span
            style={{
              fontFamily:
                brand.headline_font ?? "system-ui, -apple-system, sans-serif",
              fontWeight: 900,
              fontSize: wordSize,
              lineHeight: 1.0,
              color: fg,
              letterSpacing: "-0.02em",
              textTransform: "uppercase",
            }}
          >
            {text}
          </span>
        </div>
      )}
    </AbsoluteFill>
  );
};
