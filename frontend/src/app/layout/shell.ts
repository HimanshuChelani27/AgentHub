import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { api } from '../core/api';
import { AuthService } from '../core/auth';
import { LlmProvider } from '../core/models';
import { Icon } from './icon';

const NAV = [
  { path: '/overview', label: 'Overview', icon: 'overview' },
  { path: '/playground', label: 'Playground', icon: 'play' },
  { path: '/agents', label: 'Agents', icon: 'agents' },
  { path: '/servers', label: 'MCP servers', icon: 'server' },
  { path: '/traces', label: 'Traces', icon: 'trace' },
  { path: '/audit', label: 'Audit log', icon: 'audit' },
  { path: '/policies', label: 'Policies', icon: 'shield' },
];

@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex min-h-screen">
      <!-- Sidebar -->
      <aside
        class="fixed inset-y-0 left-0 z-40 w-60 -translate-x-full border-r border-border-soft bg-bg-raised transition-transform md:translate-x-0"
        [class.translate-x-0]="menuOpen()"
      >
        <div class="flex h-16 items-center gap-2.5 px-5">
          <img src="favicon.svg" alt="" class="h-8 w-8" />
          <div>
            <p class="text-sm font-semibold text-text-primary">AgentHub</p>
            <p class="text-[11px] text-text-muted">MCP gateway & registry</p>
          </div>
        </div>
        <nav class="mt-2 space-y-0.5 px-3" aria-label="Main">
          @for (item of nav; track item.path) {
            <a
              [routerLink]="item.path"
              routerLinkActive="!bg-surface-2 !text-text-primary [&>app-icon]:!text-accent-soft"
              (click)="menuOpen.set(false)"
              class="flex items-center gap-3 rounded-xl px-3 py-2 text-sm text-text-secondary transition hover:bg-surface hover:text-text-primary"
            >
              <app-icon [name]="item.icon" class="text-text-muted" />
              {{ item.label }}
            </a>
          }
        </nav>
        <div class="absolute inset-x-0 bottom-0 space-y-3 border-t border-border-soft p-4">
          <a
            href="https://github.com/HimanshuChelani27/agenthub"
            target="_blank"
            rel="noopener"
            class="flex items-center gap-2 text-xs text-text-muted hover:text-text-primary"
          >
            <app-icon name="github" cls="h-3.5 w-3.5" /> Source on GitHub
          </a>
          <div class="flex items-center justify-between">
            <div class="min-w-0">
              <p class="truncate text-sm text-text-primary">{{ auth.user()?.username }}</p>
              <p class="font-mono text-[11px] text-text-muted">{{ auth.user()?.role }}</p>
            </div>
            <button
              (click)="auth.logout()"
              class="grid h-8 w-8 place-items-center rounded-full text-text-muted hover:bg-surface hover:text-text-primary"
              aria-label="Sign out"
            >
              <app-icon name="logout" />
            </button>
          </div>
        </div>
      </aside>
      @if (menuOpen()) {
        <div class="fixed inset-0 z-30 bg-black/60 md:hidden" (click)="menuOpen.set(false)"></div>
      }

      <!-- Main -->
      <div class="min-w-0 flex-1 md:pl-60">
        <header
          class="sticky top-0 z-20 flex h-14 items-center justify-between gap-3 border-b border-border-soft bg-bg/80 px-4 backdrop-blur sm:px-6"
        >
          <button
            class="grid h-9 w-9 place-items-center rounded-full border border-border md:hidden"
            (click)="menuOpen.set(true)"
            aria-label="Open menu"
          >
            <app-icon name="menu" />
          </button>
          <p class="hidden text-xs text-text-muted sm:block">
            Every tool call, LLM call and hand-off goes through the gateway: authorised, PII-masked, audited.
          </p>
          @if (provider.value(); as p) {
            <span
              class="inline-flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-[11px]"
              [class]="p.mode === 'live' ? 'border-ok/40 text-ok' : 'border-border text-text-muted'"
              [title]="p.mode === 'live' ? 'Agents use a real LLM' : 'No LLM key configured: agent text is scripted; tools, policy and masking are real'"
            >
              <span class="h-1.5 w-1.5 rounded-full" [class]="p.mode === 'live' ? 'bg-ok' : 'bg-text-muted'"></span>
              LLM: {{ p.mode === 'live' ? p.provider + ' · ' + p.model : 'scripted mode' }}
            </span>
          }
        </header>
        <main class="mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
          <router-outlet />
        </main>
      </div>
    </div>
  `,
})
export class Shell {
  protected readonly auth = inject(AuthService);
  protected readonly nav = NAV;
  protected readonly menuOpen = signal(false);
  protected readonly provider = httpResource<LlmProvider>(() => api('/gateway/llm/provider'));
}
