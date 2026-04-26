import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { TopBar } from './TopBar'
import type { Brand } from './types'
import {
  usePipelineStore,
  type FlowEdge,
  type FlowNode,
  type NodeKind,
  type NodeRunStatus,
} from '../../stores/pipelineStore'

// Pipeline builder — interactive canvas with draggable nodes, port-to-port
// connection drawing, palette-based node creation, and per-node properties
// editing.
//
// Implementation notes:
//   * Coordinates are stored in *world* space (the absolute-positioned canvas
//     origin). Mouse → world conversion accounts for the canvas viewport's
//     bounding rect + scroll offset; we don't apply a CSS zoom transform so
//     the math stays direct (the zoom display is informational for now).
//   * Drag, connect-drawing, and selection use document-level listeners so
//     drags continue when the cursor leaves a node — a common gotcha with
//     element-only listeners.
//   * Edges live as ``{id, from, to}`` and are routed as cubic beziers from
//     the right port of ``from`` to the left port of ``to``.
//   * State is owned by ``usePipelineStore`` (Zustand). Every nodes/edges
//     mutation goes through the store, which debounces a PUT to
//     /api/pipelines/{id}. Run progress streams in via the event bus.

type Connecting = { fromId: string; x: number; y: number } | null

const NODE_W = 220
const NODE_H = 64
const WORLD_W = 1600
const WORLD_H = 1100

const TINT: Record<
  FlowNode['tint'],
  { bg: string; fg: string; ring: string }
> = {
  violet: { bg: '#eef0ff', fg: '#5b50e6', ring: 'rgba(91,80,230,0.35)' },
  emerald: { bg: '#dcf3e9', fg: '#1f9e6e', ring: 'rgba(31,158,110,0.35)' },
  amber: { bg: '#fbe8d6', fg: '#d97a3a', ring: 'rgba(217,122,58,0.35)' },
  sky: { bg: '#e0e7ff', fg: '#4338ca', ring: 'rgba(67,56,202,0.35)' },
  rose: { bg: '#ffe4ec', fg: '#be185d', ring: 'rgba(190,24,93,0.35)' },
}

// Trigger variants — what *fires* the pipeline. Keyed by id so the
// PropertiesPanel can pick the right form and the backend's
// services/pipeline/triggers.py can match. Default is `manual` so a
// brand-new trigger node is harmless until configured.
export const TRIGGER_VARIANTS = [
  { id: 'manual', label: 'Manual ▶', hint: 'Only runs when you press Run.' },
  {
    id: 'on_kanban_shipped',
    label: 'On kanban / Trello / Jira card done',
    hint: 'Fires when a card moves into a Done-style column.',
  },
  {
    id: 'on_shop_event',
    label: 'On shop event',
    hint: 'Fires on cart_abandoned / subscription_lapsed.',
  },
  {
    id: 'scheduled',
    label: 'Scheduled (every N minutes)',
    hint: 'Wakes on an interval and pulls fresh data.',
  },
  {
    id: 'webhook',
    label: 'Webhook (POST URL)',
    hint: 'External services POST to fire the run.',
  },
] as const

export const MODEL_VARIANTS = [
  { id: 'tag', label: 'Tag / Classify', hint: 'Returns summary + tag counts + highlights.' },
  { id: 'summarize', label: 'Summarize', hint: 'Headline + N bullets.' },
  { id: 'generate_copy', label: 'Generate copy', hint: 'Channel-aware copywriting (LinkedIn / blog / email).' },
  { id: 'generate_image', label: 'Generate image', hint: 'Brand-grounded hero image.' },
  { id: 'personalize', label: 'Personalize per customer', hint: 'One email draft per upstream customer.' },
] as const

export const DEST_VARIANTS = [
  { id: 'log_only', label: 'Log only (preview)', hint: 'Receipt-only — useful while iterating.' },
  { id: 'save_campaign', label: 'Save as campaign', hint: 'Lands in Recent Runs as a draft campaign.' },
  { id: 'send_email', label: 'Queue emails', hint: 'One EmailSend row per personalize draft.' },
  { id: 'append_to_library', label: 'Append to brand library', hint: 'Adds generated images to brand assets.' },
] as const

const LIBRARY: Record<
  NodeKind,
  Pick<FlowNode, 'kind' | 'label' | 'name' | 'glyph' | 'tint' | 'config'>
> = {
  trigger: {
    kind: 'trigger',
    label: 'TRIGGER',
    name: 'Manual run',
    glyph: '⚡',
    tint: 'rose',
    config: { variant: 'manual' },
  },
  source: {
    kind: 'source',
    label: 'SOURCE',
    name: 'New Source',
    glyph: '◈',
    tint: 'sky',
    config: { provider: 'CRM Export · Mock', refreshMin: 15 },
  },
  filter: {
    kind: 'filter',
    label: 'FILTER',
    name: 'New Filter',
    glyph: '▽',
    tint: 'amber',
    config: { rule: '', strict: false },
  },
  model: {
    kind: 'model',
    label: 'AI MODEL',
    name: 'New Model',
    glyph: '✦',
    tint: 'violet',
    config: {
      variant: 'tag',
      version: 'v2.4.1 (Stable)',
      threshold: 75,
      tags: ['Urgency', 'Product Name'],
      prompt: '',
    },
  },
  destination: {
    kind: 'destination',
    label: 'DESTINATION',
    name: 'New Destination',
    glyph: '◇',
    tint: 'emerald',
    config: { variant: 'log_only', target: 'Log', format: 'JSON' },
  },
}

const INITIAL_NODES: FlowNode[] = [
  {
    id: 'n-trigger',
    ...LIBRARY.trigger,
    name: 'Manual run',
    config: { variant: 'manual' },
    x: 60,
    y: 200,
  },
  {
    id: 'n-source',
    ...LIBRARY.source,
    name: 'CRM Export',
    config: { provider: 'CRM Export · Mock', refreshMin: 15 },
    x: 320,
    y: 200,
  },
  {
    id: 'n-model',
    ...LIBRARY.model,
    name: 'Sentiment Analyzer',
    config: {
      variant: 'tag',
      version: 'v2.4.1 (Stable)',
      threshold: 75,
      tags: ['Urgency', 'Product Name'],
      prompt: '',
    },
    x: 600,
    y: 200,
  },
  {
    id: 'n-filter',
    ...LIBRARY.filter,
    name: 'High-spend only',
    config: { rule: 'spend', strict: false },
    x: 600,
    y: 360,
  },
  {
    id: 'n-dest',
    ...LIBRARY.destination,
    name: 'Save as campaign',
    config: { variant: 'save_campaign', target: 'Campaign' },
    x: 880,
    y: 200,
  },
]

const INITIAL_EDGES: FlowEdge[] = [
  { id: 'e-0', from: 'n-trigger', to: 'n-source' },
  { id: 'e-1', from: 'n-source', to: 'n-model' },
  { id: 'e-2', from: 'n-source', to: 'n-filter' },
  { id: 'e-3', from: 'n-filter', to: 'n-model' },
  { id: 'e-4', from: 'n-model', to: 'n-dest' },
]

