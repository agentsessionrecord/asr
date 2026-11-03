/** Unofficial ASR download plugin for the authenticated DSH Host. */
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-session-query'
import type {} from '@deepseek-ai/dsh-client-connection'
import { SessionId } from '@deepseek-ai/dsh-session'
import { formatAgentSession } from './format.js'

export { formatAgentSession } from './format.js'
export const name = 'asr-export'
export const inject = ['connection', 'sessionQuery']
export const route = '/api/session.asr'

/**
 * Register a route on the Host's authenticated connection and remove it on unload.
 * @param context - Cordis context with the connection and session query services.
 */
export function apply(context: Context): void {
  context.effect(() => context.connection.fetch.register({
    path: route,
    methods: ['GET', 'HEAD'],
    requestBody: 'buffered',
    fetch: request => exportResponse(context, request),
  }))
}

async function exportResponse(context: Context, request: Request): Promise<Response> {
  const id = new URL(request.url).searchParams.get('sessionId')
  if (!id) return new Response('sessionId is required', { status: 400 })
  try {
    request.signal.throwIfAborted()
    const snapshot = await context.sessionQuery.readSession(SessionId(id))
    request.signal.throwIfAborted()
    const text = formatAgentSession(snapshot.session, snapshot.events, snapshot.inheritedEventCount)
    return new Response(request.method === 'HEAD' ? null : text, {
      headers: {
        'content-type': 'application/vnd.agent-session+jsonl; charset=utf-8',
        'content-disposition': 'attachment; filename="session.asr.jsonl"',
        'cache-control': 'no-store',
      },
    })
  } catch (error) {
    request.signal.throwIfAborted()
    const absent = error instanceof Error && 'code' in error
      && error.code === 'SESSION_QUERY_SESSION_NOT_FOUND'
    return new Response(absent ? 'session not found' : 'session export failed', { status: absent ? 404 : 500 })
  }
}
