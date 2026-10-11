import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { AuthService } from '../core/auth';
import { DEMO_CREDENTIALS } from '../core/config';
import { Icon } from '../layout/icon';

@Component({
  selector: 'app-login',
  imports: [FormsModule, Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="grid min-h-screen place-items-center px-4 py-10">
      <div class="w-full max-w-sm">
        <div class="mb-8 flex flex-col items-center text-center">
          <img src="favicon.svg" alt="" class="h-12 w-12" />
          <h1 class="mt-4 text-2xl font-semibold">AgentHub</h1>
          <p class="mt-1 text-sm text-text-muted">One gateway for every agent, tool and model call.</p>
        </div>

        <form class="card space-y-4 p-6" (ngSubmit)="submit()">
          <div>
            <label class="label" for="username">Username</label>
            <input id="username" name="username" class="input" autocomplete="username" [(ngModel)]="username" />
          </div>
          <div>
            <label class="label" for="password">Password</label>
            <input
              id="password"
              name="password"
              type="password"
              class="input"
              autocomplete="current-password"
              [(ngModel)]="password"
            />
          </div>
          @if (error()) {
            <p class="rounded-xl bg-deny/10 px-3 py-2 text-sm text-deny" role="alert">{{ error() }}</p>
          }
          <button type="submit" class="btn-primary w-full" [disabled]="busy()">
            {{ busy() ? 'Signing in…' : 'Sign in' }}
            <app-icon name="arrow" />
          </button>
        </form>

        <div class="mt-4 rounded-2xl border border-border-soft bg-bg-raised p-4 text-xs leading-relaxed text-text-muted">
          <p class="mb-1 flex items-center gap-1.5 font-medium text-text-secondary">
            <app-icon name="sparkles" cls="h-3.5 w-3.5 text-accent-soft" /> Public demo
          </p>
          The demo account (<span class="font-mono text-text-secondary">demo / demo</span>) is a read-only
          <span class="font-mono">viewer</span>. It can run the Research Crew and try tools, but can't change the registry
          or policies. The demo resets on every restart. The first request can take ~30 s while the free server wakes up.
        </div>
      </div>
    </div>
  `,
})
export class Login {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected username = DEMO_CREDENTIALS.username;
  protected password = DEMO_CREDENTIALS.password;
  protected readonly busy = signal(false);
  protected readonly error = signal('');

  constructor() {
    if (this.auth.isLoggedIn()) this.router.navigate(['/overview']);
  }

  async submit(): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      await this.auth.login(this.username.trim(), this.password);
      await this.router.navigate(['/overview']);
    } catch (err) {
      const status = err instanceof HttpErrorResponse ? err.status : 0;
      this.error.set(
        status === 401
          ? 'Wrong username or password.'
          : status === 0
            ? "Can't reach the API. It may be waking up; try again in a few seconds."
            : `Sign-in failed (HTTP ${status}).`,
      );
    } finally {
      this.busy.set(false);
    }
  }
}
