import React, { useMemo } from "react";
import {
  AbsoluteFill,
  Img,
  OffthreadVideo,
  Series,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import {
  DEFAULT_FRAME_DURATION_MS,
  FPS,
  isDesignSequenceFrame,
  type Brand,
  type CaptionMotion,
  type DesignSequenceFrame,
  type EndCard,
  type FocalZone,
  type Frame,
  type LiveActionFrame as LiveActionFrameType,
  type MarketingVideoProps,
  type TitleCard,
  type Transition,
} from "./types";
import { EffectRenderer } from "./effects/EffectRenderer";
import { SequenceRouter } from "./sequences/SequenceRouter";

/* ────────────────────────────────────────────────────────────────────────── */
/* Constants                                                                  */
/* ────────────────────────────────────────────────────────────────────────── */

// Frames over which adjacent slides crossfade. Keeping it short prevents the
// caption from being readable over a half-blended image.
const FADE_FRAMES = 12;

// Ken Burns end-scale; the slide grows from 1.0 → KEN_BURNS_END_SCALE over
// its full duration. 6% drift is enough to feel alive without obvious cropping.
const KEN_BURNS_END_SCALE = 1.06;

// Storyboard inputs that map to social UI safe zones for 9:16 (Stories/Reels).
// These match the iOS/Android system bars + reaction strip the user specified.
const STORIES_SAFE_TOP_PX = 250;
const STORIES_SAFE_BOTTOM_PX = 280;

// On 16:9 / 1:1 we don't have a chrome overlap problem, so we use generic
// breathing room instead.
const GENERIC_SAFE_BOTTOM_PCT = 0.08;

/* ────────────────────────────────────────────────────────────────────────── */
/* Helpers                                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

const frameDurationToFrames = (durationMs: number | undefined): number => {
  const ms =
    typeof durationMs === "number" && durationMs > 0
      ? durationMs
      : DEFAULT_FRAME_DURATION_MS;
  return Math.max(1, Math.ceil((ms * FPS) / 1000));
};

/**
 * Resolve a logical role (e.g. "text", "accent", "background") to a hex from
 * the brand. Falls back to the provided default when the role isn't mapped.
 */
const colorForRole = (
  brand: Brand,
  role: string,
  fallback: string,
): string => {
  const match = brand.palette_roles?.find(
    (entry) => entry.role.toLowerCase() === role.toLowerCase(),
  );
  return match?.hex ?? fallback;
};

/**
 * Pick a caption font-size that scales to the canvas. The values below were
 * tuned against 1920×1080 (64px) and 1080×1920 (56px) so captions never feel
 * either cramped or oversized for the format.
 */
const captionFontSize = (width: number, height: number): number => {
  const isPortrait = height > width;
  if (isPortrait) {
    // 56px on 1080×1920 — scales linearly with width below that.
    return Math.round(width * (56 / 1080));
  }
  // 64px on 1920×1080.
  return Math.round(height * (64 / 1080));
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Focal-zone → caption-zone mapping                                          */
/* ────────────────────────────────────────────────────────────────────────── */

type CaptionZone = {
  /** Which vertical band the caption anchors to. */
  vertical: "top" | "middle" | "bottom";
  /** Which horizontal alignment the caption uses inside its band. */
  horizontal: "left" | "center" | "right";
};

/**
 * Place the caption in the OPPOSITE quadrant from the subject.
 *
 *   - Subject in top half  → caption goes bottom.
 *   - Subject in bottom half → caption goes top.
 *   - Subject in middle row → caption goes bottom (safer, works for wide subjects).
 *   - Subject left/right → caption mirrors horizontally; center stays center.
 */
const captionZoneFromFocal = (focal: FocalZone): CaptionZone => {
  switch (focal) {
    case "tl":
      return { vertical: "bottom", horizontal: "right" };
    case "tc":
      return { vertical: "bottom", horizontal: "center" };
    case "tr":
      return { vertical: "bottom", horizontal: "left" };
    case "ml":
      return { vertical: "bottom", horizontal: "right" };
    case "mc":
      return { vertical: "bottom", horizontal: "center" };
    case "mr":
      return { vertical: "bottom", horizontal: "left" };
    case "bl":
      return { vertical: "top", horizontal: "right" };
    case "bc":
      return { vertical: "top", horizontal: "center" };
    case "br":
      return { vertical: "top", horizontal: "left" };
  }
};

/**
 * Caption band sizing — bandHeight + horizontal padding only. Vertical
 * placement (top vs bottom) is decided by the focal-zone mapping at the call
 * site, but we still respect the platform-specific safe-zone constants.
 */
const captionSafeZone = (
  aspect: MarketingVideoProps["aspect"],
  width: number,
  height: number,
): {
  topInset: number;
  bottomInset: number;
  bandHeight: number;
  horizontalPadding: number;
} => {
  if (aspect === "9:16") {
    return {
      topInset: STORIES_SAFE_TOP_PX,
      bottomInset: STORIES_SAFE_BOTTOM_PX,
      bandHeight: Math.round(height * 0.18),
      horizontalPadding: Math.round(width * 0.08),
    };
  }
  const generic = Math.round(height * GENERIC_SAFE_BOTTOM_PCT);
  return {
    topInset: generic,
    bottomInset: generic,
    bandHeight: Math.round(height * 0.18),
    horizontalPadding: Math.round(width * 0.08),
  };
};

const horizontalToFlexJustify = (
  h: CaptionZone["horizontal"],
): React.CSSProperties["justifyContent"] => {
  switch (h) {
    case "left":
      return "flex-start";
    case "right":
      return "flex-end";
    case "center":
      return "center";
  }
};

const horizontalToTextAlign = (
  h: CaptionZone["horizontal"],
): React.CSSProperties["textAlign"] => {
  switch (h) {
    case "left":
      return "left";
    case "right":
      return "right";
    case "center":
      return "center";
  }
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Caption motion variants                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

type CaptionRenderProps = {
  text: string;
  motion: CaptionMotion;
  localFrame: number;
  baseStyle: React.CSSProperties;
};

const CaptionContent: React.FC<CaptionRenderProps> = ({
  text,
  motion,
  localFrame,
  baseStyle,
}) => {
  if (motion === "letter-by-letter") {
    // Stagger one frame per character; if the caption is longer than the
    // available in-window, accelerate so every letter still finishes in time.
    const chars = Array.from(text);
    const perCharDelay = chars.length > 0
      ? Math.max(1, Math.floor(FADE_FRAMES / Math.max(chars.length, 1)))
      : 1;
    return (
      <span style={baseStyle}>
        {chars.map((ch, i) => {
          const start = i * perCharDelay;
          const end = start + Math.max(2, perCharDelay + 1);
          const opacity = interpolate(localFrame, [start, end], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          return (
            <span
              key={i}
              style={{
                opacity,
                // Preserve whitespace verbatim so spacing matches the source.
                whiteSpace: "pre",
              }}
            >
              {ch}
            </span>
          );
        })}
      </span>
    );
  }

  return <span style={baseStyle}>{text}</span>;
};

/* ────────────────────────────────────────────────────────────────────────── */
/* CaptionLayer — shared overlay used by live-action AND design-sequence      */
/* frames. Decides band position from focal_zone, applies brand typography,   */
/* and runs the in/out motion. Pure presentational; takes localFrame from     */
/* the caller's <Series.Sequence> so its timeline is per-slide.               */
/* ────────────────────────────────────────────────────────────────────────── */

type CaptionLayerProps = {
  text: string;
  brand: Brand;
  aspect: MarketingVideoProps["aspect"];
  focalZone: FocalZone;
  localFrame: number;
  width: number;
  height: number;
  // When false (default), no scrim is drawn behind the caption — used for
  // design-sequence frames where the template owns its own background and
  // a scrim would muddy the composition.
  withScrim?: boolean;
  /**
   * Per-frame adaptive caption color from the backend (or null/undefined to
   * fall back to the brand `text` palette role). When the caller passes a
   * value, we trust it — backend has already weighed background luminance
   * + scrim presence. We bias slightly toward warm white when the scrim
   * is on (good legibility against arbitrary Veo footage) and toward the
   * full provided value otherwise.
   */
  captionColorOverride?: string | null;
};

const CaptionLayer: React.FC<CaptionLayerProps> = ({
  text,
  brand,
  aspect,
  focalZone,
  localFrame,
  width,
  height,
  withScrim = true,
  captionColorOverride,
}) => {
  const captionMotion: CaptionMotion = brand.caption_motion ?? "slide-up";
  const captionTranslateY =
    captionMotion === "slide-up"
      ? interpolate(localFrame, [0, FADE_FRAMES], [40, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })
      : 0;
  const captionWrapperOpacity =
    captionMotion === "letter-by-letter"
      ? 1
      : interpolate(localFrame, [0, FADE_FRAMES], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });

  const headlineFont =
    brand.headline_font ?? "system-ui, -apple-system, sans-serif";
  // Adaptive: per-frame override wins; brand role is the legacy fallback.
  const captionColor =
    typeof captionColorOverride === "string" && captionColorOverride.length > 0
      ? captionColorOverride
      : colorForRole(brand, "text", "#ffffff");
  const fontSize = captionFontSize(width, height);
  const safe = captionSafeZone(aspect, width, height);
  const zone = captionZoneFromFocal(focalZone);

  const captionPositionStyle: React.CSSProperties =
    zone.vertical === "top"
      ? {
          top: safe.topInset,
          left: safe.horizontalPadding,
          right: safe.horizontalPadding,
          height: safe.bandHeight,
        }
      : {
          bottom: safe.bottomInset,
          left: safe.horizontalPadding,
          right: safe.horizontalPadding,
          height: safe.bandHeight,
        };

  const captionWeight = brand.caption_weight ?? 700;
  const captionTrackingEm = brand.caption_tracking_em ?? -0.01;
  const captionUppercase = brand.caption_all_caps === true;

  const captionTextStyle: React.CSSProperties = {
    fontFamily: headlineFont,
    fontWeight: captionWeight,
    fontSize,
    lineHeight: 1.15,
    color: captionColor,
    textShadow:
      "0 2px 4px rgba(0,0,0,0.55), 0 4px 16px rgba(0,0,0,0.45)",
    letterSpacing: `${captionTrackingEm}em`,
    textTransform: captionUppercase ? "uppercase" : "none",
    maxWidth: "92%",
    display: "inline-block",
    textAlign: horizontalToTextAlign(zone.horizontal),
  };

  return (
    <>
      {withScrim ? (
        <AbsoluteFill
          style={{
            background:
              zone.vertical === "top"
                ? "linear-gradient(to top, rgba(0,0,0,0) 55%, rgba(0,0,0,0.55) 100%)"
                : "linear-gradient(to bottom, rgba(0,0,0,0) 55%, rgba(0,0,0,0.55) 100%)",
            pointerEvents: "none",
          }}
        />
      ) : null}
      <div
        style={{
          position: "absolute",
          ...captionPositionStyle,
          display: "flex",
          alignItems: "center",
          justifyContent: horizontalToFlexJustify(zone.horizontal),
          textAlign: horizontalToTextAlign(zone.horizontal),
          opacity: captionWrapperOpacity,
          transform: `translateY(${captionTranslateY}px)`,
        }}
      >
        <CaptionContent
          text={text}
          motion={captionMotion}
          localFrame={localFrame}
          baseStyle={captionTextStyle}
        />
      </div>
    </>
  );
};

/* ────────────────────────────────────────────────────────────────────────── */
/* StoryboardFrame — renders a single slide inside its Series.Sequence        */
/* ────────────────────────────────────────────────────────────────────────── */

type StoryboardFrameProps = {
  frame: Frame;
  brand: Brand;
  brandName?: string;
  durationInFrames: number;
  aspect: MarketingVideoProps["aspect"];
  /**
   * Number of frames over which the slide fades in. 0 = hard cut (no fade).
   * Parent decides this based on what kind of transition sits BEFORE this
   * scene (match_cut / veo_bridge → 0; crossfade or first slide → 12).
   */
  fadeInFrames: number;
  /**
   * Number of frames over which the slide fades out. 0 = hard cut (no fade).
   * Parent decides this based on what kind of transition sits AFTER this
   * scene (match_cut / veo_bridge → 0; crossfade or last slide → 12).
   */
  fadeOutFrames: number;
};

const StoryboardFrame: React.FC<StoryboardFrameProps> = ({
  frame,
  brand,
  brandName,
  durationInFrames,
  aspect,
  fadeInFrames,
  fadeOutFrames,
}) => {
  const localFrame = useCurrentFrame();
  const { width, height } = useVideoConfig();

  /* Per-pair crossfade in/out. fadeInFrames/fadeOutFrames === 0 means the
     incoming/outgoing transition is a hard cut (match_cut) or handled by
     a Veo bridge clip — skip the opacity blend entirely. */
  const fadeIn =
    fadeInFrames <= 0
      ? 1
      : interpolate(localFrame, [0, fadeInFrames], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
  const fadeOut =
    fadeOutFrames <= 0
      ? 1
      : interpolate(
          localFrame,
          [durationInFrames - fadeOutFrames, durationInFrames],
          [1, 0],
          { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
        );
  const slideOpacity = Math.min(fadeIn, fadeOut);

  const backgroundColor = colorForRole(brand, "background", "#000000");

  /* ───────────────────────────────────────────────────────────────────────
     Design-sequence branch. Pure-graphic beat composed by SequenceRouter.
     The router's child template owns its own bg, motion, and exit; we
     just provide slide-level fade + an optional caption overlay.
     ─────────────────────────────────────────────────────────────────────── */
  if (isDesignSequenceFrame(frame)) {
    const designFrame: DesignSequenceFrame = frame;
    return (
      <AbsoluteFill style={{ backgroundColor, opacity: slideOpacity }}>
        <SequenceRouter
          frame={designFrame}
          brand={brand}
          brandName={brandName}
          durationInFrames={durationInFrames}
          aspect={aspect}
        />
        {designFrame.caption ? (
          <CaptionLayer
            text={designFrame.caption}
            brand={brand}
            aspect={aspect}
            focalZone={designFrame.focal_zone ?? "mc"}
            localFrame={localFrame}
            width={width}
            height={height}
            // Design templates render their own contrast-managed bg, so
            // skip the scrim — it would dim the template needlessly.
            withScrim={false}
            // Design frames don't currently have a per-frame caption_color
            // (templates pick foreground type internally). Passing through
            // the field anyway keeps the contract one-way: if the planner
            // ever sets it on a design frame, the caption respects it.
            captionColorOverride={
              (designFrame as unknown as { caption_color?: string | null })
                .caption_color
            }
          />
        ) : null}
        {aspect === "9:16" ? (
          <div
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              right: 0,
              height: STORIES_SAFE_TOP_PX,
              pointerEvents: "none",
            }}
            aria-hidden
          />
        ) : null}
      </AbsoluteFill>
    );
  }

  /* ───────────────────────────────────────────────────────────────────────
     Live-action branch — Veo clip or still image with caption + effects.
     ─────────────────────────────────────────────────────────────────────── */
  const liveFrame: LiveActionFrameType = frame;

  /* Ken Burns — single linear interpolate from 1.0 → 1.06 across the slide. */
  const kenBurnsScale = interpolate(
    localFrame,
    [0, durationInFrames],
    [1.0, KEN_BURNS_END_SCALE],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  /* Background medium selection.
     Veo clips bring real motion, so we drop Ken Burns on the video branch.
     The still-image branch keeps the existing Ken Burns zoom. The empty branch
     is defensive — the backend validator guarantees at least one source. */
  const hasClip =
    typeof liveFrame.clip_url === "string" && liveFrame.clip_url.length > 0;
  const hasImage =
    typeof liveFrame.image_url === "string" && liveFrame.image_url.length > 0;

  return (
    <AbsoluteFill style={{ backgroundColor, opacity: slideOpacity }}>
      {/* Background medium — Veo clip preferred, still image as fallback. */}
      {hasClip ? (
        <AbsoluteFill>
          {/*
            OffthreadVideo (not Video) — Remotion extracts frames via ffmpeg
            instead of leaning on Chromium's HTML5 decoder. The browser
            decoder chokes on Veo's mp4s with PIPELINE_ERROR_DECODE on
            certain frames mid-stream and aborts the entire render. ffmpeg
            decodes those same files cleanly.
            onError is a final safety net — if even ffmpeg trips on a
            mangled chunk, we swallow the error so the render continues
            (the frame goes black for a moment, but we don't lose the
            other 5 shots that worked).
          */}
          <OffthreadVideo
            src={liveFrame.clip_url as string}
            muted
            onError={(e) => {
              console.warn("OffthreadVideo decode error:", e);
            }}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              display: "block",
            }}
          />
        </AbsoluteFill>
      ) : hasImage ? (
        <AbsoluteFill
          style={{
            transform: `scale(${kenBurnsScale})`,
            // Anchor the zoom at the centre so cropping stays symmetrical.
            transformOrigin: "center center",
          }}
        >
          <Img
            src={liveFrame.image_url as string}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              display: "block",
            }}
          />
        </AbsoluteFill>
      ) : null}

      {/* Caption layer — shared with design_sequence. */}
      <CaptionLayer
        text={liveFrame.caption}
        brand={brand}
        aspect={aspect}
        focalZone={liveFrame.focal_zone ?? "mc"}
        localFrame={localFrame}
        width={width}
        height={height}
        withScrim
        captionColorOverride={liveFrame.caption_color}
      />

      {/* Motion-graphics effects layer — composited ON TOP of the caption.
          Each effect runs inside its own Sequence (so its local timeline
          starts at 0 regardless of where it sits within the shot). The
          planner emits 0-3 effects per shot. */}
      {(liveFrame.effects ?? []).map((effect) => (
        <EffectRenderer
          key={effect.id}
          effect={effect}
          brand={brand}
          shotDurationInFrames={durationInFrames}
        />
      ))}

      {/* 9:16 only — render an invisible top safe-zone marker. We don't draw
          anything in it, but the comment documents why callers must keep the
          caption out of the top 250px on Stories. */}
      {aspect === "9:16" ? (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: STORIES_SAFE_TOP_PX,
            // Transparent — purely a layout-debugging anchor.
            pointerEvents: "none",
          }}
          aria-hidden
        />
      ) : null}
    </AbsoluteFill>
  );
};

