import { HttpClient } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, effect, inject, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { api } from '../core/api';
import { auditTarget, formatMs, highlightText, json, parseDate, timeAgo } from '../core/format';
import { AuditEvent } from '../core/models';

const PAGE = 50;

@Component({
  selector: 'app-audit',
  imports: [FormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h1 class="page-title">Audit log</h1>
    <p class="page-sub">Every tool call, model call and hand-off: who, what, the decision, and what was masked.</p>

    <div class="mt-6 flex flex-wrap gap-3">
      <div>
        <label class="label" for="f-decision">Decision</label>
        <select id="f-decision" class="input !w-40" [ngModel]="decision()" (ngModelChange)="decision.set($event)">
          <option value="">All</option>
          <option value="allowed">allowed</option>
          <option value="denied">denied</option>
          <option value="error">error</option>
          <option value="rate_limited">rate_limited</option>
        </select>
      </div>
      <div>
        <label class="label" for="f-kind">Kind</label>
        <select id="f-kind" class="input !w-40" [ngModel]="kind()" (ngModelChange)="kind.set($event)">
          <option value="">All</option>
          <option value="tool">tool</option>
          <option value="llm">llm</option>
          <option value="a2a">a2a</option>
        </select>
      </div>
    </div>

    <section class="card mt-4 overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full min-w-[760px]">
          <thead>
            <tr>
              <th class="table-head w-16">#</th>
              <th class="table-head">When</th>
              <th class="table-head">Who</th>
              <th class="table-head">What</th>
              <th class="table-head">Decision</th>
              <th class="table-head text-right">PII</th>
              <th class="table-head text-right">Latency</th>
            </tr>
          </thead>
          <tbody>
            @for (e of rows(); track e.id) {
              <tr class="cursor-pointer transition hover:bg-surface-2" [class.bg-surface-2]="open() === e.id" (click)="toggle(e.id)">
                <td class="table-cell font-mono text-xs text-text-muted">{{ e.id }}</td>
                <td class="table-cell whitespace-nowrap text-text-muted" [title]="local(e.ts)">{{ ago(e.ts) }}</td>
                <td class="table-cell">
                  <span class="font-mono text-xs text-text-primary">{{ e.principal }}</span>
                  <span class="ml-1.5 font-mono text-[11px] text-text-muted">{{ e.role }}</span>
                </td>
                <td class="table-cell font-mono text-xs text-text-primary">{{ what(e) }}</td>
                <td class="table-cell"><span [class]="'badge-' + e.decision">{{ e.decision }}</span></td>
                <td class="table-cell text-right tabular-nums">{{ e.pii_masked || '–' }}</td>
                <td class="table-cell text-right tabular-nums text-text-muted">{{ ms(e.latency_ms) }}</td>
              </tr>
              @if (open() === e.id) {
                <tr>
                  <td colspan="7" class="border-b border-border-soft bg-bg-raised px-4 py-4">
                    <div class="grid gap-4 md:grid-cols-[14rem_minmax(0,1fr)]">
                      <dl class="space-y-2 text-xs">
                        <div><dt class="text-text-muted">Reason</dt><dd class="text-text-primary">{{ e.reason || '–' }}</dd></div>
                        <div><dt class="text-text-muted">Time</dt><dd>{{ local(e.ts) }}</dd></div>
                        @if (e.run_id) {
                          <div>
                            <dt class="text-text-muted">Run</dt>
                            <dd><a [routerLink]="['/traces', e.run_id]" class="font-mono text-accent-soft hover:underline">{{ e.run_id.slice(0, 12) }} →</a></dd>
                          </div>
                        }
                      </dl>
                      <pre class="overflow-x-auto rounded-lg border border-border-soft bg-bg p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words" [innerHTML]="detailHtml(e)"></pre>
                    </div>
                  </td>
                </tr>
              }
            } @empty {
              <tr>
                <td colspan="7" class="table-cell py-10 text-center text-text-muted">
                  {{ loading() ? 'Loading…' : 'No matching events.' }}
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
      @if (error()) {
        <p class="border-t border-border-soft px-4 py-3 text-sm text-deny">{{ error() }}</p>
      }
      @if (hasMore()) {
        <div class="border-t border-border-soft p-3 text-center">
          <button class="btn-ghost" [disabled]="loading()" (click)="load(true)">
            {{ loading() ? 'Loading…' : 'Load older events' }}
          </button>
        </div>
      }
    </section>
  `,
})
export class Audit {
  private readonly http = inject(HttpClient);

  protected readonly decision = signal('');
  protected readonly kind = signal('');
  protected readonly rows = signal<AuditEvent[]>([]);
  protected readonly loading = signal(false);
  protected readonly hasMore = signal(false);
  protected readonly error = signal('');
  protected readonly open = signal<number | null>(null);
  protected readonly ago = timeAgo;
  protected readonly ms = formatMs;
  protected readonly what = auditTarget;

  constructor() {
    // Reload from the top whenever a filter changes.
    effect(() => {
      this.decision();
      this.kind();
      untracked(() => this.load(false));
    });
  }

  protected async load(more: boolean): Promise<void> {
    const params = new URLSearchParams({ limit: String(PAGE) });
    if (this.decision()) params.set('decision', this.decision());
    if (this.kind()) params.set('kind', this.kind());
    const last = this.rows().at(-1);
    if (more && last) params.set('before_id', String(last.id));

    this.loading.set(true);
    this.error.set('');
    try {
      const page = await firstValueFrom(this.http.get<AuditEvent[]>(api(`/audit?${params}`)));
      this.rows.update((rows) => (more ? [...rows, ...page] : page));
      this.hasMore.set(page.length === PAGE);
    } catch {
      this.error.set("Couldn't load audit events.");
    } finally {
      this.loading.set(false);
    }
  }

  protected toggle(id: number): void {
    this.open.update((current) => (current === id ? null : id));
  }

  protected local(ts: string): string {
    return parseDate(ts).toLocaleString();
  }

  protected detailHtml(e: AuditEvent): string {
    return highlightText(json(e.detail));
  }
}