export function Pipeline({ brand }: { brand: Brand }) {
  const [search, setSearch] = useState('')
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>('n-model')
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  const [propsOpen, setPropsOpen] = useState(true)
  const [zoom, setZoom] = useState(100)
  const [connecting, setConnecting] = useState<Connecting>(null)
  const [showLogs, setShowLogs] = useState(true)

  const viewRef = useRef<HTMLDivElement>(null)
  const worldRef = useRef<HTMLDivElement>(null)

  const nodes = usePipelineStore((s) => s.nodes)
  const edges = usePipelineStore((s) => s.edges)
  const setNodes = usePipelineStore((s) => s.setNodes)
  const setEdges = usePipelineStore((s) => s.setEdges)
  const setName = usePipelineStore((s) => s.setName)
  const name = usePipelineStore((s) => s.name)
  const savedAt = usePipelineStore((s) => s.savedAt)
  const saving = usePipelineStore((s) => s.saving)
  const dirty = usePipelineStore((s) => s.dirty)
  const runStatus = usePipelineStore((s) => s.runStatus)
  const nodeStates = usePipelineStore((s) => s.nodeStates)
  const runLogs = usePipelineStore((s) => s.runLogs)
  const runResult = usePipelineStore((s) => s.runResult)
  const runError = usePipelineStore((s) => s.runError)
  const hydrate = usePipelineStore((s) => s.hydrate)
  const selectOrCreate = usePipelineStore((s) => s.selectOrCreate)
  const saveNow = usePipelineStore((s) => s.saveNow)
  const runFn = usePipelineStore((s) => s.run)
  const pipelineId = usePipelineStore((s) => s.pipelineId)

  // First load: list pipelines for this brand. If empty, seed a default
  // sentiment-flow demo so the canvas isn't blank on a fresh dashboard.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      await hydrate(brand.id)
      if (cancelled) return
      const cur = usePipelineStore.getState()
      if (!cur.pipelineId) {
        await selectOrCreate(brand.id, {
          name: 'Customer Sentiment Flow',
          nodes: INITIAL_NODES,
          edges: INITIAL_EDGES,
        })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [brand.id, hydrate, selectOrCreate])

  const selected = nodes.find((n) => n.id === selectedNodeId) ?? null

  // Translate a screen-space mouse position into world (canvas-local)
  // coordinates. Anchoring to the world div's bounding rect — not the
  // outer scroll container — keeps the math correct under (a) the sticky
  // toolbar offset above the world and (b) any scroll position, since
  // getBoundingClientRect already reflects scroll.
  function clientToWorld(clientX: number, clientY: number) {
    const w = worldRef.current
    if (!w) return { x: clientX, y: clientY }
    const r = w.getBoundingClientRect()
    return {
      x: clientX - r.left,
      y: clientY - r.top,
    }
  }

  function startNodeDrag(e: React.MouseEvent, nodeId: string) {
    e.stopPropagation()
    if (e.button !== 0) return
    setSelectedNodeId(nodeId)
    setSelectedEdgeId(null)
    if (!propsOpen) setPropsOpen(true)
    const node = nodes.find((n) => n.id === nodeId)
    if (!node) return
    const start = clientToWorld(e.clientX, e.clientY)
    const startNode = { x: node.x, y: node.y }

    function onMove(ev: MouseEvent) {
      const cur = clientToWorld(ev.clientX, ev.clientY)
      const nx = Math.max(0, Math.min(WORLD_W - NODE_W, startNode.x + (cur.x - start.x)))
      const ny = Math.max(0, Math.min(WORLD_H - NODE_H, startNode.y + (cur.y - start.y)))
      setNodes((s: FlowNode[]) =>
        s.map((n) => (n.id === nodeId ? { ...n, x: nx, y: ny } : n)),
      )
    }
    function onUp() {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  function startConnection(e: React.MouseEvent, fromId: string) {
    e.stopPropagation()
    e.preventDefault()
    if (e.button !== 0) return
    const start = clientToWorld(e.clientX, e.clientY)
    setConnecting({ fromId, x: start.x, y: start.y })

    function onMove(ev: MouseEvent) {
      const cur = clientToWorld(ev.clientX, ev.clientY)
      setConnecting({ fromId, x: cur.x, y: cur.y })
    }
    function onUp(ev: MouseEvent) {
      const el = document.elementFromPoint(ev.clientX, ev.clientY)
      const targetId =
        el?.closest('[data-input-port]')?.getAttribute('data-node-id') ?? null
      if (targetId && targetId !== fromId) {
        setEdges((s: FlowEdge[]) =>
          s.some((e) => e.from === fromId && e.to === targetId)
            ? s
            : [...s, { id: `e-${Date.now()}`, from: fromId, to: targetId }],
        )
      }
      setConnecting(null)
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  function addNode(kind: NodeKind) {
    const v = viewRef.current
    const cx = v ? v.scrollLeft + v.clientWidth / 2 - NODE_W / 2 : 400
    const cy = v ? v.scrollTop + v.clientHeight / 2 - NODE_H / 2 : 300
    const id = `n-${Date.now()}`
    setNodes((s: FlowNode[]) => [
      ...s,
      {
        id,
        ...LIBRARY[kind],
        config: { ...LIBRARY[kind].config },
        x: Math.max(20, cx),
        y: Math.max(20, cy),
      },
    ])
    setSelectedNodeId(id)
    setSelectedEdgeId(null)
    setPropsOpen(true)
  }

  function deleteNode(id: string) {
    setNodes((s: FlowNode[]) => s.filter((n) => n.id !== id))
    setEdges((s: FlowEdge[]) => s.filter((e) => e.from !== id && e.to !== id))
    if (selectedNodeId === id) setSelectedNodeId(null)
  }

  function deleteEdge(id: string) {
    setEdges((s: FlowEdge[]) => s.filter((e) => e.id !== id))
    if (selectedEdgeId === id) setSelectedEdgeId(null)
  }

  function updateNode(id: string, patch: Partial<FlowNode>) {
    setNodes((s: FlowNode[]) =>
      s.map((n) => (n.id === id ? { ...n, ...patch } : n)),
    )
  }

  // Keyboard: delete selected node/edge with Delete or Backspace.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== 'Delete' && e.key !== 'Backspace') return
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (selectedEdgeId) {
        e.preventDefault()
        deleteEdge(selectedEdgeId)
      } else if (selectedNodeId) {
        e.preventDefault()
        deleteNode(selectedNodeId)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedEdgeId, selectedNodeId])

  function clearSelection() {
    setSelectedNodeId(null)
    setSelectedEdgeId(null)
  }

  return (
    <main className="flex flex-col">
      <TopBar brand={brand} searchValue={search} onSearchChange={setSearch} />
      <div className="relative flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <Canvas
            viewRef={viewRef}
            worldRef={worldRef}
            nodes={nodes}
            edges={edges}
            nodeStates={nodeStates}
            selectedNodeId={selectedNodeId}
            selectedEdgeId={selectedEdgeId}
            connecting={connecting}
            name={name}
            savedAt={savedAt}
            saving={saving}
            dirty={dirty}
            runStatus={runStatus}
            canRun={Boolean(pipelineId) && nodes.length > 0}
            onRun={() => void runFn()}
            onSave={() => void saveNow()}
            onRename={setName}
            onCanvasClick={clearSelection}
            onNodeMouseDown={startNodeDrag}
            onPortMouseDown={startConnection}
            onSelectEdge={(id) => {
              setSelectedEdgeId(id)
              setSelectedNodeId(null)
            }}
            onDeleteEdge={deleteEdge}
            onAddNode={addNode}
          />
          <RunLogPanel
            open={showLogs}
            onToggle={() => setShowLogs((s) => !s)}
            runStatus={runStatus}
            nodeStates={nodeStates}
            logs={runLogs}
            result={runResult}
            error={runError}
            nodes={nodes}
          />
          <BottomBar zoom={zoom} onZoom={setZoom} onAdd={addNode} />
        </div>

        <AnimatePresence>
          {propsOpen && selected && (
            <PropertiesPanel
              key={selected.id}
              node={selected}
              onChange={(patch) => updateNode(selected.id, patch)}
              onClose={() => setPropsOpen(false)}
              onDelete={() => deleteNode(selected.id)}
              onApply={() => void saveNow()}
              saving={saving}
              dirty={dirty}
            />
          )}
        </AnimatePresence>
      </div>
    </main>
  )
}

// =================================================================== Canvas

function Canvas({
  viewRef,
  worldRef,
  nodes,
  edges,
  nodeStates,
  selectedNodeId,
  selectedEdgeId,
  connecting,
  name,
  savedAt,
  saving,
  dirty,
  runStatus,
  canRun,
  onRun,
  onSave,
  onRename,
  onCanvasClick,
  onNodeMouseDown,
  onPortMouseDown,
  onSelectEdge,
  onDeleteEdge,
  onAddNode,
}: {
  viewRef: React.RefObject<HTMLDivElement | null>
  worldRef: React.RefObject<HTMLDivElement | null>
  nodes: FlowNode[]
  edges: FlowEdge[]
  nodeStates: Record<string, NodeRunStatus>
  selectedNodeId: string | null
  selectedEdgeId: string | null
  connecting: Connecting
  name: string
  savedAt: string | null
  saving: boolean
  dirty: boolean
  runStatus: 'idle' | 'running' | 'completed' | 'failed'
  canRun: boolean
  onRun: () => void
  onSave: () => void
  onRename: (next: string) => void
  onCanvasClick: () => void
  onNodeMouseDown: (e: React.MouseEvent, nodeId: string) => void
  onPortMouseDown: (e: React.MouseEvent, fromId: string) => void
  onSelectEdge: (id: string) => void
  onDeleteEdge: (id: string) => void
  onAddNode: (kind: NodeKind) => void
}) {
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))

  return (
    <div
      ref={viewRef}
      onMouseDown={onCanvasClick}
      className="relative flex-1 overflow-auto"
    >
      <div className="sticky left-0 top-0 z-10 flex items-start gap-3 px-6 pt-4">
        <FlowHeader
          name={name}
          savedAt={savedAt}
          saving={saving}
          dirty={dirty}
          onRename={onRename}
        />
        <Palette onAdd={onAddNode} />
        <RunButton
          canRun={canRun}
          runStatus={runStatus}
          dirty={dirty}
          saving={saving}
          onRun={onRun}
          onSave={onSave}
        />
      </div>

      <div
        ref={worldRef}
        className="relative"
        style={{ width: WORLD_W, height: WORLD_H }}
      >
        {/* dot-grid backdrop */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage:
              'radial-gradient(rgba(20,20,40,0.07) 1px, transparent 1px)',
            backgroundSize: '24px 24px',
          }}
        />

        <svg
          className="pointer-events-none absolute inset-0"
          width={WORLD_W}
          height={WORLD_H}
        >
          <defs>
            <marker
              id="arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(20,20,40,0.35)" />
            </marker>
            <marker
              id="arrow-active"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path
                d="M 0 0 L 10 5 L 0 10 z"
                fill="var(--color-accent)"
              />
            </marker>
          </defs>

          {edges.map((e) => {
            const a = byId[e.from]
            const b = byId[e.to]
            if (!a || !b) return null
            const ax = a.x + NODE_W
            const ay = a.y + NODE_H / 2
            const bx = b.x
            const by = b.y + NODE_H / 2
            const d = bezierPath(ax, ay, bx, by)
            const isActive =
              e.from === selectedNodeId ||
              e.to === selectedNodeId ||
              e.id === selectedEdgeId
            const stroke = isActive
              ? 'var(--color-accent)'
              : 'rgba(20,20,40,0.22)'
            return (
              <g key={e.id} className="pointer-events-auto">
                {/* fat invisible hit target for easier edge-selection */}
                <path
                  d={d}
                  fill="none"
                  stroke="transparent"
                  strokeWidth={14}
                  onMouseDown={(ev) => {
                    ev.stopPropagation()
                    onSelectEdge(e.id)
                  }}
                  style={{ cursor: 'pointer' }}
                />
                <path
                  d={d}
                  fill="none"
                  stroke={stroke}
                  strokeWidth={isActive ? 2.2 : 1.6}
                  strokeLinecap="round"
                  markerEnd={
                    isActive ? 'url(#arrow-active)' : 'url(#arrow)'
                  }
                  pointerEvents="none"
                />
              </g>
            )
          })}

          {/* live ghost edge while connecting */}
          {connecting &&
            (() => {
              const from = byId[connecting.fromId]
              if (!from) return null
              const ax = from.x + NODE_W
              const ay = from.y + NODE_H / 2
              const d = bezierPath(ax, ay, connecting.x, connecting.y)
              return (
                <path
                  d={d}
                  fill="none"
                  stroke="var(--color-accent)"
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  strokeLinecap="round"
                />
              )
            })()}
        </svg>

        {nodes.map((n) => (
          <NodeView
            key={n.id}
            node={n}
            selected={n.id === selectedNodeId}
            runStatus={nodeStates[n.id] ?? null}
            onMouseDown={(e) => onNodeMouseDown(e, n.id)}
            onPortMouseDown={(e) => onPortMouseDown(e, n.id)}
          />
        ))}

        {/* Disconnect button at the midpoint of the selected edge.
            Stays in DOM (not SVG) so the click target is a real button
            with hover affordances. */}
        {selectedEdgeId &&
          (() => {
            const edge = edges.find((e) => e.id === selectedEdgeId)
            if (!edge) return null
            const a = byId[edge.from]
            const b = byId[edge.to]
            if (!a || !b) return null
            const ax = a.x + NODE_W
            const ay = a.y + NODE_H / 2
            const bx = b.x
            const by = b.y + NODE_H / 2
            const mx = (ax + bx) / 2
            const my = (ay + by) / 2
            return (
              <button
                onMouseDown={(e) => {
                  e.stopPropagation()
                  onDeleteEdge(edge.id)
                }}
                title="Disconnect"
                aria-label="Disconnect"
                className="absolute z-10 grid h-6 w-6 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-bg-card text-[12px] text-fg-mute shadow-[0_2px_8px_rgba(20,20,40,0.15)] ring-1 ring-line transition hover:bg-red-50 hover:text-red-600 hover:ring-red-300"
                style={{ left: mx, top: my }}
              >
                ✕
              </button>
            )
          })()}
      </div>
    </div>
  )
}

