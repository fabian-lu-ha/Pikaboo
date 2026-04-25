import { useState, Fragment } from 'react'
import { motion } from 'motion/react'
import { useOnboardingStore } from '../stores/onboardingStore'
import { StepBasics } from './StepBasics'
import { StepReferences } from './StepReferences'
import { StepReading } from './StepReading'
import { StepReview } from './StepReview'

type Stage = 'basics' | 'references' | 'reading' | 'review'

export function OnboardingFlow({ onComplete }: { onComplete: () => void }) {
  const [stage, setStage] = useState<Stage>('basics')
  const error = useOnboardingStore((s) => s.error)
  const reset = useOnboardingStore((s) => s.reset)

  function startOver() {
    reset()
    setStage('basics')
  }

  const STAGE_ORDER: Stage[] = ['basics', 'references', 'reading', 'review']
  const canBack = STAGE_ORDER.indexOf(stage) > 0 && stage !== 'reading'

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b border-line bg-bg-card px-10 py-4">
        <div className="flex items-center gap-3">
          {canBack && (
            <button
              onClick={() =>
                setStage(STAGE_ORDER[STAGE_ORDER.indexOf(stage) - 1])
              }
              className="grid h-9 w-9 place-items-center rounded-full border border-line text-fg-mute transition hover:border-accent hover:text-accent"
              title="Back"
            >
              ←
            </button>
          )}
          <span className="grid h-9 w-9 place-items-center rounded-full bg-accent text-[11px] font-semibold tracking-wider text-white">
            BA
          </span>
          <div>
            <div className="text-sm font-semibold leading-tight tracking-tight">
              Brand Autopilot
            </div>
            <div className="text-[11px] text-fg-mute">Onboarding</div>
          </div>
        </div>
        <Stepper stage={stage} />
      </header>

      <motion.main
        key={stage}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="flex-1"
      >
        {stage === 'basics' && (
          <StepBasics onAdvance={() => setStage('references')} />
        )}
        {stage === 'references' && (
          <StepReferences
            onAdvance={() => setStage('reading')}
            onSkip={() => setStage('reading')}
          />
        )}
        {stage === 'reading' && (
          <StepReading onAdvance={() => setStage('review')} />
        )}
        {stage === 'review' && <StepReview onComplete={onComplete} />}
      </motion.main>

      {error && (
        <div className="mx-10 mb-4 flex items-center justify-between gap-4 rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-xs text-danger">
          <span>{error}</span>
          <button
            onClick={startOver}
            className="rounded-full border border-danger/50 px-3 py-1 font-medium text-danger transition hover:bg-danger hover:text-white"
          >
            Start over
          </button>
        </div>
      )}
    </div>
  )
}

function Stepper({ stage }: { stage: Stage }) {
  const steps: { id: Stage; num: string; label: string }[] = [
    { id: 'basics', num: '01', label: 'Basics' },
    { id: 'references', num: '02', label: 'References' },
    { id: 'reading', num: '03', label: 'Reading you' },
    { id: 'review', num: '04', label: 'Review' },
  ]
  const currentIndex = steps.findIndex((s) => s.id === stage)
  return (
    <ol className="flex items-center gap-2">
      {steps.map((s, i) => {
        const done = i < currentIndex
        const active = s.id === stage
        return (
          <Fragment key={s.id}>
            <li className="flex items-center gap-2.5 text-xs">
              <span
                className={`grid h-6 w-6 place-items-center rounded-full text-[10px] font-semibold tabular-nums ${
                  active
                    ? 'bg-accent text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)]'
                    : done
                      ? 'bg-bg-soft text-fg'
                      : 'border border-line text-fg-dim'
                }`}
              >
                {done ? '✓' : s.num}
              </span>
              <span
                className={
                  active
                    ? 'font-medium text-fg'
                    : done
                      ? 'text-fg-mute'
                      : 'text-fg-dim'
                }
              >
                {s.label}
              </span>
            </li>
            {i < steps.length - 1 && (
              <span
                className={`h-px w-8 ${
                  i < currentIndex ? 'bg-fg-mute/40' : 'bg-line'
                }`}
              />
            )}
          </Fragment>
        )
      })}
    </ol>
  )
}
