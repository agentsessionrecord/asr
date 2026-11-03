/** Unofficial ASR download plugin for the authenticated DSH Host. */
import type { Context } from '@deepseek-ai/cordis';
export { formatAgentSession } from './format.js';
export declare const name = "asr-export";
export declare const inject: string[];
export declare const route = "/api/session.asr";
/**
 * Register a route on the Host's authenticated connection and remove it on unload.
 * @param context - Cordis context with the connection and session query services.
 */
export declare function apply(context: Context): void;
