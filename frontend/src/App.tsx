import { useCallback, useEffect, useState } from 'react'
import { useEventStream } from './events/useEventStream'
import { OnboardingFlow, type Stage } from './onboarding/OnboardingFlow'
import { Dashboard, type Brand } from './components/Dashboard'
// Side-effect import: registers research.* listeners on the bus before the
// SSE stream starts dispatching events.
import './stores/researchStore'
import './stores/competitorIntelStore'
import './stores/geoStore'

type PartialBrand = {
  id: string
  name: string
  url: string | null
  identity: Record<string, unknown> | null
  voice_profile: Record<string, unknown> | null
  [key: string]: unknown
}

/** Derive the wizard stage from whatever fields the DB brand already has. */
function deriveInitialStage(brand: PartialBrand): Stage {
  const hasIdentity = brand.identity && Object.keys(brand.identity).length > 0
  const hasVoice = brand.voice_profile && Object.keys(brand.voice_profile).length > 0

  // Both identity and voice populated → past the reading step, go to review
  if (hasIdentity && hasVoice) return 'review'
  // Either one set → scraping/distilling happened, land on reading
  if (hasIdentity || hasVoice) return 'reading'
  // Brand exists (basics submitted) but nothing distilled yet → references
  return 'references'
}

export default function App() {
  useEventStream('/api/events')

  type AppState =
    | { status: 'loading' }
    | { status: 'onboarding'; brand: PartialBrand | null; initialStage: Stage }
    | { status: 'dashboard'; brand: Brand }

  const [appState, setAppState] = useState<AppState>({ status: 'loading' })

  const refresh = useCallback(async () => {
    // First check for a fully-onboarded brand — if found, go straight to dashboard.
    const meRes = await fetch('/api/onboarding/me')
    const meData = (await meRes.json()) as { brand: Brand | null }
    if (meData.brand) {
      setAppState({ status: 'dashboard', brand: meData.brand })
      return
    }

    // No fully-onboarded brand — check for a partial brand to resume the wizard.
    const statusRes = await fetch('/api/onboarding/status')
    const statusData = (await statusRes.json()) as { brand: PartialBrand | null }
    const partial = statusData.brand

    if (!partial) {
      setAppState({ status: 'onboarding', brand: null, initialStage: 'basics' })
      return
    }

    // Partially onboarded — resume wizard at derived step
    setAppState({
      status: 'onboarding',
      brand: partial,
      initialStage: deriveInitialStage(partial),
    })
  }, [])

  useEffect(() => {
    refresh().catch(() =>
      setAppState({ status: 'onboarding', brand: null, initialStage: 'basics' }),
    )
  }, [refresh])

  if (appState.status === 'loading') {
    return (
      <div className="grid h-screen place-items-center font-mono text-xs uppercase tracking-[0.22em] text-fg-mute">
        loading
      </div>
    )
  }

  if (appState.status === 'onboarding') {
    return (
      <OnboardingFlow
        onComplete={() => refresh()}
        initialStage={appState.initialStage}
        resumeBrand={appState.brand}
      />
    )
  }

  return <Dashboard brand={appState.brand} />
}
