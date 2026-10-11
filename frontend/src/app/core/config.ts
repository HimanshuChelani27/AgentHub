declare global {
  interface Window {
    __AGENTHUB__?: { apiUrl?: string };
  }
}

/** Backend base URL, from public/env.js (written at deploy time). */
export const API_URL = (window.__AGENTHUB__?.apiUrl ?? 'http://localhost:8000').replace(/\/$/, '');

export const DEMO_CREDENTIALS = { username: 'demo', password: 'demo' };
