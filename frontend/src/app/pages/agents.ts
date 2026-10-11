import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, signal } from '@angular/core';

import { api } from '../core/api';
import { json } from '../core/format';
import { Agent } from '../core/models';
import { Icon } from '../layout/icon';

@Component({
  selector: 'app-agents',
  imports: [Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h1 class="page-title">Agents</h1>
    <p class="page-sub max-w-2xl">
      Every agent is registered with an A2A-style Agent Card: who owns it, what it can do, and where to send it tasks.
      Unregistered or inactive agents can't receive hand-offs.
    </p>

    <div class="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      @for (a of agents.value() ?? []; track a.id) {
        <article class="card flex flex-col p-5">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <h2 class="truncate text-base font-medium">{{ a.name }}</h2>
              <p class="font-mono text-[11px] text-text-muted">{{ a.slug }} · v{{ a.version }}</p>
            </div>
            <span
              class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[11px]"
              [class]="a.status === 'active' ? 'bg-ok/10 text-ok' : 'bg-surface-2 text-text-muted'"
            >
              <span class="h-1.5 w-1.5 rounded-full" [class]="a.status === 'active' ? 'bg-ok' : 'bg-text-muted'"></span>
              {{ a.status }}
            </span>
          </div>
          <p class="mt-3 text-sm leading-relaxed">{{ a.description }}</p>
          <div class="mt-4 flex flex-wrap gap-1.5">
            @for (s of a.skills; track s.id) {
              <span class="chip" [title]="s.description ?? ''">{{ s.name }}</span>
            }
          </div>
          <div class="mt-auto flex items-center justify-between gap-3 border-t border-border-soft pt-4 mt-5 text-xs text-text-muted">
            <span>{{ a.framework }} · {{ a.owner }}</span>
            <button class="text-accent-soft hover:underline" (click)="open(a)">Agent Card</button>
          </div>
        </article>
      } @empty {
        @if (agents.isLoading()) {
          <p class="text-sm text-text-muted">Loading…</p>
        } @else {
          <p class="text-sm text-text-muted">No agents registered.</p>
        }
      }
    </div>

    @if (selected(); as a) {
      <div class="fixed inset-0 z-50 flex justify-end bg-black/60" (click)="selected.set(null)">
        <aside
          class="h-full w-full max-w-xl overflow-y-auto border-l border-border bg-bg-raised p-5 sm:p-6"
          role="dialog"
          aria-modal="true"
          [attr.aria-label]="a.name + ' agent card'"
          (click)="$event.stopPropagation()"
        >
          <div class="flex items-start justify-between gap-3">
            <div>
              <h2 class="text-lg font-semibold">{{ a.name }}</h2>
              <p class="mt-0.5 font-mono text-xs text-text-muted">GET /agents/{{ a.slug }}/card</p>
            </div>
            <button
              class="grid h-8 w-8 place-items-center rounded-full hover:bg-surface"
              (click)="selected.set(null)"
              aria-label="Close"
            >
              <app-icon name="x" />
            </button>
          </div>
          <p class="mt-3 text-sm text-text-muted">
            The machine-readable card other agents and registries use to discover this agent.
          </p>
          <pre
            class="mt-4 overflow-x-auto rounded-xl border border-border-soft bg-bg p-4 font-mono text-xs leading-relaxed text-text-secondary whitespace-pre-wrap break-words"
          >{{ card.value() ? json(card.value()) : card.isLoading() ? 'Loading…' : 'Could not load the card.' }}</pre>
        </aside>
      </div>
    }
  `,
  host: { '(document:keydown.escape)': 'selected.set(null)' },
})
export class Agents {
  protected readonly agents = httpResource<Agent[]>(() => api('/agents'));
  protected readonly selected = signal<Agent | null>(null);
  protected readonly card = httpResource<unknown>(() => {
    const a = this.selected();
    return a ? api(`/agents/${a.slug}/card`) : undefined;
  });
  protected readonly json = json;

  protected open(a: Agent): void {
    this.selected.set(a);
  }
}