/* ────────────────────────────────────────────────────────────────────────── */
/* MarketingVideo — top-level composition                                      */
/* ────────────────────────────────────────────────────────────────────────── */

/* ────────────────────────────────────────────────────────────────────────── */
/* TitleSequence — typographic opener (no Veo clip)                           */
/* ────────────────────────────────────────────────────────────────────────── */

type TitleSequenceProps = {
  titleCard: TitleCard;
  brand: Brand;
  durationInFrames: number;
  aspect: MarketingVideoProps["aspect"];
};

const TitleSequence: React.FC<TitleSequenceProps> = ({
  titleCard,
  brand,
  durationInFrames,
  aspect,
}) => {
  const localFrame = useCurrentFrame();
  const { width, height } = useVideoConfig();

  // Scale + fade in over the first 14 frames; out over the last 10.
  const inFrames = 14;
  const outFrames = 10;
  const fadeIn = interpolate(localFrame, [0, inFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(
    localFrame,
    [durationInFrames - outFrames, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const opacity = Math.min(fadeIn, fadeOut);

  const scale = interpolate(localFrame, [0, inFrames], [0.94, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const headlineFont =
    brand.headline_font ?? "system-ui, -apple-system, sans-serif";
  const bg = colorForRole(brand, "background", "#000000");
  const fg = colorForRole(brand, "text", "#ffffff");
  const accent = colorForRole(brand, "accent", fg);

  // Title type is a touch larger than caption type to feel like a billboard.
  const fontSize = Math.round(captionFontSize(width, height) * 1.45);

  return (
    <AbsoluteFill style={{ backgroundColor: bg, opacity }}>
      {/* Subtle accent dot above the type — brand-colored breath mark. */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: `0 ${Math.round(width * 0.08)}px`,
          textAlign: "center",
          gap: Math.round(fontSize * 0.45),
          transform: `scale(${scale})`,
          transformOrigin: "center center",
        }}
      >
        <div
          style={{
            width: Math.round(fontSize * 0.18),
            height: Math.round(fontSize * 0.18),
            borderRadius: "999px",
            backgroundColor: accent,
            opacity: 0.9,
          }}
        />
        <span
          style={{
            fontFamily: headlineFont,
            fontWeight: brand.caption_weight ?? 800,
            fontSize,
            lineHeight: 1.05,
            color: fg,
            letterSpacing: `${brand.caption_tracking_em ?? -0.01}em`,
            textTransform: brand.caption_all_caps ? "uppercase" : "none",
            maxWidth: "90%",
            textShadow: "0 2px 6px rgba(0,0,0,0.25)",
          }}
        >
          {titleCard.text}
        </span>
      </div>
      {aspect === "9:16" ? (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: STORIES_SAFE_TOP_PX,
            pointerEvents: "none",
          }}
          aria-hidden
        />
      ) : null}
    </AbsoluteFill>
  );
};

/* ────────────────────────────────────────────────────────────────────────── */
/* EndCardSequence — typographic closer with CTA letter reveal                */
/* ────────────────────────────────────────────────────────────────────────── */

type EndCardSequenceProps = {
  endCard: EndCard;
  brand: Brand;
  durationInFrames: number;
  aspect: MarketingVideoProps["aspect"];
};

const EndCardSequence: React.FC<EndCardSequenceProps> = ({
  endCard,
  brand,
  durationInFrames,
  aspect,
}) => {
  const localFrame = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const headlineInFrames = 14;
  const ctaStart = headlineInFrames + 4; // CTA reveals after the headline lands
  const outFrames = 12;

  const headlineFadeIn = interpolate(
    localFrame,
    [0, headlineInFrames],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const headlineTranslate = interpolate(
    localFrame,
    [0, headlineInFrames],
    [24, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const fadeOut = interpolate(
    localFrame,
    [durationInFrames - outFrames, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  const headlineFont =
    brand.headline_font ?? "system-ui, -apple-system, sans-serif";
  const bg = colorForRole(brand, "background", "#000000");
  const fg = colorForRole(brand, "text", "#ffffff");
  const accent = colorForRole(brand, "accent", fg);

  const headlineSize = Math.round(captionFontSize(width, height) * 1.25);
  const ctaSize = Math.round(captionFontSize(width, height) * 0.75);

  // Letter-by-letter reveal for the CTA. Per-char delay scales so even long
  // CTAs land before the fade-out.
  const ctaChars = Array.from(endCard.cta);
  const ctaWindow = Math.max(1, durationInFrames - ctaStart - outFrames);
  const ctaPerChar = Math.max(
    1,
    Math.floor(ctaWindow / Math.max(1, ctaChars.length)),
  );

  return (
    <AbsoluteFill
      style={{
        backgroundColor: bg,
        opacity: fadeOut,
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: `0 ${Math.round(width * 0.08)}px`,
          textAlign: "center",
          gap: Math.round(headlineSize * 0.5),
        }}
      >
        <span
          style={{
            fontFamily: headlineFont,
            fontWeight: brand.caption_weight ?? 800,
            fontSize: headlineSize,
            lineHeight: 1.08,
            color: fg,
            letterSpacing: `${brand.caption_tracking_em ?? -0.01}em`,
            textTransform: brand.caption_all_caps ? "uppercase" : "none",
            maxWidth: "92%",
            opacity: headlineFadeIn,
            transform: `translateY(${headlineTranslate}px)`,
            textShadow: "0 2px 6px rgba(0,0,0,0.25)",
          }}
        >
          {endCard.headline}
        </span>
        {endCard.cta ? (
          <div
            style={{
              fontFamily: headlineFont,
              fontWeight: 700,
              fontSize: ctaSize,
              lineHeight: 1.2,
              color: accent,
              letterSpacing: "0.04em",
              textTransform: "uppercase",
              display: "inline-flex",
              flexWrap: "wrap",
              justifyContent: "center",
              gap: 0,
            }}
          >
            {ctaChars.map((ch, idx) => {
              const charStart = ctaStart + idx * ctaPerChar;
              const charOpacity = interpolate(
                localFrame,
                [charStart, charStart + ctaPerChar],
                [0, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
              );
              return (
                <span
                  key={`${idx}-${ch}`}
                  style={{
                    opacity: charOpacity,
                    display: ch === " " ? "inline-block" : "inline",
                    width: ch === " " ? "0.32em" : undefined,
                  }}
                >
                  {ch === " " ? " " : ch}
                </span>
              );
            })}
          </div>
        ) : null}
      </div>
      {aspect === "9:16" ? (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: STORIES_SAFE_TOP_PX,
            pointerEvents: "none",
          }}
          aria-hidden
        />
      ) : null}
    </AbsoluteFill>
  );
};

/* ────────────────────────────────────────────────────────────────────────── */
/* BridgeSequence — Veo motion-bridge mp4 inserted between two scenes         */
/* ────────────────────────────────────────────────────────────────────────── */

type BridgeSequenceProps = {
  clipUrl: string;
  brand: Brand;
};

/**
 * Pure-motion bridge segment. No caption overlay, no Ken Burns, no effects —
 * just the mp4 playing edge-to-edge. The bridge clip itself handles ALL
 * visual continuity from scene N's last frame to scene N+1's first frame.
 *
 * Uses OffthreadVideo (not Video) for the same decode-stability reason we
 * switched on the live-action branch — Chromium's HTML5 decoder chokes on
 * Veo mp4s mid-stream; ffmpeg handles them cleanly.
 */
const BridgeSequence: React.FC<BridgeSequenceProps> = ({ clipUrl, brand }) => {
  const backgroundColor = colorForRole(brand, "background", "#000000");
  return (
    <AbsoluteFill style={{ backgroundColor }}>
      <OffthreadVideo
        src={clipUrl}
        muted
        onError={(e) => {
          // Swallow decode errors so a bad bridge doesn't abort the whole
          // render — the rest of the scenes still produce a valid mp4.
          console.warn("BridgeSequence OffthreadVideo decode error:", e);
        }}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          display: "block",
        }}
      />
    </AbsoluteFill>
  );
};

/* ────────────────────────────────────────────────────────────────────────── */
/* MarketingVideo — top-level composition                                      */
/* ────────────────────────────────────────────────────────────────────────── */

// Default duration for a Veo bridge clip when we can't probe metadata.
// Backend renders bridges at 4s @ 30fps = 120 frames.
const DEFAULT_BRIDGE_FRAMES = 120;

/**
 * Per-segment item we feed into the Series. Either a real storyboard frame
 * (with neighbor-aware fade-in/fade-out frame counts), or a Veo bridge clip
 * inserted between two adjacent scenes.
 */
type RenderItem =
  | {
      kind: "frame";
      frame: Frame;
      duration: number;
      fadeInFrames: number;
      fadeOutFrames: number;
      keySuffix: string;
    }
  | {
      kind: "bridge";
      clipUrl: string;
      duration: number;
      pairIndex: number;
    };

export const MarketingVideo: React.FC<MarketingVideoProps> = ({
  aspect,
  brand,
  brand_name,
  frames,
  title_card,
  end_card,
  transitions,
}) => {
  // Validate the transitions prop. Backend may emit a different shape
  // than expected — defensively fall back to ignoring transitions in that
  // case (so the legacy uniform-12-frame crossfade still applies).
  const validTransitions: Transition[] | null = useMemo(() => {
    if (!Array.isArray(transitions)) return null;
    if (frames.length === 0) return null;
    if (transitions.length !== frames.length - 1) {
      console.warn(
        `MarketingVideo: transitions.length (${transitions.length}) !== ` +
          `frames.length - 1 (${frames.length - 1}); ignoring transitions ` +
          "and falling back to legacy uniform crossfade.",
      );
      return null;
    }
    return transitions;
  }, [transitions, frames.length]);

  // Build the interleaved render list. Per-frame fade-in/fade-out frame
  // counts are decided by the transition style on either side:
  //   - first frame's fadeIn  = 0 (no fade against black at the open)
  //   - last  frame's fadeOut = 0 (no fade against black at the close)
  //   - between two scenes, both sides use:
  //       crossfade  → FADE_FRAMES on both sides
  //       match_cut  → 0 on both sides (hard cut)
  //       veo_bridge → 0 on both sides (bridge clip handles continuity)
  // When transitions is missing/malformed we fall back to the legacy
  // uniform FADE_FRAMES on every internal edge.
  const renderItems = useMemo<RenderItem[]>(() => {
    if (frames.length === 0) return [];
    const items: RenderItem[] = [];

    for (let i = 0; i < frames.length; i++) {
      const frame = frames[i];
      const duration = frameDurationToFrames(frame.duration_ms);
      const isFirst = i === 0;
      const isLast = i === frames.length - 1;

      // Decide fade behaviour for this frame's incoming and outgoing edges.
      let fadeInFrames: number;
      let fadeOutFrames: number;

      if (validTransitions) {
        // Transition BEFORE this frame is at index i - 1.
        const incoming = isFirst ? null : validTransitions[i - 1];
        const outgoing = isLast ? null : validTransitions[i];
        fadeInFrames =
          incoming === null
            ? 0
            : incoming.style === "crossfade"
              ? FADE_FRAMES
              : 0; // match_cut OR veo_bridge → hard edge
        fadeOutFrames =
          outgoing === null
            ? 0
            : outgoing.style === "crossfade"
              ? FADE_FRAMES
              : 0;
      } else {
        // Legacy behaviour — every internal edge is a 12-frame crossfade.
        fadeInFrames = isFirst ? 0 : FADE_FRAMES;
        fadeOutFrames = isLast ? 0 : FADE_FRAMES;
      }

      const keySuffix = isDesignSequenceFrame(frame)
        ? `${frame.template}-${frame.caption ?? ""}`
        : `${frame.clip_url ?? frame.image_url ?? ""}`;

      items.push({
        kind: "frame",
        frame,
        duration,
        fadeInFrames,
        fadeOutFrames,
        keySuffix,
      });

      // Insert a bridge AFTER this frame if the next pair is veo_bridge
      // and we actually have a clip_url to play.
      if (validTransitions && !isLast) {
        const t = validTransitions[i];
        if (
          t.style === "veo_bridge" &&
          typeof t.clip_url === "string" &&
          t.clip_url.length > 0
        ) {
          items.push({
            kind: "bridge",
            clipUrl: t.clip_url,
            duration: DEFAULT_BRIDGE_FRAMES,
            pairIndex: i,
          });
        }
      }
    }

    return items;
  }, [frames, validTransitions]);

  const lastBackgroundColor = colorForRole(brand, "background", "#000000");

  const titleDuration = title_card
    ? frameDurationToFrames(title_card.duration_ms)
    : 0;
  const endDuration = end_card
    ? frameDurationToFrames(end_card.duration_ms)
    : 0;

  // Empty-storyboard guard: render a solid background so the renderer doesn't
  // emit a zero-content frame. Root.tsx clamps duration to 1s in this case.
  if (renderItems.length === 0 && !title_card && !end_card) {
    return <AbsoluteFill style={{ backgroundColor: lastBackgroundColor }} />;
  }

  return (
    <AbsoluteFill style={{ backgroundColor: lastBackgroundColor }}>
      <Series>
        {title_card && titleDuration > 0 ? (
          <Series.Sequence durationInFrames={titleDuration}>
            <TitleSequence
              titleCard={title_card}
              brand={brand}
              durationInFrames={titleDuration}
              aspect={aspect}
            />
          </Series.Sequence>
        ) : null}
        {renderItems.map((item, idx) => {
          if (item.kind === "bridge") {
            return (
              <Series.Sequence
                key={`bridge-${item.pairIndex}-${item.clipUrl}`}
                durationInFrames={item.duration}
              >
                <BridgeSequence clipUrl={item.clipUrl} brand={brand} />
              </Series.Sequence>
            );
          }
          return (
            <Series.Sequence
              key={`frame-${idx}-${item.keySuffix}`}
              durationInFrames={item.duration}
            >
              <StoryboardFrame
                frame={item.frame}
                brand={brand}
                brandName={brand_name}
                durationInFrames={item.duration}
                aspect={aspect}
                fadeInFrames={item.fadeInFrames}
                fadeOutFrames={item.fadeOutFrames}
              />
            </Series.Sequence>
          );
        })}
        {end_card && endDuration > 0 ? (
          <Series.Sequence durationInFrames={endDuration}>
            <EndCardSequence
              endCard={end_card}
              brand={brand}
              durationInFrames={endDuration}
              aspect={aspect}
            />
          </Series.Sequence>
        ) : null}
      </Series>
    </AbsoluteFill>
  );
};
