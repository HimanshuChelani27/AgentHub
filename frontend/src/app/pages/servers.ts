import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService, api } from '../core/api';
import { AuthService } from '../core/auth';
import { formatMs, highlightText, json, piiTotal } from '../core/format';
import { ServerWithTools, Tool, ToolOutcome } from '../core/models';
import { Icon } from '../layout/icon';

interface Field {
  name: string;
  type: string;
  required: boolean;
  description: string;
}

@Component({
  selector: 'app-servers',
  imports: [FormsModule, Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h1 class="page-title">MCP servers</h1>
    <p class="page-sub max-w-2xl">
      Tool servers registered with the gateway. Tools are discovered automatically on connect. Pick a tool to call it
      through the gateway as <span class="font-mono text-text-secondary">{{ auth.user()?.username }}</span>
      (<span class="font-mono">{{ auth.user()?.role }}</span>): your role's policy applies.
    </p>

    <div class="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div class="space-y-4">
        @for (s of servers.value() ?? []; track s.server.id) {
          <section class="card p-5">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <h2 class="flex items-center gap-2 text-base font-medium">
                  <app-icon name="server" cls="h-4 w-4 text-text-muted" /> {{ s.server.name }}
                </h2>
                <p class="mt-0.5 font-mono text-[11px] text-text-muted">
                  {{ s.server.slug }} · {{ s.server.transport }}
                  {{ s.server.transport === 'stdio' ? s.server.command + ' ' + s.server.args.join(' ') : s.server.url }}
                </p>
              </div>
              <div class="flex shrink-0 items-center gap-2">
                <span
                  class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[11px]"
                  [class]="statusClass(s.server.status)"
                >
                  <span class="h-1.5 w-1.5 rounded-full bg-current"></span>{{ s.server.status }}
                </span>
                @if (auth.canEdit()) {
                  <button
                    class="grid h-7 w-7 place-items-center rounded-full text-text-muted hover:bg-surface-2 hover:text-text-primary disabled:animate-spin"
                    [disabled]="refreshing() === s.server.slug"
                    (click)="refresh(s.server.slug)"
                    aria-label="Reconnect and rediscover tools"
                    title="Reconnect and rediscover tools"
                  >
                    <app-icon name="refresh" cls="h-3.5 w-3.5" />
                  </button>
                }
              </div>
            </div>
            <p class="mt-2 text-sm">{{ s.server.description }}</p>
            @if (s.server.last_error) {
              <p class="mt-2 rounded-lg bg-deny/10 px-3 py-2 font-mono text-xs text-deny">{{ s.server.last_error }}</p>
            }
            <ul class="mt-4 divide-y divide-border-soft rounded-xl border border-border-soft">
              @for (t of s.tools; track t.id) {
                <li>
                  <button
                    class="flex w-full items-start gap-3 px-3 py-2.5 text-left transition hover:bg-surface-2"
                    [class.bg-surface-2]="selected()?.id === t.id"
                    (click)="select(t)"
                  >
                    <app-icon name="tool" cls="mt-0.5 h-3.5 w-3.5 shrink-0 text-text-muted" />
                    <span class="min-w-0">
                      <span class="block font-mono text-xs text-text-primary">{{ t.name }}</span>
                      <span class="block text-xs text-text-muted">{{ t.description }}</span>
                    </span>
                  </button>
                </li>
              } @empty {
                <li class="px-3 py-2.5 text-xs text-text-muted">No tools discovered.</li>
              }
            </ul>
          </section>
        }
      </div>

      <!-- Try-tool console -->
      <section id="tool-console" class="card h-fit scroll-mt-20 p-5 lg:sticky lg:top-20">
        @if (selected(); as t) {
          <h2 class="font-mono text-sm text-text-primary">{{ t.server_slug }}.{{ t.name }}</h2>
          <p class="mt-1 text-xs text-text-muted">{{ t.description }}</p>
          <form class="mt-4 space-y-3" (ngSubmit)="call(t)">
            @for (f of fields(); track f.name) {
              <div>
                <label class="label" [for]="'arg-' + f.name">
                  {{ f.name }} <span class="font-mono text-text-muted">{{ f.type }}{{ f.required ? '' : ', optional' }}</span>
                </label>
                <input
                  class="input font-mono"
                  [id]="'arg-' + f.name"
                  [name]="f.name"
                  [placeholder]="f.description"
                  [(ngModel)]="args[f.name]"
                />
              </div>
            } @empty {
              <p class="text-xs text-text-muted">This tool takes no arguments.</p>
            }
            <button class="btn-primary" type="submit" [disabled]="calling()">
              <app-icon name="play" /> {{ calling() ? 'Calling…' : 'Call through gateway' }}
            </button>
          </form>

          @if (callError()) {
            <p class="mt-4 rounded-xl bg-deny/10 px-3 py-2 text-sm text-deny">{{ callError() }}</p>
          }
          @if (result(); as r) {
            <div class="mt-5 border-t border-border-soft pt-4">
              <div class="flex flex-wrap items-center gap-2 text-xs">
                <span [class]="'badge-' + r.decision">{{ r.decision }}</span>
                <span class="text-text-muted">{{ ms(r.latency_ms) }}</span>
                @if (pii(r.pii_masked)) {
                  <span class="pii">{{ pii(r.pii_masked) }} PII masked</span>
                }
                @if (r.audit_id) {
                  <span class="font-mono text-text-muted">audit #{{ r.audit_id }}</span>
                }
              </div>
              @if (r.reason) {
                <p class="mt-2 text-sm" [class.text-deny]="r.decision === 'denied'">{{ r.reason }}</p>
              }
              @if (r.decision === 'allowed') {
                <pre
                  class="mt-3 max-h-96 overflow-auto rounded-xl border border-border-soft bg-bg p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words"
                  [innerHTML]="resultHtml()"
                ></pre>
              }
            </div>
          }
        } @else {
          <div class="py-8 text-center">
            <app-icon name="tool" cls="mx-auto h-6 w-6 text-text-muted" />
            <p class="mt-3 text-sm text-text-primary">Try a tool</p>
            <p class="mx-auto mt-1 max-w-xs text-xs text-text-muted">
              Pick one on the left. Try <span class="font-mono">get_customer</span> with
              <span class="font-mono">acme</span> to see masking, or <span class="font-mono">get_contract</span> to see a
              policy block.
            </p>
          </div>
        }
      </section>
    </div>
  `,
})
export class Servers {
  protected readonly auth = inject(AuthService);
  private readonly apiService = inject(ApiService);

  protected readonly servers = httpResource<ServerWithTools[]>(() => api('/servers'));
  protected readonly selected = signal<Tool | null>(null);
  protected readonly refreshing = signal<string | null>(null);
  protected readonly calling = signal(false);
  protected readonly result = signal<ToolOutcome | null>(null);
  protected readonly callError = signal('');
  protected args: Record<string, string> = {};
  protected readonly ms = formatMs;
  protected readonly pii = piiTotal;

  protected readonly fields = computed<Field[]>(() => {
    const schema = this.selected()?.input_schema;
    const required = new Set(schema?.required ?? []);
    return Object.entries(schema?.properties ?? {}).map(([name, p]) => ({
      name,
      type: p.type ?? 'string',
      required: required.has(name),
      description: p.description ?? p.title ?? '',
    }));
  });

  protected readonly resultHtml = computed(() => {
    const r = this.result();
    if (!r) return '';
    const body = r.structured ?? r.content.map((c) => c.text ?? '').join('\n');
    return highlightText(typeof body === 'string' ? body : json(body));
  });

  protected statusClass(status: string): string {
    if (status === 'connected') return 'bg-ok/10 text-ok';
    if (status === 'error') return 'bg-deny/10 text-deny';
    return 'bg-surface-2 text-text-muted';
  }

  protected select(t: Tool): void {
    this.selected.set(t);
    this.result.set(null);
    this.callError.set('');
    this.args = t.name === 'get_customer' || t.name === 'get_contract' || t.name === 'list_open_tickets'
      ? { customer_id: 'acme' }
      : {};
    // On narrow screens the console sits below the server list.
    if (window.innerWidth < 1024) {
      setTimeout(() => document.getElementById('tool-console')?.scrollIntoView({ behavior: 'smooth' }));
    }
  }

  protected async call(t: Tool): Promise<void> {
    this.calling.set(true);
    this.callError.set('');
    this.result.set(null);
    try {
      this.result.set(await this.apiService.callTool(t.server_slug, t.name, this.coerceArgs()));
    } catch (err) {
      const status = (err as { status?: number }).status ?? 0;
      this.callError.set(status === 429 ? 'Rate limited. Wait a moment.' : `Call failed (HTTP ${status}).`);
    } finally {
      this.calling.set(false);
    }
  }

  protected async refresh(slug: string): Promise<void> {
    this.refreshing.set(slug);
    try {
      await this.apiService.refreshServer(slug);
      this.servers.reload();
    } finally {
      this.refreshing.set(null);
    }
  }

  /** Converts form strings into the types the tool's input schema expects. */
  private coerceArgs(): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const f of this.fields()) {
      const raw = (this.args[f.name] ?? '').trim();
      if (!raw && !f.required) continue;
      if (f.type === 'integer' || f.type === 'number') out[f.name] = Number(raw);
      else if (f.type === 'boolean') out[f.name] = raw === 'true';
      else out[f.name] = raw;
    }
    return out;
  }
}
