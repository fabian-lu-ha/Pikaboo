import { useEffect } from 'react'
import { bus, type AgentEvents } from './bus'

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
    return () => source.close()
  }, [url])
}
