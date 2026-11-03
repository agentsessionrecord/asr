/** Native ASR projection of a detached, validated Session log observation. */
import type { SessionEvent, SessionHeader } from '@deepseek-ai/dsh-session';
/**
 * Export original events in source order without loading an Agent or provider.
 * @param session - Header from the same query observation as the events.
 * @param events - Complete validated logical log, including inherited events.
 * @param inheritedEventCount - Number of copied prefix events to exclude from credit.
 * @returns One complete ASR JSON Lines stream.
 */
export declare function formatAgentSession(session: SessionHeader, events: readonly SessionEvent[], inheritedEventCount: number): string;
