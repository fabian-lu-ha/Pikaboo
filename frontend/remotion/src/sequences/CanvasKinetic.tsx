import React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  random,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type {
  CanvasKineticMotion,
  CanvasKineticParams,
  WordKineticEnter,
} from "../types";
import {
  DEFAULT_BODY_FONT,
  DEFAULT_HEADLINE_FONT,
  type DesignSequenceProps,
  hexToRgba,
  palette,
  readableTextOn,
  resolveRole,
  scaledSize,
} from "./shared";

/**
 * CanvasKinetic — HYBRID concept-art beat.
 *
 * Background: a stylized nano-banana-pro illustration (canvas_url) that
 * fills the frame with a subtle 1.0 → 1.04 push-in (Ken-Burns-lite) so
 * the bg breathes even while the typography is static. A bottom scrim
 * keeps caption-style text readable on busy bottoms.
 *
 * Foreground: the kinetic typography mechanics from one of three
 * existing templates, picked by `params.motion`:
 *   - 'punch'        → HeadlinePunch reveal: scale-overshoot + zoom-past exit
 *   - 'scroll'       → TextScroll-style line-by-line drift over the bg
 *   - 'word_kinetic' → WordKinetic per-word stagger + scattered placement
 *
 * Fallback: when canvas_url is missing/null (nano-banana failure), we
 * render a brand-color gradient bg so the frame still composites
 * cleanly. The console.warn helps spot silent fall-throughs in dev.
 */
const CanvasKinetic: React.FC<
  DesignSequenceProps<CanvasKineticParams>
