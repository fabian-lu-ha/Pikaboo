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

/**
 * KineticLines — animated geometric lines as stylistic texture.
 *
 * Four patterns: diagonal, horizontal, underline, frame.
 * Animates as a draw-on (clip-path reveal) + draw-off.
 */
export const KineticLines: React.FC<Props> = ({
  params,
  brand,
  durationInFrames,
}) => {
  const f = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const inFrames = 14;
  const outFrames = 10;
  const drawIn = interpolate(f, [0, inFrames], [0, 100], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(
    f,
    [durationInFrames - outFrames, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  const accent = colorForRole(brand, "accent", "#fb923c");
  const lineThickness = Math.max(2, Math.round(Math.min(width, height) / 220));
  const pattern = params.pattern ?? "diagonal";

  return (
    <AbsoluteFill
      style={{ opacity: fadeOut, pointerEvents: "none" }}
    >
      {pattern === "diagonal" &&
        [0, 1, 2].map((i) => (
          <div
            key={i}
            style={{
              position: "absolute",
              top: `${20 + i * 25}%`,
              left: "-10%",
              width: "120%",
              height: lineThickness,
              backgroundColor: accent,
              transform: "rotate(-12deg)",
              transformOrigin: "left center",
              clipPath: `inset(0 ${100 - drawIn}% 0 0)`,
              opacity: 0.85 - i * 0.18,
            }}
          />
        ))}

      {pattern === "horizontal" &&
        [0, 1].map((i) => (
          <div
            key={i}
            style={{
              position: "absolute",
              top: `${30 + i * 40}%`,
              left: "5%",
              right: "5%",
              height: lineThickness,
              backgroundColor: accent,
              clipPath: `inset(0 ${100 - drawIn}% 0 0)`,
              opacity: 0.9 - i * 0.25,
            }}
          />
        ))}

      {pattern === "underline" && (
        <div
          style={{
            position: "absolute",
            bottom: "12%",
            left: "8%",
            right: "8%",
            height: lineThickness * 1.5,
            backgroundColor: accent,
            clipPath: `inset(0 ${100 - drawIn}% 0 0)`,
          }}
        />
      )}

      {pattern === "frame" && (
        <>
          <div
            style={{
              position: "absolute",
              top: "6%",
              left: "6%",
              right: "6%",
              height: lineThickness,
              backgroundColor: accent,
              clipPath: `inset(0 ${100 - drawIn}% 0 0)`,
            }}
          />
          <div
            style={{
              position: "absolute",
              bottom: "6%",
              left: "6%",
              right: "6%",
              height: lineThickness,
              backgroundColor: accent,
              clipPath: `inset(0 0 0 ${100 - drawIn}%)`,
            }}
          />
          <div
            style={{
              position: "absolute",
              top: "6%",
              bottom: "6%",
              left: "6%",
              width: lineThickness,
              backgroundColor: accent,
              clipPath: `inset(${100 - drawIn}% 0 0 0)`,
            }}
          />
          <div
            style={{
              position: "absolute",
              top: "6%",
              bottom: "6%",
              right: "6%",
              width: lineThickness,
              backgroundColor: accent,
              clipPath: `inset(0 0 ${100 - drawIn}% 0)`,
            }}
          />
        </>
      )}
    </AbsoluteFill>
  );
};
