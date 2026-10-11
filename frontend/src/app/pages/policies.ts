import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService, api } from '../core/api';
import { AuthService } from '../core/auth';
import { Policy } from '../core/models';
import { Icon } from '../layout/icon';

const ROLES = ['*', 'admin', 'developer', 'agent', 'viewer'];

@Component({
  selector: 'app-policies',
  imports: [FormsModule, Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 class="page-title">Policies</h1>
        <p class="page-sub max-w-2xl">
          Rules are checked top to bottom and the first match wins. Server and tool accept globs like
          <span class="font-mono text-text-secondary">*</span> or <span class="font-mono text-text-secondary">get_*</span>.
          If nothing matches, the call is denied.
        </p>
      </div>
      @if (auth.isAdmin()) {
        <div class="flex gap-2">
          @if (editing()) {
            <button class="btn-ghost" (click)="cancel()">Cancel</button>
            <button class="btn-primary" [disabled]="saving()" (click)="save()">
              <app-icon name="check" /> {{ saving() ? 'Saving…' : 'Save rules' }}
            </button>
          } @else {
            <button class="btn-ghost" (click)="editing.set(true)">Edit rules</button>
          }
        </div>
      } @else {
        <span class="chip"><app-icon name="lock" cls="mr-1 h-3 w-3" /> Read-only: only admins can edit</span>
      }
    </div>

    @if (message(); as m) {
      <p class="mt-4 rounded-xl px-3 py-2 text-sm" [class]="m.ok ? 'bg-ok/10 text-ok' : 'bg-deny/10 text-deny'">{{ m.text }}</p>
    }

    <section class="card mt-6 overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full min-w-[820px]">
          <thead>
            <tr>
              <th class="table-head w-12">#</th>
              <th class="table-head">Role</th>
              <th class="table-head">Server</th>
              <th class="table-head">Tool</th>
              <th class="table-head">Effect</th>
              <th class="table-head">Mask PII</th>
              <th class="table-head">Why</th>
              @if (editing()) { <th class="table-head w-24"></th> }
            </tr>
          </thead>
          <tbody>
            @for (p of draft(); track $index; let i = $index, first = $first, last = $last) {
              <tr>
                <td class="table-cell font-mono text-xs text-text-muted">{{ i + 1 }}</td>
                @if (editing()) {
                  <td class="table-cell">
                    <select class="input !py-1.5 font-mono text-xs" [(ngModel)]="p.role" [attr.aria-label]="'Rule ' + (i + 1) + ' role'">
                      @for (r of roles; track r) { <option [value]="r">{{ r }}</option> }
                    </select>
                  </td>
                  <td class="table-cell"><input class="input !py-1.5 font-mono text-xs" [(ngModel)]="p.server" [attr.aria-label]="'Rule ' + (i + 1) + ' server'" /></td>
                  <td class="table-cell"><input class="input !py-1.5 font-mono text-xs" [(ngModel)]="p.tool" [attr.aria-label]="'Rule ' + (i + 1) + ' tool'" /></td>
                  <td class="table-cell">
                    <select class="input !py-1.5 font-mono text-xs" [(ngModel)]="p.effect" [attr.aria-label]="'Rule ' + (i + 1) + ' effect'">
                      <option value="allow">allow</option>
                      <option value="deny">deny</option>
                    </select>
                  </td>
                  <td class="table-cell">
                    <input type="checkbox" class="h-4 w-4 accent-accent" [(ngModel)]="p.mask_pii" [attr.aria-label]="'Rule ' + (i + 1) + ' mask PII'" />
                  </td>
                  <td class="table-cell"><input class="input !py-1.5 text-xs" [(ngModel)]="p.description" [attr.aria-label]="'Rule ' + (i + 1) + ' description'" /></td>
                  <td class="table-cell whitespace-nowrap text-right">
                    <button class="px-1 text-text-muted hover:text-text-primary disabled:opacity-30" [disabled]="first" (click)="move(i, -1)" aria-label="Move up">↑</button>
                    <button class="px-1 text-text-muted hover:text-text-primary disabled:opacity-30" [disabled]="last" (click)="move(i, 1)" aria-label="Move down">↓</button>
                    <button class="px-1 text-text-muted hover:text-deny" (click)="remove(i)" aria-label="Delete rule"><app-icon name="x" cls="h-3.5 w-3.5" /></button>
                  </td>
                } @else {
                  <td class="table-cell font-mono text-xs text-text-primary">{{ p.role }}</td>
                  <td class="table-cell font-mono text-xs">{{ p.server }}</td>
                  <td class="table-cell font-mono text-xs">{{ p.tool }}</td>
                  <td class="table-cell"><span [class]="p.effect === 'allow' ? 'badge-allowed' : 'badge-denied'">{{ p.effect }}</span></td>
                  <td class="table-cell">
                    @if (p.mask_pii) {
                      <span class="inline-flex items-center gap-1 text-xs text-accent-soft"><app-icon name="mask" cls="h-3.5 w-3.5" /> yes</span>
                    } @else {
                      <span class="text-xs text-text-muted">no</span>
                    }
                  </td>
                  <td class="table-cell text-xs text-text-muted">{{ p.description }}</td>
                }
              </tr>
            }
            <tr>
              <td class="table-cell font-mono text-xs text-text-muted">–</td>
              <td colspan="3" class="table-cell font-mono text-xs text-text-muted">anything else</td>
              <td class="table-cell"><span class="badge-denied">deny</span></td>
              <td class="table-cell"></td>
              <td class="table-cell text-xs text-text-muted" [attr.colspan]="editing() ? 2 : 1">Default: no rule matched</td>
            </tr>
          </tbody>
        </table>
      </div>
      @if (editing()) {
        <div class="border-t border-border-soft p-3">
          <button class="btn-ghost" (click)="add()">+ Add rule</button>
        </div>
      }
    </section>
  `,
})
export class Policies {
  protected readonly auth = inject(AuthService);
  private readonly apiService = inject(ApiService);

  protected readonly roles = ROLES;
  protected readonly policies = httpResource<Policy[]>(() => api('/policies'));
  protected readonly draft = signal<Policy[]>([]);
  protected readonly editing = signal(false);
  protected readonly saving = signal(false);
  protected readonly message = signal<{ ok: boolean; text: string } | null>(null);

  constructor() {
    effect(() => this.draft.set(clone(this.policies.value() ?? [])));
  }

  protected add(): void {
    this.draft.update((list) => [
      ...list,
      { priority: 0, role: 'agent', server: '*', tool: '*', effect: 'deny', mask_pii: true, description: '' },
    ]);
  }

  protected remove(i: number): void {
    this.draft.update((list) => list.filter((_, idx) => idx !== i));
  }

  protected move(i: number, delta: number): void {
    this.draft.update((list) => {
      const next = [...list];
      [next[i], next[i + delta]] = [next[i + delta], next[i]];
      return next;
    });
  }

  protected cancel(): void {
    this.draft.set(clone(this.policies.value() ?? []));
    this.editing.set(false);
    this.message.set(null);
  }

  protected async save(): Promise<void> {
    this.saving.set(true);
    this.message.set(null);
    try {
      // Row order is the evaluation order; priorities are renumbered to match it.
      const body = this.draft().map(({ id: _id, ...p }, i) => ({ ...p, priority: (i + 1) * 10 }));
      this.policies.set(await this.apiService.savePolicies(body));
      this.editing.set(false);
      this.message.set({ ok: true, text: 'Rules saved. They apply to the next call.' });
    } catch {
      this.message.set({ ok: false, text: "Couldn't save the rules." });
    } finally {
      this.saving.set(false);
    }
  }
}

function clone(list: Policy[]): Policy[] {
  return list.map((p) => ({ ...p }));
}
