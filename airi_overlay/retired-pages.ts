import type { Plugin } from 'vite'

const retired = new Set([
  '/ui/estate-timer-check.html',
  '/ui/estate-timer-before-check.html',
  '/ui/estate-idle-check-module.js',
  '/ui/estate-idle-before-check.js',
])

export function retiredPages(): Plugin {
  const middleware = (request: { url?: string }, response: { writeHead: (status: number, headers: Record<string, string>) => void, end: () => void }, next: () => void) => {
    if (!retired.has((request.url || '').split('?')[0])) {
      next()
      return
    }
    response.writeHead(307, { 'Location': 'http://127.0.0.1:8000/admin#settings', 'Cache-Control': 'no-store' })
    response.end()
  }
  return {
    name: 'estate-retired-pages',
    configureServer: (server) => {
      server.middlewares.use(middleware)
    },
    configurePreviewServer: (server) => {
      server.middlewares.use(middleware)
    },
  }
}
