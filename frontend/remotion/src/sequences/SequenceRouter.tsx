import React from "react";
import type {
  Aspect,
  Brand,
  CanvasKineticParams,
  CodeWindowParams,
  ComparisonSplitParams,
  DesignSequenceFrame,
  GradientKineticParams,
  HeadlinePunchParams,
  LogoRevealParams,
  SpecCardParams,
  TextScrollParams,
  UiZoomParams,
  WordKineticParams,
} from "../types";
import CanvasKinetic from "./CanvasKinetic";
import CodeWindow from "./CodeWindow";
import ComparisonSplit from "./ComparisonSplit";
import GradientKinetic from "./GradientKinetic";
import HeadlinePunch from "./HeadlinePunch";
import LogoReveal from "./LogoReveal";
import SpecCard from "./SpecCard";
import TextScroll from "./TextScroll";
import UiZoom from "./UiZoom";
import WordKinetic from "./WordKinetic";

type Props = {
  frame: DesignSequenceFrame;
  brand: Brand;
  brandName?: string;
  durationInFrames: number;
  aspect: Aspect;
};

/**
 * SequenceRouter — dispatches a DesignSequenceFrame to its template component.
 *
 * Each template owns its own bg, motion, and exit choreography. The router
 * just forwards the typed params, brand, and timing.
 *
 * If the frame's `template` doesn't match any known component (stale data
 * from an older planner), we render nothing — the empty AbsoluteFill in the
 * caller will still hold the slide's duration.
 */
export const SequenceRouter: React.FC<Props> = ({
  frame,
  brand,
  brandName,
  durationInFrames,
  aspect,
}) => {
  const common = { brand, brandName, durationInFrames, aspect };

  switch (frame.template) {
    case "gradient_kinetic":
      return (
        <GradientKinetic
          {...common}
          params={frame.params as GradientKineticParams}
        />
      );
    case "spec_card":
      return (
        <SpecCard {...common} params={frame.params as SpecCardParams} />
      );
    case "ui_zoom":
      return <UiZoom {...common} params={frame.params as UiZoomParams} />;
    case "code_window":
      return (
        <CodeWindow {...common} params={frame.params as CodeWindowParams} />
      );
    case "logo_reveal":
      return (
        <LogoReveal {...common} params={frame.params as LogoRevealParams} />
      );
    case "comparison_split":
      return (
        <ComparisonSplit
          {...common}
          params={frame.params as ComparisonSplitParams}
        />
      );
    case "text_scroll":
      return (
        <TextScroll {...common} params={frame.params as TextScrollParams} />
      );
    case "headline_punch":
      return (
        <HeadlinePunch
          {...common}
          params={frame.params as HeadlinePunchParams}
        />
      );
    case "word_kinetic":
      return (
        <WordKinetic
          {...common}
          params={frame.params as WordKineticParams}
        />
      );
    case "canvas_kinetic":
      return (
        <CanvasKinetic
          {...common}
          params={frame.params as CanvasKineticParams}
        />
      );
    default:
      return null;
  }
};
