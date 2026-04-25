// Channel registry mirror — small client-side map for UI rendering.
// Source of truth lives in backend/app/services/agent/channels.py; keep
// these display fields in sync.

export type ChannelMeta = {
  id: string
  label: string
  glyph: string // short UI mark
  tint: string // hex accent for borders/badges
  aspect: '1.91:1' | '1:1' | '16:9' | '9:16' | '4:5' // display aspect
  textKind: string // "post", "caption", "tweet", "article"
  caption: string // sub-line under the channel header ("180-word post", ...)
}

export const CHANNELS: Record<string, ChannelMeta> = {
  linkedin: {
    id: 'linkedin',
    label: 'LinkedIn',
    glyph: 'in',
    tint: '#0a66c2',
    aspect: '1.91:1',
    textKind: 'post',
    caption: '130-220 words · banner',
  },
  instagram: {
    id: 'instagram',
    label: 'Instagram',
    glyph: 'ig',
    tint: '#e1306c',
    aspect: '1:1',
    textKind: 'caption',
    caption: '60-110 words · 1:1 square',
  },
  x: {
    id: 'x',
    label: 'X',
    glyph: '𝕏',
    tint: '#0f1419',
    aspect: '16:9',
    textKind: 'tweet',
    caption: '≤280 chars · 16:9',
  },
  blog: {
    id: 'blog',
    label: 'Blog',
    glyph: '📰',
    tint: '#22a07a',
    aspect: '16:9',
    textKind: 'article',
    caption: '350-450 words · header 16:9',
  },
}

export const CHANNEL_ORDER = ['linkedin', 'instagram', 'x', 'blog']

// CSS aspect-ratio value for the image preview frame.
export function aspectStyle(aspect: ChannelMeta['aspect']): string {
  switch (aspect) {
    case '1.91:1':
      return '1.91 / 1'
    case '1:1':
      return '1 / 1'
    case '9:16':
      return '9 / 16'
    case '4:5':
      return '4 / 5'
    case '16:9':
    default:
      return '16 / 9'
  }
}
