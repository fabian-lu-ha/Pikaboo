import React from "react";
import { Composition, type CalculateMetadataFunction } from "remotion";
import { MarketingVideo } from "./MarketingVideo";
import {
  DEFAULT_FRAME_DURATION_MS,
  FPS,
  dimensionsForAspect,
  type MarketingVideoProps,
} from "./types";

/**
 * Convert a frame's storyboard duration (ms) to a frame count at our fixed FPS.
 * Always rounded up so a frame never disappears before its caption renders.
 */
const frameDurationToFrames = (durationMs: number | undefined): number => {
  const ms =
    typeof durationMs === "number" && durationMs > 0
      ? durationMs
      : DEFAULT_FRAME_DURATION_MS;
  return Math.max(1, Math.ceil((ms * FPS) / 1000));
};

// Default duration for an interleaved Veo bridge clip when the prop is
// present but we can't probe its real metadata. Backend renders bridges at
// 4s @ 30fps = 120 frames. Kept in sync with DEFAULT_BRIDGE_FRAMES inside
// MarketingVideo.tsx (the two MUST agree or the composition's
// durationInFrames will drift from the rendered timeline).
const DEFAULT_BRIDGE_FRAMES = 120;

const calculateMetadata: CalculateMetadataFunction<MarketingVideoProps> = ({
  props,
}) => {
  const { width, height } = dimensionsForAspect(props.aspect);

  const clipFrames = props.frames.reduce<number>((sum, frame) => {
    return sum + frameDurationToFrames(frame.duration_ms);
  }, 0);

  // Bookends contribute their own duration. Both are optional — when missing
  // the composition is just the Series of clips.
  const titleFrames = props.title_card
    ? frameDurationToFrames(props.title_card.duration_ms)
    : 0;
  const endFrames = props.end_card
    ? frameDurationToFrames(props.end_card.duration_ms)
    : 0;

  // Account for any veo_bridge clips interleaved between adjacent scenes.
  // A bridge only contributes when (1) transitions is well-formed
  // (length === frames.length - 1) AND (2) the entry has style=veo_bridge
  // AND (3) clip_url is a non-empty string. Mirrors the validation inside
  // MarketingVideo so duration stays in lockstep with the rendered Series.
  let bridgeFrames = 0;
  if (
    Array.isArray(props.transitions) &&
    props.frames.length > 0 &&
    props.transitions.length === props.frames.length - 1
  ) {
    for (const t of props.transitions) {
      if (
        t.style === "veo_bridge" &&
        typeof t.clip_url === "string" &&
        t.clip_url.length > 0
      ) {
        bridgeFrames += DEFAULT_BRIDGE_FRAMES;
      }
    }
  }

  const totalFrames = titleFrames + clipFrames + bridgeFrames + endFrames;

  return {
    width,
    height,
    fps: FPS,
    // Fall back to 1s for an empty storyboard so the renderer never receives
    // durationInFrames=0 (which Remotion rejects).
    durationInFrames: Math.max(FPS, totalFrames),
  };
};

/**
 * Default props used by the Remotion Studio preview when nothing is passed
 * via --props. The CLI always overrides these in production renders.
 */
const defaultProps: MarketingVideoProps = {
  aspect: "9:16",
  brand: {
    palette: ["#0f172a", "#f8fafc", "#38bdf8", "#fb923c"],
    palette_roles: [
      { hex: "#0f172a", role: "background" },
      { hex: "#f8fafc", role: "text" },
      { hex: "#38bdf8", role: "accent" },
    ],
    headline_font: "Inter",
    body_font: "Inter",
  },
  frames: [
    {
      clip_url:
        "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
      caption: "Storyboard preview",
      duration_ms: 2500,
    },
  ],
  title_card: { text: "Built for makers", duration_ms: 1400 },
  end_card: { headline: "Brewed for shipping", cta: "Try it free", duration_ms: 2000 },
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="MarketingVideo"
      component={MarketingVideo}
      // Placeholders — overridden by calculateMetadata before render.
      durationInFrames={FPS * 5}
      fps={FPS}
      width={1080}
      height={1920}
      defaultProps={defaultProps}
      calculateMetadata={calculateMetadata}
    />
  );
};
