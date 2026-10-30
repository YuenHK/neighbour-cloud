import { Client } from '@proj-airi/server-sdk'

interface Sender {
  sendOrThrow: (payload: {
    type: 'input:text'
    data: { text: string, textRaw: string }
  }) => void
}

export function publishAiriInput(sender: Sender, text: string, textRaw = text): void {
  sender.sendOrThrow({ type: 'input:text', data: { text, textRaw } })
}

export function createAiriClient(url = 'ws://localhost:6121/ws'): Client {
  return new Client({
    name: 'zhiwei-jianbing',
    url,
    possibleEvents: ['input:text', 'output:gen-ai:chat:complete'],
    autoConnect: false,
  })
}
