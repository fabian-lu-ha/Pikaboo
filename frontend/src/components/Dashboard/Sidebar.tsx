import { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'motion/react'
import { useAgentSessionStore } from '../../stores/agentSessionStore'
import { primaryName } from '../../lib/brandName'
import type { Brand } from './types'

export type NavId =
  | 'dashboard'
  | 'analytics'
  | 'campaigns'
  | 'audience'
  | 'voice'
  | 'geo'
  | 'library'
  | 'pipeline'
  | 'reports'
  | 'settings'

const NAV: { id: NavId; label: string; icon: string }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: '◫' },
  { id: 'analytics', label: 'Analytics', icon: '◴' },
  { id: 'geo', label: 'GEO', icon: '◊' },
  { id: 'campaigns', label: 'Campaigns', icon: '✦' },
  { id: 'audience', label: 'Audience', icon: '◉' },
  { id: 'voice', label: 'Voice', icon: '◐' },
  { id: 'library', label: 'Library', icon: '⊞' },
  { id: 'pipeline', label: 'AI Pipeline', icon: '⊜' },
  { id: 'reports', label: 'Reports', icon: '◇' },
]

type Props = {
  brand: Brand
  active: NavId
  onNavigate: (id: NavId) => void
}

export function Sidebar({ brand, active, onNavigate }: Props) {
  const resetSession = useAgentSessionStore((s) => s.reset)
  const sessionActive = useAgentSessionStore((s) => !!s.userRequest)
  const [showReonboardModal, setShowReonboardModal] = useState(false)
  const [showHelpModal, setShowHelpModal] = useState(false)
  const initial = primaryName(brand.name).slice(0, 1).toUpperCase() || '◯'

  return (
    <>
      <AnimatePresence>
        {showReonboardModal && (
          <ReonboardModal onClose={() => setShowReonboardModal(false)} />
        )}
        {showHelpModal && (
          <HelpModal onClose={() => setShowHelpModal(false)} />
        )}
      </AnimatePresence>
      <aside className="sticky top-0 flex h-screen flex-col overflow-y-auto overscroll-none bg-bg-card px-5 py-6">
        <button
          type="button"
          onClick={() => onNavigate('settings')}
          aria-label="Open settings"
          title="Open settings"
          className="-mx-1 flex items-center gap-3 rounded-lg px-1 py-1 text-left transition hover:bg-accent-soft/40"
        >
          {brand.logo_url ? (
            <div className="grid h-9 w-9 shrink-0 place-items-center">
              <img
                src={brand.logo_url}
                alt=""
                className="max-h-full max-w-full object-contain"
              />
            </div>
          ) : (
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-fg text-[13px] font-semibold text-white">
              {initial}
            </div>
          )}
          <div className="min-w-0 leading-tight">
            <div className="truncate text-[13px] font-semibold">
              {primaryName(brand.name)}
            </div>
            <div className="truncate text-[11px] text-fg-mute">
              Brand Autopilot
            </div>
          </div>
        </button>

        <nav className="mt-8 flex flex-col gap-1">
          {NAV.map((n) => {
            const isActive = n.id === active
            return (
              <button
                key={n.id}
                type="button"
                onClick={() => onNavigate(n.id)}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-left text-[13px] transition ${
                  isActive
                    ? 'bg-accent-soft font-medium text-fg'
                    : 'text-fg-mute hover:bg-accent-soft/40'
                }`}
              >
                <span
                  className={`w-4 text-center text-[14px] ${
                    isActive ? 'text-accent' : 'text-fg-dim'
                  }`}
                >
                  {n.icon}
                </span>
                <span>{n.label}</span>
              </button>
            )
          })}
        </nav>

        <div className="mt-auto flex flex-col gap-3">
          <button
            onClick={() => {
              resetSession()
              window.scrollTo({ top: 0, behavior: 'smooth' })
            }}
            disabled={!sessionActive}
            className="flex items-center justify-center gap-1.5 rounded-xl bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-4 py-2.5 text-[13px] font-medium text-white shadow-[0_8px_22px_rgba(91,80,230,0.35)] transition hover:brightness-110 disabled:from-accent-dim disabled:to-accent-dim disabled:shadow-none"
          >
            <span className="text-[15px] leading-none">+</span>
            <span>New Campaign</span>
          </button>
          <div className="flex flex-col gap-1.5 px-2 text-[12px] text-fg-mute">
            <button
              onClick={() => setShowHelpModal(true)}
              className="flex items-center gap-2 text-left hover:text-fg"
            >
              <span className="w-3 text-center text-fg-dim">?</span>
              <span>Help</span>
            </button>
            <button
              onClick={() => setShowReonboardModal(true)}
              className="flex items-center gap-2 text-left hover:text-accent"
            >
              <span className="w-3 text-center text-fg-dim">↻</span>
              <span>Re-onboard</span>
            </button>
          </div>
        </div>
      </aside>
    </>
  )
}

function ReonboardModal({ onClose }: { onClose: () => void }) {
  const cancelRef = useRef<HTMLButtonElement>(null)

  // Focus Cancel on mount
  useEffect(() => {
    cancelRef.current?.focus()
  }, [])

  // Esc closes
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  async function handleConfirm() {
    onClose()
    await fetch('/api/onboarding/me', { method: 'DELETE' })
    window.location.reload()
  }

  return createPortal(
    <motion.div
      key="reonboard-backdrop"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <motion.div
        key="reonboard-card"
        initial={{ opacity: 0, scale: 0.95, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 8 }}
        transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
        className="w-full max-w-sm rounded-2xl border border-line bg-bg px-7 py-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold leading-snug">Re-onboard?</h2>
        <p className="mt-2 text-sm leading-relaxed text-fg-mute">
          Delete this brand and re-run onboarding? This wipes the brand row +
          screenshots + competitors.
        </p>
        <div className="mt-6 flex gap-3">
          <button
            ref={cancelRef}
            onClick={onClose}
            className="flex-1 rounded-full border border-line bg-bg-card px-4 py-2 text-sm font-medium transition hover:bg-line/30"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            className="flex-1 rounded-full bg-red-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-600"
          >
            Re-onboard
          </button>
        </div>
      </motion.div>
    </motion.div>,
    document.body,
  )
}

function HelpModal({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return createPortal(
    <motion.div
      key="help-backdrop"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <motion.div
        key="help-card"
        initial={{ opacity: 0, scale: 0.96, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 8 }}
        transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
        className="w-full max-w-md rounded-2xl border border-line bg-bg-card px-6 py-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold leading-snug">
              Brand Autopilot · Quick reference
            </h2>
            <p className="mt-0.5 text-[11px] text-fg-mute">
              v0.1 · built for the Big Berlin Hack 2026
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="grid h-7 w-7 place-items-center rounded-md text-fg-mute hover:bg-bg-soft hover:text-fg"
          >
            ✕
          </button>
        </header>

        <section className="mt-5">
          <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            What you can do
          </div>
          <ul className="mt-2 space-y-1.5 text-[13px] leading-snug">
            <li className="flex items-start gap-2">
              <span className="mt-[3px] text-accent">◫</span>
              <span>
                <strong>Dashboard</strong> — describe what to ship; the agent
                drafts a multi-channel campaign in front of you.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-[3px] text-accent">◴</span>
              <span>
                <strong>Analytics</strong> — market position, growth
                trajectory, competitor radar, AI synthesis.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-[3px] text-accent">◉</span>
              <span>
                <strong>Audience</strong> — pull customers from a CRM,
                propose segments, generate PII-redacted personalized email.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-[3px] text-accent">⊜</span>
              <span>
                <strong>AI Pipeline</strong> — visual builder. Drag nodes,
                drag the right port to draw connections, Delete removes
                selection.
              </span>
            </li>
          </ul>
        </section>

        <section className="mt-5">
          <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Shortcuts
          </div>
          <ul className="mt-2 space-y-1 text-[12.5px] text-fg-mute">
            <li className="flex justify-between">
              <span>Submit prompt on Dashboard</span>
              <kbd className="hairline rounded bg-bg-card px-1.5 py-0.5 text-[10px]">
                Enter
              </kbd>
            </li>
            <li className="flex justify-between">
              <span>Close any drawer / modal</span>
              <kbd className="hairline rounded bg-bg-card px-1.5 py-0.5 text-[10px]">
                Esc
              </kbd>
            </li>
            <li className="flex justify-between">
              <span>Delete selected node / edge in Pipeline</span>
              <kbd className="hairline rounded bg-bg-card px-1.5 py-0.5 text-[10px]">
                Delete
              </kbd>
            </li>
            <li className="flex justify-between">
              <span>Open notifications</span>
              <span>Click ◔ in topbar</span>
            </li>
            <li className="flex justify-between">
              <span>Open settings</span>
              <span>Click ⚙ in topbar</span>
            </li>
          </ul>
        </section>

        <footer className="mt-6 flex justify-end">
          <button
            onClick={onClose}
            className="rounded-xl bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-4 py-2 text-[12.5px] font-medium text-white shadow-[0_4px_14px_rgba(91,80,230,0.3)] hover:brightness-110"
          >
            Got it
          </button>
        </footer>
      </motion.div>
    </motion.div>,
    document.body,
  )
}
