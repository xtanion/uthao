// Imported rather than left to the global: uploads send expo-file-system Files,
// which only expo/fetch can serialise, and EXPO_PUBLIC_USE_RN_FETCH swaps the
// global back to React Native's fetch without touching this import.
import { fetch } from 'expo/fetch';
import { ApiError } from './repository';

const BASE = process.env.EXPO_PUBLIC_API_URL ?? 'http://127.0.0.1:8000';

export type Tokens = { access_token: string; refresh_token: string };

let tokens: Tokens | null = null;
let listener: ((next: Tokens | null) => void) | null = null;
let renewal: Promise<boolean> | null = null;

export const setTokens = (next: Tokens | null) => {
  tokens = next;
  listener?.(next);
};

export const getToken = () => tokens?.access_token ?? null;

/** Called whenever the pair changes, including when a refresh replaces it or
 *  fails and clears it, so storage and the signed-in user stay in step. */
export const onTokensChanged = (fn: (next: Tokens | null) => void) => {
  listener = fn;
};

const url = (path: string, query?: Record<string, unknown>) => {
  const built = new URL(path.replace(/^\//, ''), BASE.endsWith('/') ? BASE : `${BASE}/`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null) built.searchParams.set(key, String(value));
  }
  return built.toString();
};

/**
 * One refresh at a time. Several requests can fail together when a token
 * expires; without this they would each spend the refresh token, and whichever
 * lost the race would sign the user out.
 */
async function renew(): Promise<boolean> {
  const current = tokens?.refresh_token;
  if (!current) return false;
  renewal ??= (async () => {
    try {
      const response = await fetch(url('/auth/token/refresh'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: current }),
      });
      if (!response.ok) {
        // The refresh token is spent or revoked; nothing to do but sign in.
        setTokens(null);
        return false;
      }
      const payload = await response.json();
      setTokens({
        access_token: payload.access_token,
        refresh_token: payload.refresh_token,
      });
      return true;
    } catch {
      // A network failure is not an expired session, so the tokens stay.
      return false;
    } finally {
      renewal = null;
    }
  })();
  return renewal;
}

/** The backend returns {detail} for errors; it is written for a person, so it
 *  is surfaced verbatim rather than replaced with a generic message. */
export async function request<T>(
  path: string,
  init: RequestInit & { query?: Record<string, unknown> } = {},
): Promise<T> {
  const { query, ...rest } = init;

  const send = async () => {
    const headers = new Headers(rest.headers);
    const access = getToken();
    if (access) headers.set('Authorization', `Bearer ${access}`);
    if (rest.body && !(rest.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json');
    }
    return fetch(url(path, query), { ...rest, headers });
  };

  let response = await send();
  if (response.status === 401 && !path.startsWith('/auth/') && (await renew())) {
    response = await send();
  }

  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new ApiError(payload?.detail ?? 'Something went wrong', response.status);
  }
  return payload as T;
}
