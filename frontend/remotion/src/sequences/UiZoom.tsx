import React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { FocalZone, UiZoomParams } from "../types";
import { zoneCenter } from "../effects/zone";
import {
  DEFAULT_BODY_FONT,
  type DesignSequenceProps,
  hexToRgba,
  palette,
  resolveRole,
  scaledSize,
} from "./shared";

/**
 * UiZoom — Stripe-style demo zoom into a screenshot.
 *
 * - Background: params.image_url (a UI screenshot).
 * - Starts wide (scale ~0.85), pushes in to a focal region (~2.4×) with
 *   cubic in-out easing.
 * - Optional label: small badge with a line pointing at the focus area.
 *   Fades in at ~60% through the duration.
 * - Subtle vignette at all times for cinematic weight.
 * - On exit, the camera continues forward slightly while everything fades —
 *   no static hold at the end.
 *
 * If image_url is missing, falls back to a brand-palette gradient placeholder.
 */
const UiZoom: React.FC<DesignSequenceProps<UiZoomParams>> = ({
  params,
  brand,
  durationInFrames,
}) => {
  const f = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const imageUrl = params.image_url ?? null;
  const focusZone: FocalZone = params.focus_zone ?? "mc";
  const label = (params.label ?? "").trim();

  /* Camera scale: 0.85 → 2.4 over the duration, then bloom slightly on exit. */
  const exitStart = durationInFrames - 14;

  const inScale = interpolate(
    f,
    [0, exitStart],
    [0.85, 2.4],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.cubic),
    },
  );
  const exitScale = interpolate(
    f,
    [exitStart, durationInFrames],
    [1.0, 1.06],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.in(Easing.cubic),
    },
  );
  const scale = inScale * exitScale;

  /* Camera target — slowly drifts toward the focal zone center. */
  const focal = zoneCenter(focusZone, width, height);
  // Shift origin toward focal point as we zoom; biased so wide shot stays balanced.
  const originX = interpolate(f, [0, exitStart], [width / 2, focal.x], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  const originY = interpolate(f, [0, exitStart], [height / 2, focal.y], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });

  /* Label appears at ~60% through, then exits with the rest. */
  const labelStart = Math.floor(durationInFrames * 0.6);
  const labelInEnd = labelStart + 12;
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

  /* Whole-frame fade-in/out — gives the zoom an entry, not just an instant
     full-opacity start. */
  const fadeIn = interpolate(f, [0, 8], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(
    f,
    [exitStart, durationInFrames],
    [1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.in(Easing.cubic),
    },
  );
  const opacity = Math.min(fadeIn, fadeOut);

  const bodyFont = brand.body_font ?? DEFAULT_BODY_FONT;
  const accent = resolveRole(brand, "accent", "#fb923c");
  const stop0 = palette(brand, 0, "#0f172a");
  const stop1 = palette(brand, 1, "#1e293b");
  const stop2 = palette(brand, 2, accent);

  const labelSize = scaledSize(width, height, 28);

  /* Position the line endpoint near the label, pointing AT the focal point. */
  // Place the badge in a corner opposite the focal point (rough mirror).
  const isLeft = focal.x > width * 0.5;
  const isTop = focal.y > height * 0.5;
  const badgePos: React.CSSProperties = {
    position: "absolute",
    [isLeft ? "left" : "right"]: Math.round(width * 0.08),
    [isTop ? "top" : "bottom"]: Math.round(height * 0.12),
  };
  // Anchor for the line — measure roughly from the badge corner toward focal.
  const badgeAnchor = {
    x: isLeft ? width * 0.08 + 60 : width * 0.92 - 60,
    y: isTop ? height * 0.12 + 30 : height * 0.88 - 30,
  };
  const lineLength = Math.hypot(focal.x - badgeAnchor.x, focal.y - badgeAnchor.y);
  const lineAngle =
    (Math.atan2(focal.y - badgeAnchor.y, focal.x - badgeAnchor.x) * 180) / Math.PI;

  return (
    <AbsoluteFill style={{ backgroundColor: stop0, opacity }}>
      {/* Background medium — scaled around drift origin. */}
      <AbsoluteFill
        style={{
          transform: `scale(${scale})`,
          transformOrigin: `${originX}px ${originY}px`,
        }}
      >
        {imageUrl ? (
          <Img
            src={imageUrl}
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
              background: `linear-gradient(135deg, ${stop0} 0%, ${stop1} 50%, ${stop2} 100%)`,
            }}
          >
            {/* Faux-UI placeholder grid so even the fallback feels structured. */}
            <AbsoluteFill
              style={{
                opacity: 0.18,
                backgroundImage: `linear-gradient(${hexToRgba("#ffffff", 0.5)} 1px, transparent 1px), linear-gradient(90deg, ${hexToRgba("#ffffff", 0.5)} 1px, transparent 1px)`,
                backgroundSize: "120px 120px",
              }}
            />
          </AbsoluteFill>
        )}
      </AbsoluteFill>

      {/* Vignette — subtle corner darkening for cinematic weight. */}
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,0.45) 100%)",
          mixBlendMode: "multiply",
          pointerEvents: "none",
        }}
      />

      {/* Label + indicator line — fades in late. */}
      {label ? (
        <>
          {/* Indicator line drawn from badge toward focal point. */}
          <div
            style={{
              position: "absolute",
              left: badgeAnchor.x,
              top: badgeAnchor.y,
              width: lineLength,
              height: 2,
              backgroundColor: accent,
              transform: `rotate(${lineAngle}deg)`,
              transformOrigin: "left center",
              opacity: labelOpacity * 0.85,
              pointerEvents: "none",
              borderRadius: "999px",
              boxShadow: `0 0 12px ${hexToRgba(accent, 0.6)}`,
            }}
          />
          {/* Endpoint dot at focal area. */}
          <div
            style={{
              position: "absolute",
              left: focal.x - 8,
              top: focal.y - 8,
              width: 16,
              height: 16,
              borderRadius: "50%",
              border: `2px solid ${accent}`,
              boxShadow: `0 0 18px ${hexToRgba(accent, 0.7)}`,
              opacity: labelOpacity,
              pointerEvents: "none",
            }}
          />
          {/* Badge. */}
          <div
            style={{
              ...badgePos,
              opacity: labelOpacity,
              fontFamily: bodyFont,
              fontWeight: 600,
              fontSize: labelSize,
              color: "#ffffff",
              backgroundColor: hexToRgba("#0b0b0c", 0.78),
              padding: `${Math.round(labelSize * 0.45)}px ${Math.round(labelSize * 0.85)}px`,
              borderRadius: 8,
              border: `1px solid ${hexToRgba(accent, 0.5)}`,
              backdropFilter: "blur(8px)",
              letterSpacing: "0.01em",
              whiteSpace: "nowrap",
              pointerEvents: "none",
            }}
          >
            {label}
          </div>
        </>
      ) : null}
    </AbsoluteFill>
  );
};

export default UiZoom;
