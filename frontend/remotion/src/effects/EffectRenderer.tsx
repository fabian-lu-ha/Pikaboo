import React from "react";
import { Sequence, useVideoConfig } from "remotion";
import type { Brand, Effect } from "../types";
import { BrandStinger } from "./BrandStinger";
import { DataPop } from "./DataPop";
import { KineticLines } from "./KineticLines";
import { KineticText } from "./KineticText";
import { LowerThird } from "./LowerThird";
import { Spotlight } from "./Spotlight";

type Props = {
  effect: Effect;
  brand: Brand;
  shotDurationInFrames: number;
};

const msToFrames = (ms: number, fps: number): number =>
  Math.max(1, Math.ceil((ms * fps) / 1000));

/**
 * EffectRenderer — dispatches an Effect to the right component, and
 * positions it inside the shot's timeline via a Sequence.
 *
 * If the effect has start_ms / duration_ms, the Sequence honors them.
 * Otherwise the effect spans the full shot duration.
 *
 * Effect components themselves use useCurrentFrame() relative to the
 * Sequence — so each effect's local timeline starts at 0 regardless of
 * where it sits inside the shot.
 */
export const EffectRenderer: React.FC<Props> = ({
  effect,
  brand,
  shotDurationInFrames,
}) => {
  const { fps } = useVideoConfig();

  const startFrame =
    typeof effect.start_ms === "number" && effect.start_ms > 0
      ? msToFrames(effect.start_ms, fps)
      : 0;

  const requested =
    typeof effect.duration_ms === "number" && effect.duration_ms > 0
      ? msToFrames(effect.duration_ms, fps)
      : shotDurationInFrames - startFrame;

  // Don't let an effect run past the end of its shot.
  const duration = Math.max(1, Math.min(requested, shotDurationInFrames - startFrame));
  if (duration <= 0) return null;

  const params = effect.params ?? {};

  let body: React.ReactNode = null;
  switch (effect.kind) {
    case "kinetic_text":
      body = (
        <KineticText
          params={params}
          brand={brand}
          durationInFrames={duration}
        />
      );
      break;
    case "lower_third":
      body = (
        <LowerThird
          params={params}
          brand={brand}
          durationInFrames={duration}
        />
      );
      break;
    case "brand_stinger":
      body = (
        <BrandStinger
          params={params}
          brand={brand}
          durationInFrames={duration}
        />
      );
      break;
    case "spotlight":
      body = (
        <Spotlight
          params={params}
          brand={brand}
          durationInFrames={duration}
        />
      );
      break;
    case "kinetic_lines":
      body = (
        <KineticLines
          params={params}
          brand={brand}
          durationInFrames={duration}
        />
      );
      break;
    case "data_pop":
      body = (
        <DataPop params={params} brand={brand} durationInFrames={duration} />
      );
      break;
    default:
      // Unknown kind — render nothing; the planner shouldn't emit unknowns
      // post-normalize, but this keeps Remotion from crashing on stale data.
      body = null;
  }

  if (!body) return null;
  return (
    <Sequence from={startFrame} durationInFrames={duration} layout="none">
      {body}
    </Sequence>
  );
};
