import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

import { api } from '../core/api';
import { durationMs, formatMs, timeAgo } from '../core/format';
import { Run } from '../core/models';

@Component({
  selector: 'app-traces',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h1 class="page-title">Traces</h1>
    <p class="page-sub">Every crew run, with each agent step, model call, tool call and hand-off as a span.</p>

    <section class="card mt-6 overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full min-w-[640px]">
          <thead>
            <tr>
              <th class="table-head">Task</th>
              <th class="table-head">Status</th>
              <th class="table-head">LLM</th>
              <th class="table-head">Started by</th>
              <th class="table-head">When</th>
              <th class="table-head text-right">Duration</th>
            </tr>
          </thead>
          <tbody>
            @for (r of runs.value() ?? []; track r.id) {
              <tr class="transition hover:bg-surface-2">
                <td class="table-cell max-w-xs">
                  <a [routerLink]="['/traces', r.id]" class="block truncate text-text-primary hover:text-accent-soft">
                    {{ r.task }}
                  </a>
                  <span class="font-mono text-[11px] text-text-muted">{{ r.id.slice(0, 12) }}</span>
                </td>
                <td class="table-cell">
                  <span [class]="statusClass(r.status)">{{ r.status }}</span>
                </td>
                <td class="table-cell font-mono text-xs">{{ r.mode }}</td>
                <td class="table-cell font-mono text-xs">{{ r.started_by }}</td>
                <td class="table-cell whitespace-nowrap text-text-muted">{{ ago(r.started_at) }}</td>
                <td class="table-cell text-right tabular-nums text-text-muted">
                  {{ r.finished_at ? ms(dur(r.started_at, r.finished_at)) : '–' }}
                </td>
              </tr>
            } @empty {
              <tr>
                <td colspan="6" class="table-cell py-10 text-center text-text-muted">
                  @if (runs.isLoading()) {
                    Loading…
                  } @else {
                    No runs yet. <a routerLink="/playground" class="text-accent-soft hover:underline">Start one in the Playground</a>.
                  }
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    </section>
  `,
})
export class Traces {
  protected readonly runs = httpResource<Run[]>(() => api('/runs'));
  protected readonly ago = timeAgo;
  protected readonly ms = formatMs;
  protected readonly dur = durationMs;

  protected statusClass(status: Run['status']): string {
    return { succeeded: 'badge-allowed', failed: 'badge-denied', running: 'badge-error' }[status];
  }
}
