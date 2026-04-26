import { useAudienceStore } from '../../stores/audienceStore'
import { PIIShield } from './PIIShield'

export function AudienceActivityFeed() {
  const redactionLog = useAudienceStore((s) => s.redactionLog)
  const lastImport = useAudienceStore((s) => s.lastImport)
  const personalizedCount = useAudienceStore((s) => s.personalizedCount)

  const hasActivity =
    redactionLog.length > 0 || !!lastImport || personalizedCount > 0

  return (
    <div className="rounded-2xl border border-line bg-bg-card p-5 shadow-[0_2px_10px_rgba(20,20,40,0.03)]">
      <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
        Audience activity
      </div>
      {!hasActivity ? (
        <p className="mt-3 text-xs text-fg-mute">
          The agent will log redactions, imports, and personalized sends here.
        </p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2.5 text-xs">
          {lastImport && (
            <li className="flex items-baseline justify-between gap-2">
              <span className="text-fg">
                imported{' '}
                <span className="font-medium">
                  {lastImport.customer_count}
                </span>{' '}
                customers ·{' '}
                <span className="font-medium">{lastImport.product_count}</span>{' '}
                products ·{' '}
                <span className="font-medium">{lastImport.event_count}</span>{' '}
                events
              </span>
            </li>
          )}
          {personalizedCount > 0 && (
            <li className="flex items-baseline justify-between gap-2">
              <span className="text-fg">
                personalized{' '}
                <span className="font-medium">{personalizedCount}</span>{' '}
                {personalizedCount === 1 ? 'message' : 'messages'}
              </span>
            </li>
          )}
          {redactionLog.length > 0 && (
            <li>
              <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                PII shield
              </div>
              <ul className="mt-2 flex flex-col gap-1.5">
                {redactionLog.map((r) => (
                  <li
                    key={r.id}
                    className="flex items-center justify-between gap-2"
                  >
                    <PIIShield count={r.entity_count} types={r.types} />
                    <span className="text-[10px] tabular-nums text-fg-dim">
                      {r.at}
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
