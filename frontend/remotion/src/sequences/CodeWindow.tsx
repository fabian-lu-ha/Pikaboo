import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { CodeWindowParams } from "../types";
import {
  DEFAULT_BODY_FONT,
  DEFAULT_MONO_FONT,
  type DesignSequenceProps,
  hexToRgba,
  palette,
  resolveRole,
  scaledSize,
} from "./shared";

/**
 * CodeWindow — Vercel/GitHub demo beat.
 *
 * - macOS-style window chrome (3 traffic-light dots + filename pill).
 * - Code lines type in line-by-line at ~7 chars/frame.
 * - Cursor blinks at the current line end.
 * - Subtle terminal scanline overlay for tactile texture.
 * - Window enters by lifting up + fading in (cubic-out), exits by sliding
 *   down + fading out so it doesn't hang.
 *
 * Language tint is picked from brand palette per-language so the syntax
 * accent feels brand-consistent without forcing a real syntax highlighter.
 */

/** Pick a syntax-tint color per language from the brand palette. */
const tintForLanguage = (
  language: string | undefined,
  brand: import("../types").Brand,
): string => {
  // We use palette index modulo length to deterministically pick a hue per
  // language. Falls back to a sensible accent.
  const fallback = resolveRole(brand, "accent", "#7dd3fc");
  if (!language) return fallback;
  const lang = language.toLowerCase();
  // Per-language palette pick — stable, brand-aware, no real syntax parse.
  const idx =
    {
      ts: 2,
      tsx: 2,
      typescript: 2,
      js: 3,
      jsx: 3,
      javascript: 3,
      python: 1,
      py: 1,
      rust: 0,
      rs: 0,
      go: 2,
      shell: 1,
      bash: 1,
      sh: 1,
      json: 3,
    }[lang] ?? 2;
  return palette(brand, idx, fallback);
};