function FlowHeader({
  name,
  savedAt,
  saving,
  dirty,
  onRename,
}: {
  name: string
  savedAt: string | null
  saving: boolean
  dirty: boolean
  onRename: (next: string) => void
}) {
  // Live "Xs ago" tick that updates while no other state changes — without
  // it the label would freeze between renders triggered by the canvas.
  // 1s cadence so transitions like "just now → 5s ago → 30s ago" feel real.
  const [, force] = useState(0)
  useEffect(() => {
    const id = setInterval(() => force((n) => n + 1), 1_000)
    return () => clearInterval(id)
  }, [])

  let label: string
  let dotClass = 'bg-emerald-500'
  if (saving) {
    label = 'Saving…'
    dotClass = 'bg-amber-500 animate-pulse'
  } else if (dirty) {
    label = 'Unsaved changes'
    dotClass = 'bg-amber-500'
  } else if (savedAt) {
    label = `Auto-saved ${formatAgo(savedAt)}`
  } else {
    label = 'Not saved yet'
    dotClass = 'bg-fg-dim'
  }
  return (
    <div className="hairline rounded-2xl bg-bg-card px-4 py-3 shadow-[0_2px_10px_rgba(20,20,40,0.04)]">
      <input
        value={name}
        onChange={(e) => onRename(e.target.value)}
        className="w-full bg-transparent text-[18px] font-semibold leading-tight tracking-[-0.01em] outline-none focus:text-accent"
        aria-label="Pipeline name"
      />
      <div className="mt-1 flex items-center gap-2 text-[11px] text-fg-mute">
        <span className={`h-1.5 w-1.5 rounded-full ${dotClass}`} />
        <span>{label}</span>
      </div>
    </div>
  )
}

