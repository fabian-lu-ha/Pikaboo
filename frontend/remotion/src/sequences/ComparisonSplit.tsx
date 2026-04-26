import React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { ComparisonSplitParams } from "../types";
import {
  DEFAULT_BODY_FONT,
  DEFAULT_HEADLINE_FONT,
  type DesignSequenceProps,
  hexToRgba,
  palette,
  resolveRole,
  scaledSize,
} from "./shared";

/**
 * ComparisonSplit — Apple "Switch to Mac" before/after.
 *
 * - Vertical (default) or horizontal split.
 * - "Before" side: desaturated + slightly dimmer.
 * - "After" side: full color.
 * - Split line slides in from the matching edge over 8 frames.
 * - Labels fade in independently — left/top first, then right/bottom (6-frame stagger).
 * - Optional accent BEFORE/AFTER badges in the matching corner.
 * - Exit: split line retracts to center, labels fade out.
 */
const ComparisonSplit: React.FC<DesignSequenceProps<ComparisonSplitParams>> = ({
  params,
  brand,
  durationInFrames,
}) => {
  const f = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const orientation = params.orientation ?? "v";
  const isVertical = orientation === "v";

  /* Timing. */
  const lineInEnd = 8;
  const beforeLabelStart = lineInEnd + 2;
  const beforeLabelInEnd = beforeLabelStart + 10;
  const afterLabelStart = beforeLabelStart + 6;
  const afterLabelInEnd = afterLabelStart + 10;
  const exitStart = durationInFrames - 14;

  /* Split line slides from the matching edge to center. */
  // For vertical orientation: line is vertical, comes in from left
  // For horizontal orientation: line is horizontal, comes in from top
  const splitProgress = interpolate(f, [0, lineInEnd], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const splitExit = interpolate(
    f,
    [exitStart, durationInFrames],
    [1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.in(Easing.cubic),
    },
  );

  /* Label opacities — staggered + exit on the way out. */
  const beforeLabelOpacity = Math.min(
    interpolate(f, [beforeLabelStart, beforeLabelInEnd], [0, 1], {
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
  const afterLabelOpacity = Math.min(
    interpolate(f, [afterLabelStart, afterLabelInEnd], [0, 1], {
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

  /* Whole-frame fade-in. */
  const frameFadeIn = interpolate(f, [0, 6], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  /* Theming. */
  const accent = resolveRole(brand, "accent", "#fb923c");
  const bg0 = palette(brand, 0, "#0b0b0c");
  const bg1 = palette(brand, 1, "#1a1a1a");

  const headlineFont = brand.headline_font ?? DEFAULT_HEADLINE_FONT;
  const bodyFont = brand.body_font ?? DEFAULT_BODY_FONT;
  const labelSize = scaledSize(width, height, 42);
  const badgeSize = scaledSize(width, height, 22);

  /* Side rendering. Each side gets a clip path that splits the canvas. */
  const renderSide = (
    side: { label: string; image_url?: string | null },
    role: "before" | "after",
  ) => {
    const isBefore = role === "before";
    // Clip path for each side.
    let clip: string;
    if (isVertical) {
      clip = isBefore
        ? "polygon(0 0, 50% 0, 50% 100%, 0 100%)"
        : "polygon(50% 0, 100% 0, 100% 100%, 50% 100%)";
    } else {
      clip = isBefore
        ? "polygon(0 0, 100% 0, 100% 50%, 0 50%)"
        : "polygon(0 50%, 100% 50%, 100% 100%, 0 100%)";
    }
    const filter = isBefore ? "saturate(0.18) brightness(0.7)" : "saturate(1) brightness(1)";

    return (
      <AbsoluteFill
        style={{
          clipPath: clip,
          filter,
        }}
      >
        {side.image_url ? (
          <Img
            src={side.image_url}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              display: "block",
            }}
          />
        ) : (
          <AbsoluteFill
            style={{
              background: isBefore
                ? `linear-gradient(135deg, ${bg0} 0%, ${bg1} 100%)`
                : `linear-gradient(135deg, ${bg1} 0%, ${hexToRgba(accent, 0.4)} 100%)`,
            }}
          />
        )}
      </AbsoluteFill>
    );
  };

  /* Split line geometry. */
  const lineThickness = Math.max(2, scaledSize(width, height, 6));
  const lineOpacity = splitExit;
  const lineProgress = splitProgress;

  let lineStyle: React.CSSProperties;
  if (isVertical) {
    // Vertical line — slides in from the left, settles at 50%.
    const lineH = height * lineProgress;
    lineStyle = {
      position: "absolute",
      left: width / 2 - lineThickness / 2,
      top: (height - lineH) / 2,
      width: lineThickness,
      height: lineH,
      background: `linear-gradient(180deg, transparent 0%, ${accent} 12%, ${accent} 88%, transparent 100%)`,
      boxShadow: `0 0 24px ${hexToRgba(accent, 0.8)}`,
      opacity: lineOpacity,
      pointerEvents: "none",
    };
  } else {
    const lineW = width * lineProgress;
    lineStyle = {
      position: "absolute",
      top: height / 2 - lineThickness / 2,
      left: (width - lineW) / 2,
      height: lineThickness,
      width: lineW,
      background: `linear-gradient(90deg, transparent 0%, ${accent} 12%, ${accent} 88%, transparent 100%)`,
      boxShadow: `0 0 24px ${hexToRgba(accent, 0.8)}`,
      opacity: lineOpacity,
      pointerEvents: "none",
    };
  }

  /* Label positions — anchored to side centers, offset toward outer edges. */
  const beforeLabelStyle: React.CSSProperties = isVertical
    ? {
        position: "absolute",
        left: 0,
        right: width / 2,
        bottom: Math.round(height * 0.12),
        textAlign: "center",
        opacity: beforeLabelOpacity,
        padding: `0 ${Math.round(width * 0.04)}px`,
      }
    : {
        position: "absolute",
        top: Math.round(height * 0.12),
        left: 0,
        right: 0,
        bottom: height / 2,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        opacity: beforeLabelOpacity,
        padding: `0 ${Math.round(width * 0.04)}px`,
      };
  const afterLabelStyle: React.CSSProperties = isVertical
    ? {
        position: "absolute",
        left: width / 2,
        right: 0,
        bottom: Math.round(height * 0.12),
        textAlign: "center",
        opacity: afterLabelOpacity,
        padding: `0 ${Math.round(width * 0.04)}px`,
      }
    : {
        position: "absolute",
        top: height / 2,
        left: 0,
        right: 0,
        bottom: Math.round(height * 0.12),
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "center",
        opacity: afterLabelOpacity,
        padding: `0 ${Math.round(width * 0.04)}px`,
      };

  /* Badge positions — opposite corners, BEFORE in the before-side corner. */
  const beforeBadgeStyle: React.CSSProperties = isVertical
    ? { position: "absolute", left: Math.round(width * 0.04), top: Math.round(height * 0.06) }
    : { position: "absolute", left: Math.round(width * 0.04), top: Math.round(height * 0.04) };
  const afterBadgeStyle: React.CSSProperties = isVertical
    ? { position: "absolute", right: Math.round(width * 0.04), top: Math.round(height * 0.06) }
    : { position: "absolute", right: Math.round(width * 0.04), bottom: Math.round(height * 0.04) };

  const labelTextStyle: React.CSSProperties = {
    fontFamily: headlineFont,
    fontWeight: 700,
    fontSize: labelSize,
    color: "#ffffff",
    lineHeight: 1.1,
    letterSpacing: "-0.01em",
    textShadow: "0 4px 20px rgba(0,0,0,0.7), 0 2px 6px rgba(0,0,0,0.5)",
    maxWidth: isVertical ? "92%" : "80%",
    display: "inline-block",
  };

  const badgeBaseStyle: React.CSSProperties = {
    fontFamily: bodyFont,
    fontWeight: 700,
    fontSize: badgeSize,
    color: "#ffffff",
    backgroundColor: hexToRgba("#0b0b0c", 0.65),
    padding: `${Math.round(badgeSize * 0.4)}px ${Math.round(badgeSize * 0.85)}px`,
    borderRadius: 6,
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    border: `1px solid ${hexToRgba("#ffffff", 0.18)}`,
    backdropFilter: "blur(6px)",
    pointerEvents: "none",
  };

  return (
    <AbsoluteFill
      style={{
        backgroundColor: bg0,
        opacity: frameFadeIn,
      }}
    >
      {renderSide(params.before, "before")}
      {renderSide(params.after, "after")}

      {/* Split divider line. */}
      <div style={lineStyle} />

      {/* Badges. */}
      <div style={{ ...beforeBadgeStyle, opacity: beforeLabelOpacity }}>
        <span style={{ ...badgeBaseStyle }}>BEFORE</span>
      </div>
      <div style={{ ...afterBadgeStyle, opacity: afterLabelOpacity }}>
        <span
          style={{
            ...badgeBaseStyle,
            backgroundColor: hexToRgba(accent, 0.85),
            border: `1px solid ${hexToRgba(accent, 0.9)}`,
          }}
        >
          AFTER
        </span>
      </div>

      {/* Labels. */}
      <div style={beforeLabelStyle}>
        <span style={labelTextStyle}>{params.before.label}</span>
      </div>
      <div style={afterLabelStyle}>
        <span style={labelTextStyle}>{params.after.label}</span>
      </div>
    </AbsoluteFill>
  );
};

export default ComparisonSplit;
