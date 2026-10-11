import { HttpClient, HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, firstValueFrom, throwError } from 'rxjs';

import { API_URL } from './config';
import { Role } from './models';

interface Session {
  token: string;
  username: string;
  role: Role;
}

const STORAGE_KEY = 'agenthub.session';

// Storage can be unavailable (private mode, blocked site data), so every access is guarded.
function readSession(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

function writeSession(session: Session | null): void {
  try {
    if (session) localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* keep the in-memory session only */
  }
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private readonly session = signal<Session | null>(readSession());

  readonly user = this.session.asReadonly();
  readonly isLoggedIn = computed(() => this.session() !== null);
  readonly canEdit = computed(() => ['admin', 'developer'].includes(this.session()?.role ?? ''));
  readonly isAdmin = computed(() => this.session()?.role === 'admin');

  get token(): string | null {
    return this.session()?.token ?? null;
  }

  async login(username: string, password: string): Promise<void> {
    const res = await firstValueFrom(
      this.http.post<{ access_token: string; username: string; role: Role }>(`${API_URL}/auth/login`, {
        username,
        password,
      }),
    );
    const session = { token: res.access_token, username: res.username, role: res.role };
    this.session.set(session);
    writeSession(session);
  }

  logout(redirect = true): void {
    this.session.set(null);
    writeSession(null);
    if (redirect) this.router.navigate(['/login']);
  }
}

/** Adds the bearer token to API calls and signs out when it's rejected. */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const isApi = req.url.startsWith(API_URL);
  const token = auth.token;
  const request = isApi && token ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : req;
  return next(request).pipe(
    catchError((err: HttpErrorResponse) => {
      if (isApi && err.status === 401 && !req.url.endsWith('/auth/login')) auth.logout();
      return throwError(() => err);
    }),
  );
};

export const authGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return auth.isLoggedIn() ? true : inject(Router).createUrlTree(['/login']);
};