function RunButton({
  canRun,
  runStatus,
  dirty,
  saving,
  onRun,
  onSave,
}: {
  canRun: boolean
  runStatus: 'idle' | 'running' | 'completed' | 'failed'
  dirty: boolean
  saving: boolean
  onRun: () => void
  onSave: () => void
}) {
  const isRunning = runStatus === 'running'
  const tone =
    runStatus === 'failed'
      ? 'from-red-500 to-red-600'
      : runStatus === 'completed'
        ? 'from-emerald-500 to-emerald-600'
        : 'from-accent to-[var(--color-accent-deep)]'
  return (
    <div className="hairline inline-flex items-stretch overflow-hidden rounded-full bg-bg-card shadow-[0_2px_10px_rgba(20,20,40,0.06)]">
      <button
        onClick={onSave}
        disabled={saving || !dirty}
        className="px-3.5 py-2 text-[11.5px] font-medium text-fg-mute transition hover:text-fg disabled:opacity-50"
        title="Save now"
      >
        {saving ? 'Saving…' : dirty ? 'Save' : 'Saved'}
      </button>
      <button
        onClick={onRun}
        disabled={!canRun || isRunning}
        className={`bg-gradient-to-b ${tone} px-4 py-2 text-[12px] font-semibold text-white shadow-inner disabled:opacity-50`}
        title={canRun ? 'Run pipeline' : 'Add a node first'}
      >
        {isRunning ? '● Running…' : runStatus === 'completed' ? '✓ Run again' : runStatus === 'failed' ? '⚠ Retry' : '▶ Run'}
      </button>
    </div>
  )
}

function formatAgo(iso: string): string {
  // SQLite drops the tzinfo on round-trip, so the backend may serialize a
  // naive ISO string like "2026-04-26T05:10:02.868228" with no Z / offset.
  // JS Date.parse treats those as *local* time, which makes the label drift
  // by the user's UTC offset (e.g. "2h ago" right after a fresh save in
  // Berlin). Append Z when the string lacks an explicit timezone so we
  // consistently parse as UTC — the canonical write timezone.
  const hasTz = /[Z]|[+\-]\d{2}:?\d{2}$/.test(iso)
  const t = Date.parse(hasTz ? iso : `${iso}Z`)
  if (Number.isNaN(t)) return 'just now'
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000))
  if (sec < 5) return 'just now'
  if (sec < 60) return `${sec}s ago`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  return `${Math.floor(hr / 24)}d ago`
}

function NodeView({
  node,
  selected,
  runStatus,
  onMouseDown,
  onPortMouseDown,
}: {
  node: FlowNode
  selected: boolean
  runStatus: NodeRunStatus | null
  onMouseDown: (e: React.MouseEvent) => void
  onPortMouseDown: (e: React.MouseEvent) => void
}) {
  const t = TINT[node.tint]
  const runRing =
    runStatus === 'running'
      ? '0 0 0 2px rgba(91,80,230,0.55), 0 0 0 6px rgba(91,80,230,0.15)'
      : runStatus === 'completed'
        ? '0 0 0 2px rgba(31,158,110,0.55)'
        : runStatus === 'failed'
          ? '0 0 0 2px rgba(220,38,38,0.55)'
          : null
  const style: CSSProperties = {
    left: node.x,
    top: node.y,
    width: NODE_W,
    height: NODE_H,
    boxShadow: runRing
      ? `${runRing}, 0 8px 24px rgba(91,80,230,0.18)`
      : selected
        ? `0 0 0 2px ${t.ring}, 0 8px 24px rgba(91,80,230,0.18)`
        : `inset 0 0 0 1px var(--color-line), 0 2px 8px rgba(20,20,40,0.04)`,
    cursor: 'grab',
  }
  return (
    <div
      onMouseDown={onMouseDown}
      className={`absolute flex select-none items-center gap-3 rounded-2xl bg-bg-card px-4 py-3 transition-shadow ${runStatus === 'running' ? 'animate-pulse' : ''}`}
      style={style}
    >
      <span
        className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-[15px]"
        style={{ background: t.bg, color: t.fg }}
      >
        {node.glyph}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-mute">
          {node.label}
        </div>
        <div className="truncate text-[13px] font-medium leading-tight">
          {node.name}
        </div>
      </div>
      <RunStatusGlyph status={runStatus} />
      <span className="text-[14px] text-fg-dim">⋮</span>

      {/* input port — passive drop target identified by data-input-port */}
      <span
        data-input-port
        data-node-id={node.id}
        className="absolute -left-1.5 top-1/2 grid h-3 w-3 -translate-y-1/2 place-items-center rounded-full bg-bg-card shadow-[0_0_0_1px_var(--color-line)] transition hover:shadow-[0_0_0_2px_var(--color-accent)]"
        title="Input"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-fg-dim" />
      </span>
      {/* output port — drag from here to draw a connection */}
      <span
        onMouseDown={onPortMouseDown}
        className="absolute -right-1.5 top-1/2 grid h-3 w-3 -translate-y-1/2 cursor-crosshair place-items-center rounded-full bg-bg-card shadow-[0_0_0_1px_var(--color-line)] transition hover:shadow-[0_0_0_2px_var(--color-accent)]"
        title="Drag to connect"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-accent" />
      </span>
    </div>
  )
}

// ================================================================== Palette

