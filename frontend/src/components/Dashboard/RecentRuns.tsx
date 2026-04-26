import { relativeTime } from '../../lib/brandName'
import { RunRow } from './RunRow'
import { useRecentRuns } from './useRecentRuns'
import { useAgentSessionStore } from '../../stores/agentSessionStore'
import type { Brand } from './types'

export function RecentRuns({ brand }: { brand: Brand }) {
  const entries = useRecentRuns(brand)
  const restore = useAgentSessionStore((s) => s.restore)
  if (entries.length === 0) return null
  return (
    <section className="mx-auto mt-12 w-full max-w-2xl">
      <h2 className="px-1 text-[12px] font-medium text-fg-mute">Recent Runs</h2>
      <ul className="panel mt-3 flex flex-col divide-y divide-[rgba(20,20,40,0.04)]">
        {entries.map((e) => (
          <RunRow
            key={e.id}
            tint={e.tint}
            title={e.title}
            sub={e.sub}
            ago={relativeTime(e.ts)}
            onClick={() => {
              void restore(e.id)
              window.scrollTo({ top: 0, behavior: 'smooth' })
            }}
          />
        ))}
      </ul>
    </section>
  )
}
