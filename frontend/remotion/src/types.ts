/**
 * Shared types between Root.tsx and MarketingVideo.tsx.
 *
 * The shape mirrors the JSON storyboard the FastAPI backend emits and passes
 * via Remotion's `--props='{...}'` CLI flag.
 */

export type Aspect = "9:16" | "16:9" | "1:1";

export type PaletteRole = {
  hex: string;
  role: string;
};

/**
 * 9-cell focal-zone grid: t/m/b (top/middle/bottom) × l/c/r (left/center/right).
 * Backend tags each frame with one of these so the compositor can place
 * captions in the opposite quadrant of the canvas.
 */
export type FocalZone =
  | "tl"
  | "tc"
  | "tr"
  | "ml"
  | "mc"
  | "mr"
  | "bl"
  | "bc"
  | "br";

/**
 * Caption-motion presets. The compositor picks one based on brand traits.
 *  - "slide-up": default — caption slides up + fades in.
 *  - "fade": opacity-only fade (no translate).
 *  - "letter-by-letter": staggered character fade-in for typographic brands.
 */
export type CaptionMotion = "slide-up" | "fade" | "letter-by-letter";

/**
 * Motion-graphics overlay rendered ON TOP of a Veo clip (or still keyframe).
 * Effects are visual punctuation — kinetic text accents, lower-thirds,
 * brand stingers, spotlights, geometric lines, data pops. They lift the
 * composition above generic AI-stock-video output.
 */
export type EffectKind =
  | "kinetic_text"
  | "lower_third"
  | "brand_stinger"
  | "spotlight"
  | "kinetic_lines"
  | "data_pop";

export type EffectColor = "accent" | "text" | "background";
export type EffectSize = "sm" | "md" | "lg";
export type EffectLinePattern = "diagonal" | "horizontal" | "underline" | "frame";
export type EffectDataVariant = "number" | "bar" | "dot";

export type EffectParams = {
  text?: string;
  title?: string;
  subtitle?: string;
  value?: string;
  zone?: FocalZone;
  size?: EffectSize;
  color?: EffectColor;
  radius?: EffectSize;
  pattern?: EffectLinePattern;
  variant?: EffectDataVariant;
};

export type Effect = {
  id: string;
  kind: EffectKind;
  params?: EffectParams;
  start_ms?: number | null;
  duration_ms?: number | null;
};

