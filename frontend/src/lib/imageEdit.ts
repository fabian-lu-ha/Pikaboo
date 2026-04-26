/**
 * Client for /api/images/* — region-inpaint and sketch-to-image.
 *
 * Both routes return `{ image_url, edit_id }`. The image_url is a
 * `/api/storage/edits/...` (or scoped) URL the caller can drop straight
 * into an `<img src>` or a store update.
 */

export type EditAspect = '1:1' | '16:9' | '9:16'

// Closed scope set the backend accepts. Frame edits cluster under their
// parent storyboard so they can be cleaned up together.
export type EditScope = 'frame' | 'channel' | 'hero' | 'misc'

export type EditResult = {
  image_url: string
  edit_id: string
}

type EditRegionBody = {
  source_url: string
  mask_data_url: string
  prompt: string
  aspect: EditAspect
  save_scope?: EditScope
  save_scope_id?: string | null
}

type FromSketchBody = {
  sketch_data_url: string
  prompt: string
  aspect: EditAspect
  save_scope?: EditScope
  save_scope_id?: string | null
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) {
    let detail = ''
    try {
      const data = await r.json()
      detail = typeof data?.detail === 'string' ? data.detail : ''
    } catch {
      // ignore — fall through to status text
    }
    throw new Error(`${path} ${r.status}${detail ? `: ${detail}` : ''}`)
  }
  return (await r.json()) as T
}

export function editRegion(body: EditRegionBody): Promise<EditResult> {
  return postJson<EditResult>('/api/images/edit-region', body)
}

export function fromSketch(body: FromSketchBody): Promise<EditResult> {
  return postJson<EditResult>('/api/images/from-sketch', body)
}
