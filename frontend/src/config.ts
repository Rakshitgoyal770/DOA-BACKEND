/**
 * Runtime configuration.
 *
 * VITE_API_BASE_URL points at the DAO Governance Intelligence API (the FastAPI
 * backend). Copy `.env.example` to `.env.local` to change it.
 */
const raw = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8000';

export const API_BASE_URL = raw.replace(/\/+$/, '');

/** Ordinary reads: fail fast. */
export const REQUEST_TIMEOUT_MS = 20_000;

/** /chat runs an LLM agent plus a writer and may fall through several providers. */
export const CHAT_TIMEOUT_MS = 120_000;
