import { useEffect } from 'react'
import { bus, type AgentEvents } from './bus'
import { reconcileFromStatus } from '../stores/onboardingStore'

type ServerEvent = {
  type: keyof AgentEvents
  payload: AgentEvents[keyof AgentEvents]
}

export function useEventStream(url: string) {
  useEffect(() => {
    const source = new EventSource(url)

    source.onmessage = (msg) => {
      try {
        const { type, payload } = JSON.parse(msg.data) as ServerEvent
        bus.emit(type, payload as never)
      } catch {
        /* dropped malformed event */
      }
    }

    // When the SSE connection drops and the browser is about to reconnect,
    // re-fetch the brand status snapshot so any events that fired during the
    // gap are recovered from DB rather than being silently lost.
    source.onerror = () => {
      reconcileFromStatus().catch(() => {/* non-fatal */})
    }

    return () => source.close()
  }, [url])
}