function Palette({ onAdd }: { onAdd: (kind: NodeKind) => void }) {
  const items: {
    kind: NodeKind
    label: string
    glyph: string
    tint: FlowNode['tint']
  }[] = [
    { kind: 'trigger', label: 'Trigger', glyph: '⚡', tint: 'rose' },
    { kind: 'source', label: 'Source', glyph: '◈', tint: 'sky' },
    { kind: 'filter', label: 'Filter', glyph: '▽', tint: 'amber' },
    { kind: 'model', label: 'AI Model', glyph: '✦', tint: 'violet' },
    { kind: 'destination', label: 'Destination', glyph: '◇', tint: 'emerald' },
  ]
  return (
    <div className="hairline inline-flex items-center gap-1 rounded-full bg-bg-card p-1 shadow-[0_2px_10px_rgba(20,20,40,0.06)]">
      <span className="px-2 text-[10px] font-medium uppercase tracking-[0.16em] text-fg-mute">
        Add
      </span>
      {items.map((it) => {
        const t = TINT[it.tint]
        return (
          <button
            key={it.kind}
            onClick={() => onAdd(it.kind)}
            className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-medium text-fg-mute transition hover:bg-bg-soft hover:text-fg"
          >
            <span
              className="grid h-4 w-4 place-items-center rounded text-[10px]"
              style={{ background: t.bg, color: t.fg }}
            >
              {it.glyph}
            </span>
            {it.label}
          </button>
        )
      })}
    </div>
  )
}

// ================================================================ BottomBar

function BottomBar({
  zoom,
  onZoom,
  onAdd,
}: {
  zoom: number
  onZoom: (z: number) => void
  onAdd: (k: NodeKind) => void
}) {
  const clamp = (v: number) => Math.min(160, Math.max(50, v))
  return (
    <div className="flex items-center justify-between border-t border-line bg-bg-card/60 px-6 py-2.5 text-[11px] text-fg-mute backdrop-blur">
      <div className="flex items-center gap-3">
        <span className="hidden md:inline">
          Drag node body to move · drag right port to connect · Delete
          removes selection
        </span>
        <button
          onClick={() => onAdd('model')}
          className="hairline inline-flex items-center gap-1 rounded-full bg-bg-card px-2.5 py-1 text-fg-mute hover:text-fg md:hidden"
        >
          + Add
        </button>
      </div>
      <div className="hairline inline-flex items-center gap-1 rounded-full bg-bg-card px-1 py-1">
        <button
          onClick={() => onZoom(clamp(zoom - 10))}
          className="grid h-6 w-6 place-items-center rounded-full text-fg-mute hover:bg-bg-soft hover:text-fg"
          aria-label="Zoom out"
        >
          −
        </button>
        <span className="px-2 tabular-nums text-fg-mute">{zoom}%</span>
        <button
          onClick={() => onZoom(clamp(zoom + 10))}
          className="grid h-6 w-6 place-items-center rounded-full text-fg-mute hover:bg-bg-soft hover:text-fg"
          aria-label="Zoom in"
        >
          +
        </button>
        <button
          onClick={() => onZoom(100)}
          className="grid h-6 w-6 place-items-center rounded-full text-fg-mute hover:bg-bg-soft hover:text-fg"
          aria-label="Fit"
          title="Reset zoom"
        >
          ⊡
        </button>
      </div>
    </div>
  )
}

// ============================================================== Properties

function RunStatusGlyph({ status }: { status: NodeRunStatus | null }) {
  if (!status || status === 'pending') return null
  if (status === 'running') {
    return (
      <span
        className="grid h-5 w-5 place-items-center rounded-full bg-accent/15 text-[10px] font-semibold text-accent"
        title="Running"
      >
        ●
      </span>
    )
  }
  if (status === 'completed') {
    return (
      <span
        className="grid h-5 w-5 place-items-center rounded-full bg-emerald-500/15 text-[10px] font-semibold text-emerald-600"
        title="Completed"
      >
        ✓
      </span>
    )
  }
  return (
    <span
      className="grid h-5 w-5 place-items-center rounded-full bg-red-500/15 text-[10px] font-semibold text-red-600"
      title="Failed"
    >
      ⚠
    </span>
  )
}

function PropertiesPanel({
  node,
  onChange,
  onClose,
  onDelete,
  onApply,
  saving,
  dirty,
}: {
  node: FlowNode
  onChange: (patch: Partial<FlowNode>) => void
  onClose: () => void
  onDelete: () => void
  onApply: () => void
  saving: boolean
  dirty: boolean
}) {
  const t = TINT[node.tint]
  return (
    <motion.aside
      initial={{ x: 24, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: 24, opacity: 0 }}
      transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      className="flex w-[320px] shrink-0 flex-col border-l border-line bg-bg-card"
    >
      <header className="flex items-center justify-between px-5 pt-5">
        <div className="text-[14px] font-semibold">Properties</div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="grid h-7 w-7 place-items-center rounded-md text-fg-mute hover:bg-bg-soft hover:text-fg"
        >
          ✕
        </button>
      </header>

      <div className="mt-5 flex items-center gap-3 px-5">
        <span
          className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-[15px]"
          style={{ background: t.bg, color: t.fg }}
        >
          {node.glyph}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-mute">
            Selected node
          </div>
          <input
            value={node.name}
            onChange={(e) => onChange({ name: e.target.value })}
            className="w-full bg-transparent text-[14px] font-medium leading-tight outline-none focus:text-accent"
          />
        </div>
      </div>

      <div className="mt-6 flex-1 overflow-y-auto px-5 pb-5 [scrollbar-width:thin]">
        <NodeFields node={node} onChange={onChange} />
      </div>

      <div className="border-t border-line p-3">
        <div className="flex items-center gap-2">
          <button
            onClick={onDelete}
            className="hairline grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-bg-card text-fg-mute transition hover:border-red-300 hover:text-red-500"
            aria-label="Delete node"
            title="Delete node"
          >
            ⌫
          </button>
          <button
            onClick={onApply}
            disabled={saving || !dirty}
            className="flex-1 rounded-xl bg-gradient-to-b from-accent to-[var(--color-accent-deep)] py-2.5 text-[13px] font-medium text-white shadow-[0_6px_18px_rgba(91,80,230,0.35)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? 'Saving…' : dirty ? 'Apply Changes' : 'Saved'}
          </button>
        </div>
      </div>
    </motion.aside>
  )
}

function NodeFields({
  node,
  onChange,
}: {
  node: FlowNode
  onChange: (patch: Partial<FlowNode>) => void
}) {
  function setConfig(patch: Record<string, unknown>) {
    onChange({ config: { ...node.config, ...patch } })
  }

  if (node.kind === 'trigger') {
    return <TriggerFields cfg={node.config} onSet={setConfig} />
  }
  if (node.kind === 'model') {
    return <ModelFields cfg={node.config} onSet={setConfig} />
  }
  if (node.kind === 'source') {
    const cfg = node.config as { provider: string; refreshMin: number }
    return (
      <SourceFields
        provider={cfg.provider}
        refreshMin={cfg.refreshMin ?? 15}
        onSet={setConfig}
      />
    )
  }
  if (node.kind === 'filter') {
    const cfg = node.config as { rule: string; strict: boolean }
    return (
      <FilterFields
        rule={cfg.rule ?? ''}
        strict={!!cfg.strict}
        onSet={setConfig}
      />
    )
  }
  return <DestinationFields cfg={node.config} onSet={setConfig} />
}

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="mt-5 first:mt-0">
      <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-mute">
        {label}
      </div>
      <div className="mt-2">{children}</div>
    </div>
  )
}

