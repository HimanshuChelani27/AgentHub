import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { api } from '../core/api';
import { auditTarget, durationMs, formatMs, json, parseDate, renderMarkdown, timeAgo } from '../core/format';
import { RunDetail, Span } from '../core/models';
import { Icon } from '../layout/icon';

const KIND_STYLE: Record<Span['kind'], { bar: string; icon: string }> = {
  run: { bar: 'bg-text-muted/50', icon: 'trace' },
  agent: { bar: 'bg-accent', icon: 'agents' },
  llm: { bar: 'bg-info', icon: 'brain' },
  tool: { bar: 'bg-ok', icon: 'tool' },
  a2a: { bar: 'bg-accent-soft', icon: 'message' },
};

interface Row {
  span: Span;
  depth: number;
  left: number;
  width: number;
  duration: number;
  bar: string;
  icon: string;
}

@Component({
  selector: 'app-trace-detail',
  imports: [RouterLink, Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a routerLink="/traces" class="text-xs text-text-muted hover:text-text-primary">← All traces</a>

    @if (detail.error()) {
      <p class="card mt-4 p-5 text-sm text-deny">Couldn't load this run.</p>
    }

    @if (detail.value(); as d) {
      <div class="mt-3 flex flex-wrap items-start justify-between gap-3">
        <div class="min-w-0">
          <h1 class="page-title break-words">{{ d.run.task }}</h1>
          <p class="page-sub font-mono text-xs">
            {{ d.run.id }} · {{ d.run.mode }} LLM · by {{ d.run.started_by }} · {{ ago(d.run.started_at) }}
          </p>
        </div>
        <div class="flex flex-wrap gap-2 font-mono text-[11px]">
          <span class="chip">{{ d.spans.length }} spans</span>
          <span class="chip">{{ ms(total()) }}</span>
          <span [class]="d.run.status === 'succeeded' ? 'badge-allowed' : d.run.status === 'failed' ? 'badge-denied' : 'badge-error'">
            {{ d.run.status }}
          </span>
        </div>
      </div>

      <!-- Waterfall -->
      <section class="card mt-6 p-4 sm:p-5">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-sm font-medium">Span waterfall</h2>
          <div class="flex flex-wrap gap-3 text-[11px] text-text-muted">
            @for (k of legend; track k.kind) {
              <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-sm" [class]="k.bar"></span>{{ k.kind }}</span>
            }
            <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-sm bg-deny"></span>denied</span>
          </div>
        </div>
        <div class="space-y-0.5">
          @for (r of rows(); track r.span.id) {
            <button
              class="grid w-full grid-cols-[minmax(0,15rem)_minmax(0,1fr)] items-center gap-3 rounded-lg px-2 py-1.5 text-left transition hover:bg-surface-2 max-sm:grid-cols-1 max-sm:gap-1"
              [class.bg-surface-2]="selected()?.id === r.span.id"
              (click)="selected.set(selected()?.id === r.span.id ? null : r.span)"
            >
              <span class="flex min-w-0 items-center gap-1.5 text-xs" [style.padding-left.px]="r.depth * 14">
                <app-icon [name]="r.icon" cls="h-3.5 w-3.5 shrink-0 text-text-muted" />
                <span class="truncate font-mono" [class]="r.span.status === 'ok' ? 'text-text-primary' : 'text-deny'">{{ r.span.name }}</span>
              </span>
              <span class="relative h-5">
                <span
                  class="absolute inset-y-1 min-w-[3px] rounded"
                  [class]="r.span.status === 'ok' ? r.bar : 'bg-deny'"
                  [style.left.%]="r.left"
                  [style.width.%]="r.width"
                ></span>
                <span
                  class="absolute top-0.5 whitespace-nowrap font-mono text-[10px] text-text-muted"
                  [style.left.%]="r.left + r.width > 82 ? null : r.left + r.width"
                  [style.right.%]="r.left + r.width > 82 ? 100 - r.left : null"
                  [class]="r.left + r.width > 82 ? 'pr-1.5' : 'pl-1.5'"
                >{{ ms(r.duration) }}</span>
              </span>
            </button>
            @if (selected()?.id === r.span.id) {
              <pre class="mx-2 mb-2 overflow-x-auto rounded-lg border border-border-soft bg-bg p-3 font-mono text-[11px] leading-relaxed">{{ json({ kind: r.span.kind, status: r.span.status, start: r.span.start, ...r.span.attrs }) }}</pre>
            }
          } @empty {
            <p class="text-sm text-text-muted">No spans recorded.</p>
          }
        </div>
      </section>

      <div class="mt-4 grid gap-4 lg:grid-cols-2">
        <!-- A2A conversation -->
        <section class="card p-4 sm:p-5">
          <h2 class="mb-3 text-sm font-medium">Agent-to-agent messages</h2>
          <ol class="space-y-3">
            @for (m of d.messages; track m.id) {
              <li class="rounded-xl border border-border-soft bg-bg-raised p-3">
                <p class="mb-1.5 font-mono text-[11px] text-accent-soft">{{ m.sender }} → {{ m.recipient }}</p>
                <p class="line-clamp-6 whitespace-pre-line text-xs leading-relaxed">{{ m.content }}</p>
              </li>
            } @empty {
              <li class="text-sm text-text-muted">No hand-offs.</li>
            }
          </ol>
        </section>

        <!-- Output -->
        <section class="card p-4 sm:p-5">
          <h2 class="mb-3 text-sm font-medium">Output</h2>
          @if (d.run.output) {
            <article class="prose-brief text-sm" [innerHTML]="outputHtml()"></article>
          } @else {
            <p class="text-sm text-text-muted">No output.</p>
          }
        </section>
      </div>

      <!-- Audit rows -->
      <section class="card mt-4 overflow-hidden">
        <h2 class="px-5 py-4 text-sm font-medium">Gateway audit for this run</h2>
        <div class="overflow-x-auto">
          <table class="w-full min-w-[600px]">
            <thead>
              <tr>
                <th class="table-head">Who</th>
                <th class="table-head">What</th>
                <th class="table-head">Decision</th>
                <th class="table-head">Reason</th>
                <th class="table-head text-right">PII</th>
                <th class="table-head text-right">Latency</th>
              </tr>
            </thead>
            <tbody>
              @for (e of d.audit; track e.id) {
                <tr>
                  <td class="table-cell font-mono text-xs">{{ e.principal }}</td>
                  <td class="table-cell font-mono text-xs text-text-primary">{{ what(e) }}</td>
                  <td class="table-cell"><span [class]="'badge-' + e.decision">{{ e.decision }}</span></td>
                  <td class="table-cell text-xs text-text-muted">{{ e.reason }}</td>
                  <td class="table-cell text-right tabular-nums">{{ e.pii_masked || '–' }}</td>
                  <td class="table-cell text-right tabular-nums text-text-muted">{{ ms(e.latency_ms) }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      </section>
    }
  `,
})
export class TraceDetail {
  readonly id = input.required<string>();

  protected readonly detail = httpResource<RunDetail>(() => api(`/runs/${this.id()}`));
  protected readonly selected = signal<Span | null>(null);
  protected readonly legend = (['agent', 'llm', 'tool', 'a2a'] as const).map((kind) => ({ kind, bar: KIND_STYLE[kind].bar }));
  protected readonly ago = timeAgo;
  protected readonly ms = formatMs;
  protected readonly json = json;
  protected readonly what = auditTarget;

  private readonly bounds = computed(() => {
    const d = this.detail.value();
    if (!d?.spans.length) return null;
    const starts = d.spans.map((s) => parseDate(s.start).getTime());
    const ends = d.spans.map((s) => parseDate(s.end ?? s.start).getTime());
    const t0 = Math.min(...starts, parseDate(d.run.started_at).getTime());
    const t1 = Math.max(...ends, d.run.finished_at ? parseDate(d.run.finished_at).getTime() : 0);
    return { t0, span: Math.max(1, t1 - t0) };
  });

  protected readonly total = computed(() => {
    const d = this.detail.value();
    if (d?.run.finished_at) return durationMs(d.run.started_at, d.run.finished_at);
    return this.bounds()?.span ?? 0;
  });

  /** Spans in tree order (parent before children, siblings by start time). */
  protected readonly rows = computed<Row[]>(() => {
    const d = this.detail.value();
    const b = this.bounds();
    if (!d || !b) return [];
    const ids = new Set(d.spans.map((s) => s.id));
    const children = new Map<string | null, Span[]>();
    for (const s of d.spans) {
      const parent = s.parent_id && ids.has(s.parent_id) ? s.parent_id : null;
      children.set(parent, [...(children.get(parent) ?? []), s]);
    }
    const out: Row[] = [];
    const walk = (parent: string | null, depth: number) => {
      const list = (children.get(parent) ?? []).sort(
        (a, c) => parseDate(a.start).getTime() - parseDate(c.start).getTime(),
      );
      for (const s of list) {
        const start = parseDate(s.start).getTime();
        const duration = durationMs(s.start, s.end);
        const style = KIND_STYLE[s.kind] ?? KIND_STYLE.run;
        out.push({
          span: s,
          depth,
          left: ((start - b.t0) / b.span) * 100,
          width: Math.max(0.4, (duration / b.span) * 100),
          duration,
          bar: style.bar,
          icon: style.icon,
        });
        walk(s.id, depth + 1);
      }
    };
    walk(null, 0);
    return out;
  });

  protected readonly outputHtml = computed(() => renderMarkdown(this.detail.value()?.run.output ?? ''));
}
