import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed } from '@angular/core';
import { RouterLink } from '@angular/router';

import { api } from '../core/api';
import { auditTarget, formatMs, parseDate, timeAgo } from '../core/format';
import { AuditEvent, Stats } from '../core/models';
import { Icon } from '../layout/icon';

const CHART_H = 160;

@Component({
  selector: 'app-overview',
  imports: [RouterLink, Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 class="page-title">Overview</h1>
        <p class="page-sub">What went through the gateway in the last 24 hours.</p>
      </div>
      <a routerLink="/playground" class="btn-primary"><app-icon name="play" /> Run the Research Crew</a>
    </div>

    @if (stats.error()) {
      <p class="card mt-6 p-5 text-sm text-deny">Couldn't load stats. Is the API running?</p>
    }

    @if (stats.value(); as s) {
      <div class="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        @for (k of kpis(); track k.label) {
          <div class="card p-4">
            <p class="text-xs text-text-muted">{{ k.label }}</p>
            <p class="mt-1.5 text-2xl font-semibold tabular-nums" [class]="k.tone">{{ k.value }}</p>
            <p class="mt-0.5 text-[11px] text-text-muted">{{ k.hint }}</p>
          </div>
        }
      </div>

      <section class="card mt-4 p-5">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h2 class="text-sm font-medium">Gateway calls per hour</h2>
          <div class="flex gap-4 text-[11px] text-text-muted">
            <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-sm bg-ok"></span>Allowed</span>
            <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-sm bg-deny"></span>Denied</span>
            <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-sm bg-warn"></span>Error</span>
          </div>
        </div>
        @if (chart(); as c) {
          <div class="mt-4 flex gap-2">
            <div class="flex flex-col justify-between pb-5 text-right font-mono text-[10px] text-text-muted">
              <span>{{ c.max }}</span><span>0</span>
            </div>
            <div class="min-w-0 flex-1">
              <svg
                [attr.viewBox]="'0 0 ' + c.width + ' ' + chartH"
                preserveAspectRatio="none"
                class="h-40 w-full"
                role="img"
                [attr.aria-label]="'Calls per hour over the last 24 hours, peak ' + c.max"
              >
                <line x1="0" [attr.x2]="c.width" [attr.y1]="chartH - 0.5" [attr.y2]="chartH - 0.5" class="stroke-border" />
                @for (b of c.bars; track b.x) {
                  <g>
                    <title>{{ b.label }}: {{ b.allowed }} allowed, {{ b.denied }} denied, {{ b.error }} error</title>
                    <rect [attr.x]="b.x" y="0" [attr.width]="c.barW" [attr.height]="chartH" class="fill-transparent hover:fill-white/[0.03]" />
                    <rect [attr.x]="b.x" [attr.y]="b.yA" [attr.width]="c.barW" [attr.height]="b.hA" class="fill-ok" rx="1.5" />
                    <rect [attr.x]="b.x" [attr.y]="b.yD" [attr.width]="c.barW" [attr.height]="b.hD" class="fill-deny" rx="1.5" />
                    <rect [attr.x]="b.x" [attr.y]="b.yE" [attr.width]="c.barW" [attr.height]="b.hE" class="fill-warn" rx="1.5" />
                  </g>
                }
              </svg>
              <div class="mt-1.5 flex justify-between font-mono text-[10px] text-text-muted">
                <span>{{ c.first }}</span><span>now</span>
              </div>
            </div>
          </div>
          @if (c.empty) {
            <p class="mt-2 text-center text-xs text-text-muted">No calls yet. Run the crew in the Playground to fill this in.</p>
          }
        }
      </section>
    }

    <section class="card mt-4 overflow-hidden">
      <div class="flex items-center justify-between px-5 py-4">
        <h2 class="text-sm font-medium">Latest gateway activity</h2>
        <a routerLink="/audit" class="text-xs text-accent-soft hover:underline">Full audit log →</a>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full min-w-[640px]">
          <thead>
            <tr>
              <th class="table-head">When</th>
              <th class="table-head">Who</th>
              <th class="table-head">What</th>
              <th class="table-head">Decision</th>
              <th class="table-head text-right">PII masked</th>
              <th class="table-head text-right">Latency</th>
            </tr>
          </thead>
          <tbody>
            @for (e of recent.value() ?? []; track e.id) {
              <tr>
                <td class="table-cell whitespace-nowrap text-text-muted">{{ ago(e.ts) }}</td>
                <td class="table-cell font-mono text-xs">{{ e.principal }}</td>
                <td class="table-cell font-mono text-xs text-text-primary">{{ what(e) }}</td>
                <td class="table-cell"><span [class]="'badge-' + e.decision">{{ e.decision }}</span></td>
                <td class="table-cell text-right tabular-nums">{{ e.pii_masked || '–' }}</td>
                <td class="table-cell text-right tabular-nums text-text-muted">{{ ms(e.latency_ms) }}</td>
              </tr>
            } @empty {
              <tr><td colspan="6" class="table-cell text-center text-text-muted">Nothing yet.</td></tr>
            }
          </tbody>
        </table>
      </div>
    </section>
  `,
})
export class Overview {
  protected readonly chartH = CHART_H;
  protected readonly stats = httpResource<Stats>(() => api('/stats'));
  protected readonly recent = httpResource<AuditEvent[]>(() => api('/audit?limit=8'));
  protected readonly ago = timeAgo;
  protected readonly ms = formatMs;
  protected readonly what = auditTarget;

  protected readonly kpis = computed(() => {
    const s = this.stats.value();
    if (!s) return [];
    return [
      { label: 'Registered agents', value: s.agents, hint: `${s.servers} MCP servers · ${s.tools} tools`, tone: '' },
      { label: 'Calls (24h)', value: s.calls_24h, hint: `avg ${formatMs(s.avg_latency_ms)}`, tone: '' },
      { label: 'Blocked by policy', value: s.denied_24h, hint: `${s.errors_24h} errors / rate-limited`, tone: s.denied_24h ? 'text-deny' : '' },
      { label: 'PII entities masked', value: s.pii_masked_24h, hint: 'emails, phones, names…', tone: 'text-accent-soft' },
    ];
  });

  protected readonly chart = computed(() => {
    const timeline = this.stats.value()?.timeline ?? [];
    if (!timeline.length) return null;
    const barW = 10;
    const gap = 4;
    const max = Math.max(1, ...timeline.map((t) => t.allowed + t.denied + t.error));
    const scale = (n: number) => (n / max) * (CHART_H - 4);
    const bars = timeline.map((t, i) => {
      const hA = scale(t.allowed);
      const hD = scale(t.denied);
      const hE = scale(t.error);
      const yA = CHART_H - hA;
      const yD = yA - hD;
      const yE = yD - hE;
      const label = parseDate(t.hour).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      return { ...t, x: i * (barW + gap), hA, hD, hE, yA, yD, yE, label };
    });
    return {
      bars,
      barW,
      max,
      width: timeline.length * (barW + gap) - gap,
      first: bars[0].label,
      empty: timeline.every((t) => t.allowed + t.denied + t.error === 0),
    };
  });
}