function TriggerFields({
  cfg,
  onSet,
}: {
  cfg: Record<string, unknown>
  onSet: (p: Record<string, unknown>) => void
}) {
  const variant = String((cfg.variant as string) || 'manual')
  const meta = TRIGGER_VARIANTS.find((v) => v.id === variant)
  return (
    <>
      <Field label="Trigger type">
        <select
          value={variant}
          onChange={(e) => onSet({ variant: e.target.value })}
          className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] outline-none focus:border-accent"
        >
          {TRIGGER_VARIANTS.map((v) => (
            <option key={v.id} value={v.id}>
              {v.label}
            </option>
          ))}
        </select>
        {meta && (
          <div className="mt-1.5 text-[11.5px] leading-snug text-fg-mute">
            {meta.hint}
          </div>
        )}
      </Field>

      {variant === 'on_kanban_shipped' && (
        <>
          <Field label="Column filter (substring, blank = any)">
            <input
              value={String(cfg.column_filter || '')}
              onChange={(e) => onSet({ column_filter: e.target.value })}
              placeholder="Done"
              className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] outline-none focus:border-accent"
            />
          </Field>
          <Field label="Label filter (substring, blank = any)">
            <input
              value={String(cfg.label_filter || '')}
              onChange={(e) => onSet({ label_filter: e.target.value })}
              placeholder="marketing"
              className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] outline-none focus:border-accent"
            />
          </Field>
        </>
      )}

      {variant === 'on_shop_event' && (
        <Field label="Shop event kind">
          <select
            value={String(cfg.shop_kind || 'cart_abandoned')}
            onChange={(e) => onSet({ shop_kind: e.target.value })}
            className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] outline-none focus:border-accent"
          >
            <option value="cart_abandoned">cart_abandoned</option>
            <option value="subscription_lapsed">subscription_lapsed</option>
            <option value="">any</option>
          </select>
        </Field>
      )}

      {variant === 'scheduled' && (
        <Field label="Interval (minutes)">
          <input
            type="number"
            min={1}
            value={Number(cfg.interval_minutes || 60)}
            onChange={(e) => onSet({ interval_minutes: Number(e.target.value) })}
            className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] tabular-nums outline-none focus:border-accent"
          />
          <div className="mt-1.5 text-[11.5px] leading-snug text-fg-mute">
            Resolution is ~60s — sub-minute schedules are coalesced.
          </div>
        </Field>
      )}

      {variant === 'webhook' && (
        <WebhookFields cfg={cfg} onSet={onSet} />
      )}
    </>
  )
}

function WebhookFields({
  cfg,
  onSet,
}: {
  cfg: Record<string, unknown>
  onSet: (p: Record<string, unknown>) => void
}) {
  const pipelineId = usePipelineStore((s) => s.pipelineId)
  const token = String(cfg.token || '')
  const url = pipelineId
    ? `${window.location.origin}/api/pipelines/${pipelineId}/webhook`
    : '(save the pipeline first)'

  function genToken() {
    const random =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID().replace(/-/g, '')
        : Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2)
    onSet({ token: `tok_${random.slice(0, 24)}` })
  }

  return (
    <>
      <Field label="Webhook URL">
        <input
          readOnly
          value={url}
          onClick={(e) => (e.target as HTMLInputElement).select()}
          className="hairline w-full rounded-lg bg-bg-card px-3 py-2 font-mono text-[11.5px] outline-none focus:border-accent"
        />
      </Field>
      <Field label="Token (optional, recommended)">
        <div className="flex gap-2">
          <input
            value={token}
            onChange={(e) => onSet({ token: e.target.value })}
            placeholder="(unauthenticated)"
            className="hairline flex-1 rounded-lg bg-bg-card px-3 py-2 font-mono text-[11.5px] outline-none focus:border-accent"
          />
          <button
            onClick={genToken}
            className="hairline rounded-lg bg-bg-card px-2.5 text-[12px] text-fg-mute hover:text-fg"
            title="Generate token"
          >
            ↻
          </button>
        </div>
        <div className="mt-1.5 text-[11.5px] leading-snug text-fg-mute">
          Send as <span className="font-mono">X-Pipeline-Token</span> or
          <span className="font-mono"> Authorization: Bearer</span>.
        </div>
      </Field>
    </>
  )
}

function ModelFields({
  cfg,
  onSet,
}: {
  cfg: Record<string, unknown>
  onSet: (p: Record<string, unknown>) => void
}) {
  const variant = String((cfg.variant as string) || 'tag')
  const meta = MODEL_VARIANTS.find((v) => v.id === variant)
  return (
    <>
      <Field label="Model task">
        <select
          value={variant}
          onChange={(e) => onSet({ variant: e.target.value })}
          className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] outline-none focus:border-accent"
        >
          {MODEL_VARIANTS.map((v) => (
            <option key={v.id} value={v.id}>
              {v.label}
            </option>
          ))}
        </select>
        {meta && (
          <div className="mt-1.5 text-[11.5px] leading-snug text-fg-mute">
            {meta.hint}
          </div>
        )}
      </Field>

      {variant === 'tag' && <TagFields cfg={cfg} onSet={onSet} />}
      {variant === 'summarize' && <SummarizeFields cfg={cfg} onSet={onSet} />}
      {variant === 'generate_copy' && (
        <GenerateCopyFields cfg={cfg} onSet={onSet} />
      )}
      {variant === 'generate_image' && (
        <GenerateImageFields cfg={cfg} onSet={onSet} />
      )}
      {variant === 'personalize' && (
        <PersonalizeFields cfg={cfg} onSet={onSet} />
      )}

      <Field label="Custom system prompt (optional)">
        <textarea
          rows={4}
          value={String(cfg.prompt || '')}
          onChange={(e) => onSet({ prompt: e.target.value })}
          placeholder="Leave blank to use the variant's default prompt."
          className="hairline w-full resize-y rounded-lg bg-bg-card px-3 py-2 font-mono text-[11.5px] leading-snug outline-none focus:border-accent"
        />
      </Field>
    </>
  )
}

function TagFields({
  cfg,
  onSet,
}: {
  cfg: Record<string, unknown>
  onSet: (p: Record<string, unknown>) => void
}) {
  const version = String(cfg.version || 'v2.4.1 (Stable)')
  const threshold = Number(cfg.threshold ?? 75)
  const tags = (cfg.tags as string[]) || []
  const [draft, setDraft] = useState('')
  return (
    <>
      <Field label="Model Version">
        <select
          value={version}
          onChange={(e) => onSet({ version: e.target.value })}
          className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] outline-none focus:border-accent"
        >
          <option>v2.4.1 (Stable)</option>
          <option>v2.5 (Beta)</option>
          <option>v2.3 (Legacy)</option>
        </select>
      </Field>
      <Field label="Confidence Threshold">
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={0}
            max={100}
            value={threshold}
            onChange={(e) => onSet({ threshold: Number(e.target.value) })}
            className="flex-1 accent-[var(--color-accent)]"
          />
          <span className="w-10 text-right text-[12px] tabular-nums text-fg-mute">
            {threshold}%
          </span>
        </div>
      </Field>
      <Field label="Tags to Extract">
        <div className="flex flex-wrap gap-1.5">
          {tags.map((tag) => (
            <button
              key={tag}
              onClick={() => onSet({ tags: tags.filter((t) => t !== tag) })}
              className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-2.5 py-1 text-[11px] font-medium text-accent hover:bg-accent/10"
              title="Remove"
            >
              {tag}
              <span className="text-[9px] opacity-70">✕</span>
            </button>
          ))}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            const v = draft.trim()
            if (v && !tags.includes(v)) onSet({ tags: [...tags, v] })
            setDraft('')
          }}
          className="mt-2"
        >
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="+ Add Tag"
            className="hairline w-full rounded-full bg-bg-card px-3 py-1.5 text-[12px] outline-none placeholder:text-fg-dim focus:border-accent"
          />
        </form>
      </Field>
    </>
  )
}