export type Brand = {
  palette: string[];
  palette_roles?: PaletteRole[];
  headline_font?: string;
  body_font?: string;
  // Caption styling/motion derived from the brand profile.
  caption_motion?: CaptionMotion;
  caption_weight?: number;
  caption_tracking_em?: number;
  caption_all_caps?: boolean;
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Frame discriminated union                                                  */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Live-action frame — Veo mp4 clip or still image keyframe with caption.
 * `kind` is optional so legacy storyboards (no `kind` field) continue to
 * route through this branch.
 */
export type LiveActionFrame = {
  kind?: "live_action";
  /**
   * Veo-generated mp4 clip for this segment. Preferred over image_url when set.
   * Real motion comes from Veo, so the compositor skips Ken Burns on this branch.
   */
  clip_url?: string | null;
  /**
   * Still-image fallback. Used when clip_url is missing (dev/test, Veo failure,
   * or pre-Veo storyboards). Ken Burns zoom is applied on this branch.
   */
  image_url?: string | null;
  caption: string;
  duration_ms: number;
  /** Where the primary subject sits in this frame. Defaults to "mc" (center). */
  focal_zone?: FocalZone;
  /**
   * Motion-graphics effects rendered ON TOP of this shot. 0-3 entries; the
   * compositor renders them in order, after the caption layer.
   */
  effects?: Effect[];
  /**
   * Adaptive caption color (#hex). When set the compositor uses this instead
   * of the brand `text` palette role. Backend computes per-frame from the
   * background's effective luminance behind the caption band so captions
   * stay readable on mid-to-dark Veo footage.
   */
  caption_color?: string | null;
};

/**
 * Design-sequence templates — pure-graphic beats interleaved with live-action
 * shots. Each template is its own React component with bespoke motion (no Ken
 * Burns / no Veo). Think Linear/Vercel release reel cuts.
 */
export type DesignSequenceTemplate =
  | "gradient_kinetic"
  | "spec_card"
  | "ui_zoom"
  | "code_window"
  | "logo_reveal"
  | "comparison_split"
  | "text_scroll"
  | "headline_punch"
  | "word_kinetic"
  | "canvas_kinetic";

export type Theme = "light" | "dark";

export type GradientKineticParams = {
  template: "gradient_kinetic";
  headline: string;
  subtitle?: string;
};

export type SpecCardParams = {
  template: "spec_card";
  value: string;
  label?: string;
  unit?: string;
  theme?: Theme;
};

export type UiZoomParams = {
  template: "ui_zoom";
  image_url?: string | null;
  focus_zone?: FocalZone;
  label?: string;
};

export type CodeWindowParams = {
  template: "code_window";
  lines: string[];
  language?: string;
  theme?: Theme;
};

export type LogoRevealParams = {
  template: "logo_reveal";
  wordmark?: string;
  brand_name?: string;
  tagline?: string;
  theme?: Theme;
};

export type ComparisonSide = {
  label: string;
  image_url?: string | null;
};

export type ComparisonSplitParams = {
  template: "comparison_split";
  before: ComparisonSide;
  after: ComparisonSide;
  orientation?: "h" | "v";
};

export type TextScrollTheme = "overlay" | "full";

export type TextScrollParams = {
  template: "text_scroll";
  /** 5-12 short lines that scroll past, end-credits style. */
  lines: string[];
  /** overlay = transparent (sits on Veo); full = solid brand-color bg. */
  theme?: TextScrollTheme;
};

export type HeadlinePunchParams = {
  template: "headline_punch";
  /** 3-5 word punch line. */
  headline: string;
  /** Optional supporting line beneath the headline. */
  subheadline?: string;
};

export type WordKineticEnter = "rotate" | "scale" | "slide" | "flip";
export type WordKineticStyle = "bold" | "italic" | "caps";
export type WordKineticColor = "accent" | "text" | "background";

export type WordKineticWord = {
  text: string;
  style?: WordKineticStyle;
  color?: WordKineticColor;
  enter?: WordKineticEnter;
};

export type WordKineticParams = {
  template: "word_kinetic";
  /** 3-6 words — each animates independently. */
  words: WordKineticWord[];
};

/** Foreground motion variants for canvas_kinetic. Each maps to one of the
 *  pure-CSS kinetic templates whose mechanics are reused on top of the
 *  nano-banana backdrop. */
export type CanvasKineticMotion = "punch" | "scroll" | "word_kinetic";

export type CanvasKineticParams = {
  template: "canvas_kinetic";
  /** Documentation-only — describes the bg the LLM asked for. Not consumed
   *  at render time (the bytes are already at canvas_url). Kept on the
   *  record so the editor surface can show the user the prompt. */
  canvas_prompt?: string;
  /** Storage URL of the nano-banana-pro stylized backdrop. Filled in by
   *  the backend at /render time. When null/missing the foreground falls
   *  back to a brand-color gradient bg. */
  canvas_url?: string | null;
  headline: string;
  subtitle?: string;
  motion: CanvasKineticMotion;
};

export type DesignSequenceParams =
  | GradientKineticParams
  | SpecCardParams
  | UiZoomParams
  | CodeWindowParams
  | LogoRevealParams
  | ComparisonSplitParams
  | TextScrollParams
  | HeadlinePunchParams
  | WordKineticParams
  | CanvasKineticParams;

export type DesignSequenceFrame = {
  kind: "design_sequence";
  template: DesignSequenceTemplate;
  params: DesignSequenceParams;
  /** Optional bottom caption (uses the same overlay system as live-action). */
  caption?: string;
  duration_ms: number;
  /** Where the primary subject sits — only used if a caption is provided. */
  focal_zone?: FocalZone;
};

export type Frame = LiveActionFrame | DesignSequenceFrame;

/**
 * Title-card opener — pure-typography beat played BEFORE the first clip.
 * Brand-voiced hook. Optional; when null/missing the composition starts
 * directly with the first Veo clip.
 */
export type TitleCard = {
  text: string;
  duration_ms: number;
};

/**
 * End-card with CTA — pure-typography beat played AFTER the last clip.
 * Optional; when null/missing the composition ends with the final clip.
 */
export type EndCard = {
  headline: string;
  cta: string;
  duration_ms: number;
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Inter-scene transitions                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Per-pair transition decision emitted by the backend's `plan_transitions()`.
 * One entry per adjacent scene pair (length === frames.length - 1):
 *  - `veo_bridge`: insert a 4s motion clip (`clip_url`) between the two
 *    scenes; the bridge handles all visual continuity so adjacent fades
 *    are suppressed.
 *  - `match_cut`: hard cut, zero crossfade either side.
 *  - `crossfade`: keep the existing 12-frame opacity blend on the pair.
 */
export type TransitionStyle = "veo_bridge" | "match_cut" | "crossfade";

export type Transition = {
  from_id: string;
  to_id: string;
  style: TransitionStyle;
  reason?: string;
  motion_hint?: string | null;
  /** Storage URL to the 4s mp4 — set ONLY when style === "veo_bridge". */
  clip_url?: string | null;
};

export type MarketingVideoProps = {
  aspect: Aspect;
  brand: Brand;
  brand_name?: string;
  frames: Frame[];
  title_card?: TitleCard | null;
  end_card?: EndCard | null;
  /**
   * Optional per-pair transition decisions. When present and well-formed
   * (length === frames.length - 1), the compositor interleaves veo_bridge
   * clips between scenes and applies per-pair crossfade/match_cut/bridge
   * fade behaviour. When absent or malformed, the compositor falls back
   * to the legacy uniform 12-frame crossfade between every pair.
   */
  transitions?: Transition[];
};

export type Dimensions = {
  width: number;
  height: number;
};

/**
 * Maps the storyboard's aspect string to pixel dimensions. We use a fixed
 * 1080-on-the-short-axis policy so renders look identical regardless of where
 * the storyboard ultimately ships (Stories, YouTube, IG square).
 */
export const dimensionsForAspect = (aspect: Aspect): Dimensions => {
  switch (aspect) {
    case "9:16":
      return { width: 1080, height: 1920 };
    case "16:9":
      return { width: 1920, height: 1080 };
    case "1:1":
      return { width: 1080, height: 1080 };
  }
};

/**
 * Default frame duration in milliseconds when a storyboard frame omits it.
 */
export const DEFAULT_FRAME_DURATION_MS = 2500;

export const FPS = 30;

/* ────────────────────────────────────────────────────────────────────────── */
/* Frame-kind helpers                                                         */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Type-narrowing predicate. We treat a missing `kind` as live_action so
 * legacy storyboards (emitted before this discriminated union landed)
 * continue to render unchanged.
 */
export const isDesignSequenceFrame = (
  frame: Frame,
): frame is DesignSequenceFrame =>
  (frame as DesignSequenceFrame).kind === "design_sequence";

export const isLiveActionFrame = (frame: Frame): frame is LiveActionFrame =>
  !isDesignSequenceFrame(frame);
