import { bus } from '../events/bus'

bus.on('chat.submitted', async ({ text }) => {
  await fetch('/api/chat', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ text }),
  })
})