function SummarizeFields({
  cfg,
  onSet,
}: {
  cfg: Record<string, unknown>
  onSet: (p: Record<string, unknown>) => void
}) {
  return (
    <Field label="Bullet count">
      <input
        type="number"
        min={1}
        max={8}
        value={Number(cfg.bullets ?? 3)}
        onChange={(e) => onSet({ bullets: Number(e.target.value) })}
        className="hairline w-24 rounded-lg bg-bg-card px-3 py-2 text-[13px] tabular-nums outline-none focus:border-accent"
      />
    </Field>
  )
}

function GenerateCopyFields({
  cfg,
  onSet,
}: {
  cfg: Record<string, unknown>
  onSet: (p: Record<string, unknown>) => void
}) {
  return (
    <>
      <Field label="Channel">
        <select
          value={String(cfg.channel || 'linkedin')}
          onChange={(e) => onSet({ channel: e.target.value })}
          className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] outline-none focus:border-accent"
        >
          <option value="linkedin">LinkedIn post</option>
          <option value="instagram">Instagram caption</option>
          <option value="x">X / Twitter</option>
          <option value="blog">Blog article</option>
          <option value="email">Email</option>
        </select>
      </Field>
      <Field label="User request (what to write about)">
        <textarea
          rows={3}
          value={String(cfg.user_request || '')}
          onChange={(e) => onSet({ user_request: e.target.value })}
          placeholder="Leave blank to auto-summarize the upstream items."
          className="hairline w-full resize-y rounded-lg bg-bg-card px-3 py-2 text-[13px] leading-snug outline-none focus:border-accent"
        />
      </Field>
    </>
  )
}

function GenerateImageFields({
  cfg,
  onSet,
}: {
  cfg: Record<string, unknown>
  onSet: (p: Record<string, unknown>) => void
}) {
  return (
    <>
      <Field label="Channel (sets aspect ratio)">
        <select
          value={String(cfg.channel || 'instagram')}
          onChange={(e) => onSet({ channel: e.target.value })}
          className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] outline-none focus:border-accent"
        >
          <option value="instagram">Instagram (1:1)</option>
          <option value="linkedin">LinkedIn (16:9)</option>
          <option value="x">X (16:9)</option>
        </select>
      </Field>
    </>
  )
}

function PersonalizeFields({
  cfg,
  onSet,
}: {
  cfg: Record<string, unknown>
  onSet: (p: Record<string, unknown>) => void
}) {
  return (
    <>
      <Field label="Max customers per run">
        <input
          type="number"
          min={1}
          max={50}
          value={Number(cfg.max_customers ?? 5)}
          onChange={(e) => onSet({ max_customers: Number(e.target.value) })}
          className="hairline w-24 rounded-lg bg-bg-card px-3 py-2 text-[13px] tabular-nums outline-none focus:border-accent"
        />
      </Field>
      <Field label="Per-customer angle (optional)">
        <textarea
          rows={2}
          value={String(cfg.user_request || '')}
          onChange={(e) => onSet({ user_request: e.target.value })}
          placeholder="e.g. We just launched a fall edition — promote without sounding salesy."
          className="hairline w-full resize-y rounded-lg bg-bg-card px-3 py-2 text-[13px] leading-snug outline-none focus:border-accent"
        />
      </Field>
    </>
  )
}

function SourceFields({
  provider,
  refreshMin,
  onSet,
}: {
  provider: string
  refreshMin: number
  onSet: (p: Record<string, unknown>) => void
}) {
  return (
    <>
      <Field label="Source Provider">
        <select
          value={provider}
          onChange={(e) => onSet({ provider: e.target.value })}
          className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] outline-none focus:border-accent"
        >
          <option>CRM Export · Mock</option>
          <option>HubSpot</option>
          <option>Klaviyo</option>
          <option>Trello (kanban)</option>
        </select>
      </Field>
      <Field label="Refresh Interval">
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={1}
            max={60}
            value={refreshMin}
            onChange={(e) =>
              onSet({ refreshMin: Number(e.target.value) })
            }
            className="flex-1 accent-[var(--color-accent)]"
          />
          <span className="w-12 text-right text-[12px] tabular-nums text-fg-mute">
            {refreshMin} min
          </span>
        </div>
      </Field>
    </>
  )
}

function FilterFields({
  rule,
  strict,
  onSet,
}: {
  rule: string
  strict: boolean
  onSet: (p: Record<string, unknown>) => void
}) {
  return (
    <>
      <Field label="Rule">
        <textarea
          rows={3}
          value={rule}
          onChange={(e) => onSet({ rule: e.target.value })}
          className="hairline w-full resize-none rounded-lg bg-bg-card px-3 py-2 text-[13px] leading-snug outline-none focus:border-accent"
        />
      </Field>
      <Field label="Strict Mode">
        <label className="inline-flex cursor-pointer items-center gap-2 text-[13px] text-fg-mute">
          <input
            type="checkbox"
            checked={strict}
            onChange={(e) => onSet({ strict: e.target.checked })}
            className="accent-[var(--color-accent)]"
          />
          Drop on first violation
        </label>
      </Field>
    </>
  )
}

