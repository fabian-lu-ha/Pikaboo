import { useState, type FormEvent } from 'react'
import { useAgentStore } from '../stores/agentStore'
import { bus } from '../events/bus'

export function ChatBox() {
  const [draft, setDraft] = useState('')
  const steps = useAgentStore((s) => s.steps)

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const text = draft.trim()
    if (!text) return
    bus.emit('chat.submitted', { text })
    setDraft('')
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-white/10">
      <div className="flex-1 overflow-auto p-4">
        {steps.length === 0 ? (
          <p className="opacity-60">Ask anything. The agent will work in front of you.</p>
        ) : (
          <ul className="space-y-2">
            {steps.map((s) => (
              <li key={s.id} className="text-sm opacity-80">
                <span className="opacity-50">{s.at}</span> · {s.label}
              </li>
            ))}
          </ul>
        )}
      </div>
      <form className="flex gap-2 border-t border-white/10 p-3" onSubmit={handleSubmit}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="What should I post this week?"
          className="flex-1 rounded-md bg-white/5 px-3 py-2 outline-none placeholder:opacity-50"
        />
        <button type="submit" className="rounded-md bg-white/10 px-4 py-2 hover:bg-white/20">
          Send
        </button>
      </form>
    </div>
  )
}