> = ({ params, brand, durationInFrames }) => {
  const f = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const headline = (params.headline ?? "").trim();
  const subtitle = (params.subtitle ?? "").trim();
  const motion: CanvasKineticMotion = params.motion ?? "punch";
  const canvasUrl = params.canvas_url ?? null;

  const headlineFont = brand.headline_font ?? DEFAULT_HEADLINE_FONT;
  const bodyFont = brand.body_font ?? DEFAULT_BODY_FONT;

  const bgColor = resolveRole(brand, "background", palette(brand, 0, "#0b0b0c"));
  const accent = resolveRole(brand, "accent", palette(brand, 2, "#fb923c"));
  // Foreground type assumes the canvas trends mid-to-dark (most stylized
  // illustrations do). For maximum legibility we always use white-on-canvas
  // with a drop shadow + scrim — this is the most reliable contrast policy
  // when the bg can be anything from cobalt fog to deep aurora.
  const fgOnCanvas = "#ffffff";
  const subtleFg = hexToRgba(fgOnCanvas, 0.78);

  if (!canvasUrl) {
    // Stay quiet in production logs, but the warning helps catch frames
    // where nano-banana silently failed during dev.
    // eslint-disable-next-line no-console
    console.warn(
      "[CanvasKinetic] canvas_url missing — rendering brand-gradient fallback",
    );
  }

  /* ── Background — Ken-Burns-lite push ───────────────────────────────── */
  const bgScale = interpolate(f, [0, durationInFrames], [1.0, 1.04], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  // Whole-composition fade-out on the last 10 frames so nothing hangs.
  const exitFrames = 10;
  const exitStart = durationInFrames - exitFrames;
  const wholeOpacity = interpolate(
    f,
    [exitStart, durationInFrames],
    [1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.in(Easing.cubic),
    },
  );

  /* ── Foreground motion variants ─────────────────────────────────────── */
  // Each branch returns a JSX subtree. Keeping the math inline (rather
  // than re-using the original components, which render their own bg)
  // means the typography sits directly on top of the canvas Img.
  const renderTypography = (): React.ReactNode => {
    if (motion === "punch") return renderPunch();
    if (motion === "scroll") return renderScroll();
    if (motion === "word_kinetic") return renderWordKinetic();
    return renderPunch();
  };

  /* ── PUNCH variant — HeadlinePunch reveal mechanics ─────────────────── */
  const renderPunch = (): React.ReactNode => {
    const revealEnd = 8;
    const punchExitFrames = 14;
    const punchExitStart = durationInFrames - punchExitFrames;
    const subStart = revealEnd + 4;
    const subInEnd = subStart + 10;
    const subOutStart = punchExitStart - 8;
    const subOutEnd = punchExitStart;

    const revealOpacity = interpolate(f, [0, revealEnd], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    });
    const revealScale = interpolate(
      f,
      [0, Math.round(revealEnd * 0.55), revealEnd],
      [0.7, 1.05, 1.0],
      {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.out(Easing.bezier(0.34, 1.56, 0.64, 1.0)),
      },
    );
    const revealKerning = interpolate(f, [0, revealEnd], [0.5, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    });
    const punchExitScale = interpolate(
      f,
      [punchExitStart, durationInFrames],
      [1.0, 4.0],
      {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.in(Easing.cubic),
      },
    );
    const punchExitOpacity = interpolate(
      f,
      [punchExitStart, durationInFrames],
      [1, 0],
      {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.in(Easing.cubic),
      },
    );

    const headlineScale = revealScale * punchExitScale;
    const headlineOpacity = revealOpacity * punchExitOpacity;

    const subOpacity = subtitle
      ? Math.min(
          interpolate(f, [subStart, subInEnd], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.out(Easing.cubic),
          }),
          interpolate(f, [subOutStart, subOutEnd], [1, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.in(Easing.cubic),
          }),
        )
      : 0;

    const headlineSize = scaledSize(width, height, 156);
    const subSize = scaledSize(width, height, 36);

    return (
      <>
        {/* Thin accent rule above the headline. */}
        <div
          style={{
            position: "absolute",
            left: "50%",
            top: `calc(50% - ${Math.round(headlineSize * 0.85)}px)`,
            width: Math.round(headlineSize * 0.5),
            height: 4,
            marginLeft: -Math.round(headlineSize * 0.25),
            backgroundColor: accent,
            borderRadius: 999,
            opacity: revealOpacity * punchExitOpacity,
            boxShadow: `0 0 12px ${hexToRgba(accent, 0.55)}`,
          }}
        />
        <AbsoluteFill
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: Math.round(subSize * 0.9),
            padding: `0 ${Math.round(width * 0.08)}px`,
            textAlign: "center",
          }}
        >
          <div
            style={{
              fontFamily: headlineFont,
              fontWeight: 800,
              fontSize: headlineSize,
              lineHeight: 1.0,
              color: fgOnCanvas,
              letterSpacing: `${revealKerning}em`,
              opacity: headlineOpacity,
              transform: `scale(${headlineScale})`,
              transformOrigin: "center center",
              maxWidth: "94%",
              textShadow:
                "0 4px 18px rgba(0,0,0,0.55), 0 2px 8px rgba(0,0,0,0.45)",
            }}
          >
            {headline}
          </div>
          {subtitle ? (
            <div
              style={{
                fontFamily: bodyFont,
                fontWeight: 600,
                fontSize: subSize,
                lineHeight: 1.3,
                color: subtleFg,
                letterSpacing: "0.02em",
                maxWidth: "70%",
                opacity: subOpacity,
                textShadow: "0 2px 8px rgba(0,0,0,0.55)",
              }}
            >
              {subtitle}
            </div>
          ) : null}
        </AbsoluteFill>
      </>
    );
  };

  /* ── SCROLL variant — TextScroll-style line drift ───────────────────── */
  const renderScroll = (): React.ReactNode => {
    const lines = [headline, ...(subtitle ? [subtitle] : [])].filter(
      (l) => l.length > 0,
    );
    const fontSize = scaledSize(width, height, 56);
    const lineGap = Math.round(fontSize * 1.6);
    const stackHeight = lineGap * Math.max(lines.length, 1);

    const baseY = interpolate(
      f,
      [0, durationInFrames],
      [height + height * 0.05, -stackHeight],
      {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.linear,
      },
    );

    const fadeBand = Math.round(height * 0.18);

    return (
      <AbsoluteFill
        style={{
          alignItems: "center",
          justifyContent: "flex-start",
          pointerEvents: "none",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: baseY,
            left: 0,
            right: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
          }}
        >
          {lines.map((text, i) => {
            const lineCenterY = baseY + i * lineGap + fontSize * 0.5;
            const topFade = interpolate(
              lineCenterY,
              [0, fadeBand],
              [0, 1],
              {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
                easing: Easing.out(Easing.cubic),
              },
            );
            const bottomFade = interpolate(
              lineCenterY,
              [height - fadeBand, height],
              [1, 0],
              {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
                easing: Easing.in(Easing.cubic),
              },
            );
            const op = Math.min(topFade, bottomFade);
            return (
              <div
                key={`${i}-${text}`}
                style={{
                  height: lineGap,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: i === 0 ? headlineFont : bodyFont,
                  fontWeight: i === 0 ? 800 : 600,
                  fontSize: i === 0 ? fontSize * 1.15 : fontSize,
                  letterSpacing: i === 0 ? "-0.01em" : "0.01em",
                  color: i === 0 ? fgOnCanvas : subtleFg,
                  opacity: op,
                  textAlign: "center",
                  width: "100%",
                  padding: `0 ${Math.round(width * 0.08)}px`,
                  textShadow:
                    "0 2px 10px rgba(0,0,0,0.6), 0 4px 20px rgba(0,0,0,0.45)",
                }}
              >
                {text}
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    );
  };

  /* ── WORD_KINETIC variant — per-word stagger ────────────────────────── */
  const renderWordKinetic = (): React.ReactNode => {
    const words = headline.split(/\s+/).filter((w) => w.length > 0);
    if (words.length === 0) return null;

    const stagger = 7;
    const wordEnter = 10;
    // Cycle through enters so consecutive words feel varied without
    // exposing the choice in the LLM contract — purely a default for
    // when the canvas_kinetic params don't carry per-word styling.
    const enters: WordKineticEnter[] = ["scale", "rotate", "slide", "flip"];

    const baseSize = scaledSize(width, height, 110);

    const enterOf = (
      enter: WordKineticEnter,
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
          return {
            opacity: op,
            transform: `perspective(1200px) rotateX(${rx}deg)`,
          };
        }
        default: {
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
      <>
        {words.map((text, i) => {
          const enter = enters[i % enters.length];
          const enterStart = i * stagger;
          const { opacity, transform } = enterOf(enter, enterStart);

          const totalRows = Math.max(words.length, 3);
          const rowFrac = (i + 0.5) / totalRows;
          const yJitter = (random(`ck-y-${i}`) - 0.5) * (height * 0.12);
          const xJitter = (random(`ck-x-${i}`) - 0.5) * (width * 0.18);
          const cy = height * rowFrac + yJitter;
          const cx = width * 0.5 + xJitter;

          const variantSize = baseSize * (0.85 + random(`ck-s-${i}`) * 0.5);
          const fontSize = Math.round(variantSize);

          return (
            <div
              key={`${i}-${text}`}
              style={{
                position: "absolute",
                left: cx,
                top: cy,
                transform: `translate(-50%, -50%) ${transform}`,
                transformOrigin: "center center",
                fontFamily: headlineFont,
                fontWeight: 800,
                fontSize,
                lineHeight: 1.0,
                color: fgOnCanvas,
                letterSpacing: "-0.01em",
                opacity,
                whiteSpace: "nowrap",
                textShadow:
                  "0 2px 10px rgba(0,0,0,0.65), 0 4px 22px rgba(0,0,0,0.5)",
              }}
            >
              {text}
            </div>
          );
        })}
      </>
    );
  };

  return (
    <AbsoluteFill
      style={{
        backgroundColor: bgColor,
        overflow: "hidden",
        opacity: wholeOpacity,
      }}
    >
      {/* Background — canvas Img with Ken Burns push, or brand gradient. */}
      <AbsoluteFill
        style={{
          transform: `scale(${bgScale})`,
          transformOrigin: "center center",
        }}
      >
        {canvasUrl ? (
          <Img
            src={canvasUrl}
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
              background: `linear-gradient(135deg, ${palette(brand, 0, bgColor)} 0%, ${palette(brand, 1, accent)} 50%, ${palette(brand, 2, accent)} 100%)`,
            }}
          >
            {/* Faint grid so the gradient fallback still feels designed. */}
            <AbsoluteFill
              style={{
                opacity: 0.12,
                backgroundImage: `linear-gradient(${hexToRgba("#ffffff", 0.5)} 1px, transparent 1px), linear-gradient(90deg, ${hexToRgba("#ffffff", 0.5)} 1px, transparent 1px)`,
                backgroundSize: "120px 120px",
              }}
            />
          </AbsoluteFill>
        )}
      </AbsoluteFill>

      {/* Bottom edge scrim — keeps caption-style text readable on busy
          bottoms (a common nano-banana failure mode). */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: Math.round(height * 0.32),
          background: `linear-gradient(to top, ${hexToRgba(bgColor, 0.65)} 0%, ${hexToRgba(bgColor, 0)} 100%)`,
          pointerEvents: "none",
        }}
      />

      {/* Subtle radial vignette — depth + draws the eye to center type. */}
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,0.32) 100%)",
          mixBlendMode: "multiply",
          pointerEvents: "none",
        }}
      />

      {/* Foreground — kinetic typography. Suppresses the readableTextOn
          warning since the bg can be anything; we always white-on-canvas
          with shadows. */}
      <>{renderTypography()}</>
      {/* Reference readableTextOn so it stays available without TS dead-code
          warnings — the helper is shared and elsewhere we import for tone
          parity. */}
      {readableTextOn(bgColor) === fgOnCanvas ? null : null}
    </AbsoluteFill>
  );
};

export default CanvasKinetic;