function DestinationFields({
  cfg,
  onSet,
}: {
  cfg: Record<string, unknown>
  onSet: (p: Record<string, unknown>) => void
}) {
  const variant = String((cfg.variant as string) || 'log_only')
  const meta = DEST_VARIANTS.find((v) => v.id === variant)
  const format = String(cfg.format || 'JSON')
  return (
    <>
      <Field label="Action">
        <select
          value={variant}
          onChange={(e) => onSet({ variant: e.target.value })}
          className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] outline-none focus:border-accent"
        >
          {DEST_VARIANTS.map((v) => (
            <option key={v.id} value={v.id}>
              {v.label}
            </option>
          ))}
        </select>
        {meta && (
          <div className="mt-1.5 text-[11.5px] leading-snug text-fg-mute">
            {meta.hint}
          </div>
        )}
      </Field>

      {variant === 'save_campaign' && (
        <>
          <Field label="Campaign title (optional — falls back to first draft)">
            <input
              value={String(cfg.title || '')}
              onChange={(e) => onSet({ title: e.target.value })}
              placeholder="e.g. Fall launch"
              className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] outline-none focus:border-accent"
            />
          </Field>
          <Field label="Original user request (stored on the campaign)">
            <input
              value={String(cfg.user_request || '')}
              onChange={(e) => onSet({ user_request: e.target.value })}
              className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] outline-none focus:border-accent"
            />
          </Field>
        </>
      )}

      {variant === 'send_email' && (
        <Field label="Fallback subject (used if upstream draft has none)">
          <input
            value={String(cfg.subject || '')}
            onChange={(e) => onSet({ subject: e.target.value })}
            placeholder="Update from your favorite brand"
            className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] outline-none focus:border-accent"
          />
        </Field>
      )}

      {variant === 'log_only' && (
        <Field label="Format">
          <div className="hairline inline-flex rounded-full bg-bg p-0.5">
            {(['JSON', 'CSV', 'Parquet'] as const).map((f) => (
              <button
                key={f}
                onClick={() => onSet({ format: f })}
                className={`rounded-full px-3 py-1 text-[11px] font-medium transition ${
                  format === f
                    ? 'bg-bg-card text-fg shadow-[0_1px_2px_rgba(20,20,40,0.06)]'
                    : 'text-fg-mute hover:text-fg'
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </Field>
      )}
    </>
  )
}

// ============================================================== Run logs

function RunLogPanel({
  open,
  onToggle,
  runStatus,
  nodeStates,
  logs,
  result,
  error,
  nodes,
}: {
  open: boolean
  onToggle: () => void
  runStatus: 'idle' | 'running' | 'completed' | 'failed'
  nodeStates: Record<string, NodeRunStatus>
  logs: {
    node_id: string
    level: string
    msg?: string
    kind?: string
    preview?: Record<string, unknown>
    at: string
  }[]
  result: Record<string, unknown> | null
  error: string | null
  nodes: FlowNode[]
}) {
  const nameById = useMemo(
    () => Object.fromEntries(nodes.map((n) => [n.id, n.name])),
    [nodes],
  )
  const counts = useMemo(() => {
    const c = { pending: 0, running: 0, completed: 0, failed: 0 }
    for (const v of Object.values(nodeStates)) {
      if (v in c) c[v as keyof typeof c]++
    }
    return c
  }, [nodeStates])

  const tone =
    runStatus === 'running'
      ? 'text-accent'
      : runStatus === 'completed'
        ? 'text-emerald-600'
        : runStatus === 'failed'
          ? 'text-red-600'
          : 'text-fg-mute'

  return (
    <div className="border-t border-line bg-bg-card/60 backdrop-blur">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between px-6 py-2 text-[11px] text-fg-mute hover:text-fg"
        aria-expanded={open}
      >
        <span className="flex items-center gap-3">
          <span className={`font-semibold uppercase tracking-[0.16em] ${tone}`}>
            Run · {runStatus}
          </span>
          <span className="text-fg-dim">
            {counts.completed} done · {counts.running} running · {counts.failed} failed · {counts.pending} pending
          </span>
        </span>
        <span className="text-fg-dim">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="grid max-h-[280px] grid-cols-[1fr_320px] gap-4 overflow-hidden border-t border-line/60 px-6 py-3">
          <div className="overflow-y-auto pr-2 [scrollbar-width:thin]">
            <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-mute">
              Logs
            </div>
            <ol className="mt-2 space-y-1.5">
              {logs.length === 0 && (
                <li className="text-[12px] text-fg-dim">
                  {runStatus === 'idle'
                    ? 'No runs yet — click Run to execute.'
                    : 'Waiting for the first node…'}
                </li>
              )}
              {logs.map((l, i) => (
                <li
                  key={`${l.node_id}-${i}`}
                  className={`flex items-start gap-2 text-[12px] ${
                    l.level === 'error' ? 'text-red-600' : 'text-fg'
                  }`}
                >
                  <span className="mt-0.5 inline-block w-2 shrink-0">
                    {l.level === 'error' ? '⚠' : '·'}
                  </span>
                  <span className="font-medium">
                    {nameById[l.node_id] ?? l.node_id}
                  </span>
                  {l.msg && (
                    <span className="text-fg-mute">{l.msg}</span>
                  )}
                  {!l.msg && l.preview && (
                    <span className="truncate text-fg-mute">
                      {Object.entries(l.preview)
                        .filter(([k]) => k !== 'preview')
                        .slice(0, 4)
                        .map(([k, v]) => `${k}: ${formatPreviewValue(v)}`)
                        .join(' · ')}
                    </span>
                  )}
                </li>
              ))}
              {error && (
                <li className="mt-2 rounded-md bg-red-50 px-2 py-1 text-[12px] text-red-700">
                  {error}
                </li>
              )}
            </ol>
          </div>
          <div className="overflow-y-auto border-l border-line pl-4 [scrollbar-width:thin]">
            <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-mute">
              Result
            </div>
            {result ? (
              <ResultView result={result} />
            ) : (
              <div className="mt-2 text-[12px] text-fg-dim">
                {runStatus === 'completed'
                  ? '(no destination output)'
                  : 'Run completes here.'}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function ResultView({ result }: { result: Record<string, unknown> }) {
  const target = (result.target as string | undefined) ?? null
  const recordCount = (result.record_count as number | undefined) ?? null
  const summary = (result.summary as string | undefined) ?? ''
  const tagCounts = (result.tag_counts as Record<string, number> | undefined) ?? {}
  const highlights =
    (result.highlights as { id: string; reason: string }[] | undefined) ?? []
  return (
    <div className="mt-2 space-y-3 text-[12px]">
      {target && (
        <div>
          <div className="text-fg-mute">Wrote to</div>
          <div className="font-medium">{target}</div>
        </div>
      )}
      {recordCount !== null && (
        <div>
          <div className="text-fg-mute">Records</div>
          <div className="font-medium tabular-nums">{recordCount}</div>
        </div>
      )}
      {summary && (
        <div>
          <div className="text-fg-mute">Summary</div>
          <div className="leading-snug">{summary}</div>
        </div>
      )}
      {Object.keys(tagCounts).length > 0 && (
        <div>
          <div className="text-fg-mute">Tag counts</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {Object.entries(tagCounts).map(([k, v]) => (
              <span
                key={k}
                className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] text-accent"
              >
                {k} · {v}
              </span>
            ))}
          </div>
        </div>
      )}
      {highlights.length > 0 && (
        <div>
          <div className="text-fg-mute">Highlights</div>
          <ul className="mt-1 space-y-1">
            {highlights.slice(0, 5).map((h, i) => (
              <li key={`${h.id}-${i}`} className="leading-snug">
                <span className="font-medium">{h.id}</span>
                <span className="text-fg-mute"> — {h.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function formatPreviewValue(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'number') return String(v)
  if (typeof v === 'string') return v.length > 40 ? v.slice(0, 40) + '…' : v
  if (typeof v === 'object') {
    const j = JSON.stringify(v)
    return j.length > 40 ? j.slice(0, 40) + '…' : j
  }
  return String(v)
}

// ================================================================== helpers

function bezierPath(ax: number, ay: number, bx: number, by: number) {
  const dx = Math.max(60, Math.abs(bx - ax) / 2)
  const c1x = ax + dx
  const c1y = ay
  const c2x = bx - dx
  const c2y = by
  return `M ${ax} ${ay} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${bx} ${by}`
}
