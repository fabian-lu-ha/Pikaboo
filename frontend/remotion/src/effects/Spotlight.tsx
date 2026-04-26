import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { Brand, EffectParams, FocalZone } from "../types";
import { zoneCenter } from "./zone";

type Props = {
  params: EffectParams;
  brand: Brand;
  durationInFrames: number;
};

const radiusMultiplier = (radius?: string): number => {
  switch (radius) {
    case "sm":
      return 0.16;
    case "lg":
      return 0.40;
    default:
      return 0.26;
  }
};

/**
 * Spotlight — directs attention to a focal region with cinema-grade weight.
 *
 * Layered composition (back→front):
 *  1. Heavy outer dim (max 0.85) on a radial gradient — the "look here"
 *     darkroom feel. Was 0.6 — too soft to actually read as a spotlight.
 *  2. Subtle vignette boost on the four corners — adds the "anamorphic
 *     lens drop-off" you see in real cinematography.
 *  3. A faint warm rim INSIDE the spotlight circle that pulses ~0.2 Hz —
 *     gives the focal area a living, breathing presence vs a flat mask.
 *
 * Animation:
 *  - Radius PUNCHES IN with cubic-out easing (0 → target in 12 frames)
 *    instead of just appearing. Reads like a real spot snapping on.
 *  - Dim ramps with a slight back-easing so the darkness "settles"
 *    rather than linearly arriving.
 *  - Out: radius blooms slightly (1.0 → 1.15) while dim fades, like the
 *    light pulling away.
 */
export const Spotlight: React.FC<Props> = ({
  params,
  durationInFrames,
}) => {
  const f = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();

  const inFrames = 12;
  const outFrames = 10;
  const targetRadius = Math.round(
    Math.min(width, height) * radiusMultiplier(params.radius),
  );

  // Punch-in radius (0 → target with cubic out), then bloom on exit.
  const radiusInProgress = interpolate(f, [0, inFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const radiusOutProgress = interpolate(
    f,
    [durationInFrames - outFrames, durationInFrames],
    [1, 1.15],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.in(Easing.quad),
    },
  );
  const radius = Math.max(
    1,
    Math.round(targetRadius * Math.min(radiusInProgress, radiusOutProgress)),
  );

  // Heavy dim that settles, then fades on exit.
  const MAX_DIM = 0.85;
  const dim = Math.min(
    interpolate(f, [0, inFrames], [0, MAX_DIM], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.quad),
    }),
    interpolate(
      f,
      [durationInFrames - outFrames, durationInFrames],
      [MAX_DIM, 0],
      {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.in(Easing.quad),
      },
    ),
  );

  const center = zoneCenter(
    (params.zone ?? "mc") as FocalZone,
    width,
    height,
  );

  // Subtle pulse on the inner rim — 0.2 Hz, ±4% of radius.
  const pulse = Math.sin((f / fps) * Math.PI * 0.4) * 0.04 + 1;
  const innerRimRadius = Math.round(radius * 0.55 * pulse);

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {/* Layer 1: heavy spotlight dim with feathered hole. */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(circle at ${center.x}px ${center.y}px, transparent 0, transparent ${radius * 0.55}px, rgba(0,0,0,${dim * 0.4}) ${radius * 0.85}px, rgba(0,0,0,${dim}) ${radius * 1.1}px, rgba(0,0,0,${Math.min(0.95, dim + 0.08)}) 100%)`,
        }}
      />
      {/* Layer 2: corner vignette — anamorphic drop-off. */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(ellipse at center, transparent 45%, rgba(0,0,0,${dim * 0.3}) 100%)`,
          mixBlendMode: "multiply",
        }}
      />
      {/* Layer 3: faint warm inner rim — living spotlight vs dead mask. */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(circle at ${center.x}px ${center.y}px, rgba(255,240,210,${dim * 0.08}) 0, rgba(255,240,210,${dim * 0.04}) ${innerRimRadius}px, transparent ${radius * 0.9}px)`,
          mixBlendMode: "screen",
        }}
      />
    </AbsoluteFill>
  );
};