const CodeWindow: React.FC<DesignSequenceProps<CodeWindowParams>> = ({
  params,
  brand,
  durationInFrames,
}) => {
  const f = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();

  const lines = Array.isArray(params.lines) ? params.lines : [];
  const language = params.language;
  const theme = params.theme ?? "dark";

  /* Theme — windowed editor feel. Dark by default (premium Vercel/GitHub). */
  const windowBg = theme === "dark" ? "#0d1117" : "#fafafa";
  const codeBg = theme === "dark" ? "#0d1117" : "#fafafa";
  const fg = theme === "dark" ? "#e6edf3" : "#24292f";
  const subtleFg = theme === "dark" ? "rgba(230,237,243,0.55)" : "rgba(36,41,47,0.5)";
  const chromeBg = theme === "dark" ? "#161b22" : "#ebebeb";
  const tint = tintForLanguage(language, brand);

  /* Window enter/exit — lift in, settle, drop out. */
  const enterFrames = 14;
  const exitStart = durationInFrames - 12;
  const enterTranslate = interpolate(f, [0, enterFrames], [40, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const exitTranslate = interpolate(
    f,
    [exitStart, durationInFrames],
    [0, 30],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.in(Easing.cubic),
    },
  );
  const fadeIn = interpolate(f, [0, enterFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
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

  /* Type-on. After enterFrames, start typing line-by-line at CHARS_PER_FRAME. */
  const CHARS_PER_FRAME = 7;
  const typingStart = enterFrames + 4;
  const typingF = Math.max(0, f - typingStart);

  // Pre-compute cumulative chars per line so we can find the cursor.
  const cumulative: number[] = [];
  let acc = 0;
  for (const line of lines) {
    acc += line.length + 1; // +1 for newline transition cost
    cumulative.push(acc);
  }
  const totalChars = acc;
  const charsTyped = Math.min(totalChars, typingF * CHARS_PER_FRAME);

  /* Determine which line the cursor is on (for blink positioning). */
  let cursorLineIdx = 0;
  for (let i = 0; i < cumulative.length; i++) {
    if (charsTyped < cumulative[i]) {
      cursorLineIdx = i;
      break;
    }
    cursorLineIdx = i;
  }
  const isDoneTyping = charsTyped >= totalChars;

  /* Cursor blink — 2 Hz, 50% duty. */
  const cursorOn = Math.floor((f / fps) * 4) % 2 === 0;

  /* Window sizing — fits inside the canvas with breathing margins. */
  const windowW = Math.round(width * 0.86);
  const windowH = Math.round(height * 0.7);
  const windowX = Math.round((width - windowW) / 2);
  const windowY = Math.round((height - windowH) / 2);

  const monoFont = DEFAULT_MONO_FONT;
  const codeSize = scaledSize(width, height, 32);
  const lineHeight = Math.round(codeSize * 1.55);
  const chromeSize = scaledSize(width, height, 18);

  /* Build typed-so-far per line, with the cursor sitting on the active line. */
  const renderedLines = lines.map((line, idx) => {
    const lineStart = idx === 0 ? 0 : cumulative[idx - 1];
    const cap = Math.max(0, Math.min(line.length, charsTyped - lineStart));
    const visible = line.slice(0, cap);
    const showCursor = idx === cursorLineIdx && (!isDoneTyping || cursorOn);
    return (
      <div
        key={idx}
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: Math.round(codeSize * 0.6),
          minHeight: lineHeight,
          lineHeight: `${lineHeight}px`,
        }}
      >
        <span
          style={{
            fontFamily: monoFont,
            fontSize: Math.round(codeSize * 0.78),
            color: subtleFg,
            userSelect: "none",
            minWidth: Math.round(codeSize * 1.6),
            textAlign: "right",
          }}
        >
          {idx + 1}
        </span>
        <span
          style={{
            fontFamily: monoFont,
            fontSize: codeSize,
            color: fg,
            whiteSpace: "pre",
          }}
        >
          {visible}
          {showCursor ? (
            <span
              style={{
                display: "inline-block",
                width: Math.round(codeSize * 0.55),
                height: Math.round(codeSize * 1.1),
                marginLeft: 2,
                verticalAlign: "text-bottom",
                backgroundColor: tint,
                opacity: cursorOn || !isDoneTyping ? 1 : 0,
                boxShadow: `0 0 12px ${hexToRgba(tint, 0.5)}`,
              }}
            />
          ) : null}
        </span>
      </div>
    );
  });

  /* Background — soft brand-tinted gradient so the window pops. */
  const bg0 = palette(brand, 0, "#0a0a0a");
  const bg1 = palette(brand, 1, "#1a1a1a");

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(135deg, ${bg0} 0%, ${bg1} 100%)`,
        opacity,
      }}
    >
      {/* Subtle scanline overlay across the whole frame. */}
      <AbsoluteFill
        style={{
          opacity: 0.06,
          backgroundImage:
            "repeating-linear-gradient(0deg, rgba(255,255,255,0.4) 0px, rgba(255,255,255,0.4) 1px, transparent 1px, transparent 3px)",
          pointerEvents: "none",
        }}
      />

      {/* Window. */}
      <div
        style={{
          position: "absolute",
          left: windowX,
          top: windowY,
          width: windowW,
          height: windowH,
          backgroundColor: windowBg,
          borderRadius: 18,
          boxShadow:
            "0 30px 80px rgba(0,0,0,0.55), 0 12px 30px rgba(0,0,0,0.35)",
          overflow: "hidden",
          transform: `translateY(${enterTranslate + exitTranslate}px)`,
          backdropFilter: "blur(20px)",
          border: `1px solid ${hexToRgba(tint, 0.18)}`,
        }}
      >
        {/* Chrome. */}
        <div
          style={{
            height: Math.round(chromeSize * 2.4),
            backgroundColor: chromeBg,
            display: "flex",
            alignItems: "center",
            padding: `0 ${Math.round(chromeSize * 1.2)}px`,
            gap: Math.round(chromeSize * 0.6),
            borderBottom: `1px solid ${hexToRgba(fg, 0.08)}`,
          }}
        >
          {/* Traffic lights. */}
          <div style={{ display: "flex", gap: Math.round(chromeSize * 0.55) }}>
            <span
              style={{
                width: chromeSize,
                height: chromeSize,
                borderRadius: "50%",
                backgroundColor: "#ff5f57",
              }}
            />
            <span
              style={{
                width: chromeSize,
                height: chromeSize,
                borderRadius: "50%",
                backgroundColor: "#febc2e",
              }}
            />
            <span
              style={{
                width: chromeSize,
                height: chromeSize,
                borderRadius: "50%",
                backgroundColor: "#28c840",
              }}
            />
          </div>
          {/* Filename pill — language label. */}
          <div
            style={{
              flex: 1,
              display: "flex",
              justifyContent: "center",
            }}
          >
            <div
              style={{
                fontFamily: brand.body_font ?? DEFAULT_BODY_FONT,
                fontSize: Math.round(chromeSize * 0.95),
                fontWeight: 500,
                color: subtleFg,
                padding: `${Math.round(chromeSize * 0.25)}px ${Math.round(chromeSize * 0.9)}px`,
                backgroundColor: hexToRgba(fg, 0.05),
                borderRadius: 6,
                letterSpacing: "0.01em",
              }}
            >
              {language ? `index.${language}` : "preview"}
            </div>
          </div>
          {/* Tint pill — language accent dot. */}
          <div
            style={{
              width: Math.round(chromeSize * 1.2),
              display: "flex",
              justifyContent: "flex-end",
            }}
          >
            <span
              style={{
                width: Math.round(chromeSize * 0.6),
                height: Math.round(chromeSize * 0.6),
                borderRadius: "50%",
                backgroundColor: tint,
                boxShadow: `0 0 8px ${hexToRgba(tint, 0.6)}`,
              }}
            />
          </div>
        </div>

        {/* Code area. */}
        <div
          style={{
            backgroundColor: codeBg,
            padding: `${Math.round(codeSize * 1.2)}px ${Math.round(codeSize * 1.4)}px`,
            height: "100%",
            overflow: "hidden",
          }}
        >
          {renderedLines}
        </div>

        {/* Top accent stripe — language tint. */}
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 0,
            height: 2,
            background: `linear-gradient(90deg, transparent 0%, ${tint} 50%, transparent 100%)`,
            opacity: 0.7,
          }}
        />
      </div>
    </AbsoluteFill>
  );
};

export default CodeWindow;
