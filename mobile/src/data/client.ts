import { ApiError } from './repository';

const BASE = process.env.EXPO_PUBLIC_API_URL ?? 'http://127.0.0.1:8000';

const TIMEOUT_MS = 15_000;
/** Photo uploads on a weak connection legitimately take longer than a read. */
const UPLOAD_TIMEOUT_MS = 60_000;

/** Status 0 marks a request that never got an answer from the server. */
export const isOffline = (error: unknown) => error instanceof ApiError && error.status === 0;

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
  const { query, signal: outer, ...rest } = init;
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(
    () => {
      timedOut = true;
      controller.abort();
    },
    rest.body instanceof FormData ? UPLOAD_TIMEOUT_MS : TIMEOUT_MS,
  );
  const cancel = () => controller.abort();
  outer?.addEventListener('abort', cancel);

  const send = async () => {
    const headers = new Headers(rest.headers);
    const access = getToken();
    if (access) headers.set('Authorization', `Bearer ${access}`);
    if (rest.body && !(rest.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json');
    }
    return fetch(url(path, query), { ...rest, headers, signal: controller.signal });
  };

  try {
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
  } catch (error) {
    if (error instanceof ApiError || outer?.aborted) throw error;
    // The native layer can time out on its own before our timer fires, and
    // its message is a stack trace, so every transport failure is reworded.
    throw new ApiError(
      timedOut || /timed out/i.test(String((error as Error)?.message))
        ? 'The server took too long to respond. Check your connection and try again.'
        : 'Could not reach the server. Check your connection and try again.',
      0,
    );
  } finally {
    clearTimeout(timer);
    outer?.removeEventListener('abort', cancel);
  }
}
