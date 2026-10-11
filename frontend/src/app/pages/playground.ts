import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { ApiService } from '../core/api';
import { formatMs, json, piiTotal, renderMarkdown } from '../core/format';
import { RunEvent } from '../core/models';
import { Icon } from '../layout/icon';

const AGENTS = [
  { id: 'planner', label: 'Planner', job: 'splits the task' },
  { id: 'researcher', label: 'Researcher', job: 'calls tools' },
  { id: 'writer', label: 'Writer', job: 'drafts the brief' },
  { id: 'reviewer', label: 'Reviewer', job: 'checks it' },
];

const SUGGESTIONS = [
  'Prepare a customer brief for Acme Corp',
  'Summarise open support issues for Globex',
  'Account review for Initech before the renewal call',
];

type AgentState = 'idle' | 'running' | 'done' | 'error';

@Component({
  selector: 'app-playground',
  imports: [FormsModule, RouterLink, Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h1 class="page-title">Playground</h1>
    <p class="page-sub max-w-2xl">
      Give the Research Crew a task. Four agents hand work to each other (A2A) and call MCP tools, and every call goes
      through the gateway. Watch PII get masked and one call get blocked by policy.
    </p>

    <form class="card mt-6 p-4 sm:p-5" (ngSubmit)="start()">
      <label class="label" for="task">Task</label>
      <div class="flex flex-col gap-3 sm:flex-row">
        <input
          id="task"
          name="task"
          class="input flex-1"
          maxlength="300"
          placeholder="e.g. Prepare a customer brief for Acme Corp"
          [(ngModel)]="task"
          [disabled]="running()"
        />
        <button type="submit" class="btn-primary shrink-0" [disabled]="running() || task.trim().length < 3">
          <app-icon name="play" /> {{ running() ? 'Running…' : 'Run crew' }}
        </button>
      </div>
      <div class="mt-3 flex flex-wrap gap-2">
        @for (s of suggestions; track s) {
          <button
            type="button"
            class="rounded-full border border-border-soft px-3 py-1 text-xs text-text-muted transition hover:border-accent/50 hover:text-text-primary disabled:opacity-50"
            [disabled]="running()"
            (click)="task = s"
          >
            {{ s }}
          </button>
        }
      </div>
      @if (error()) {
        <p class="mt-3 rounded-xl bg-deny/10 px-3 py-2 text-sm text-deny" role="alert">{{ error() }}</p>
      }
    </form>

    <!-- Agent pipeline -->
    <ol class="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
      @for (a of agents; track a.id; let i = $index) {
        <li
          class="card flex items-center gap-3 p-3 transition"
          [class.!border-accent]="agentState()[a.id] === 'running'"
        >
          <span
            class="grid h-8 w-8 shrink-0 place-items-center rounded-full font-mono text-xs"
            [class]="stateClass(agentState()[a.id])"
          >
            @switch (agentState()[a.id]) {
              @case ('done') { <app-icon name="check" /> }
              @case ('error') { <app-icon name="x" /> }
              @case ('running') { <span class="h-2 w-2 animate-ping rounded-full bg-accent-soft"></span> }
              @default { {{ i + 1 }} }
            }
          </span>
          <div class="min-w-0">
            <p class="text-sm text-text-primary">{{ a.label }}</p>
            <p class="truncate text-[11px] text-text-muted">{{ a.job }}</p>
          </div>
        </li>
      }
    </ol>

    @if (events().length) {
      <div class="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <!-- Live timeline -->
        <section class="card p-4 sm:p-5">
          <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 class="text-sm font-medium">Live gateway timeline</h2>
            <div class="flex gap-2 font-mono text-[11px]">
              <span class="chip">{{ counts().tools }} tool calls</span>
              @if (counts().denied) { <span class="chip !text-deny">{{ counts().denied }} blocked</span> }
              @if (counts().pii) { <span class="chip !text-accent-soft">{{ counts().pii }} PII masked</span> }
            </div>
          </div>
          <ol class="relative space-y-2 before:absolute before:inset-y-1 before:left-[15px] before:w-px before:bg-border-soft">
            @for (e of timeline(); track $index) {
              <li class="relative flex gap-3">
                <span
                  class="z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full border border-border bg-bg-raised"
                  [class]="e.tone"
                >
                  <app-icon [name]="e.icon" cls="h-3.5 w-3.5" />
                </span>
                <div class="min-w-0 flex-1 rounded-xl px-3 py-2" [class.bg-surface-2]="e.highlight">
                  <p class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                    <span class="font-mono text-[11px] text-text-muted">{{ e.agent }}</span>
                    <span class="text-text-primary">{{ e.title }}</span>
                    @if (e.badge) { <span [class]="'badge-' + e.badge">{{ e.badge }}</span> }
                    @if (e.pii) { <span class="pii">{{ e.pii }} PII masked</span> }
                  </p>
                  @if (e.detail) {
                    <p class="mt-0.5 break-words text-xs text-text-muted">{{ e.detail }}</p>
                  }
                </div>
              </li>
            }
            @if (running()) {
              <li class="flex items-center gap-3 pl-1 text-xs text-text-muted">
                <span class="h-2 w-2 animate-pulse rounded-full bg-accent"></span> working…
              </li>
            }
          </ol>
        </section>

        <!-- Result -->
        <section class="card p-4 sm:p-5">
          <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 class="text-sm font-medium">Customer brief</h2>
            @if (runId() && !running()) {
              <a [routerLink]="['/traces', runId()]" class="text-xs text-accent-soft hover:underline">View full trace →</a>
            }
          </div>
          @if (briefHtml(); as html) {
            <article class="prose-brief text-sm text-text-secondary" [innerHTML]="html"></article>
            <p class="mt-4 border-t border-border-soft pt-3 text-[11px] text-text-muted">
              Highlighted values like <span class="pii">&lt;EMAIL_ADDRESS&gt;</span> were masked by the gateway before any
              agent or model saw them.
            </p>
          } @else {
            <p class="text-sm text-text-muted">
              {{ running() ? 'The brief appears here when the Reviewer signs off.' : 'No output.' }}
            </p>
          }
        </section>
      </div>
    }
  `,
})
export class Playground {
  private readonly api = inject(ApiService);

  protected readonly agents = AGENTS;
  protected readonly suggestions = SUGGESTIONS;
  protected task = SUGGESTIONS[0];

  protected readonly events = signal<RunEvent[]>([]);
  protected readonly running = signal(false);
  protected readonly runId = signal<string | null>(null);
  protected readonly error = signal('');
  private stop: (() => void) | null = null;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.stop?.());
  }

  protected readonly agentState = computed(() => {
    const state: Record<string, AgentState> = Object.fromEntries(AGENTS.map((a) => [a.id, 'idle' as AgentState]));
    for (const e of this.events()) {
      if (e.type === 'agent_started') state[e.agent] = 'running';
      if (e.type === 'agent_finished') state[e.agent] = e.status === 'ok' ? 'done' : 'error';
    }
    return state;
  });

  protected readonly counts = computed(() => {
    let tools = 0;
    let denied = 0;
    let pii = 0;
    for (const e of this.events()) {
      if (e.type === 'tool_call') {
        tools++;
        if (e.decision === 'denied') denied++;
      }
      if (e.type === 'tool_call' || e.type === 'llm') pii += piiTotal(e.pii_masked);
    }
    return { tools, denied, pii };
  });

  protected readonly timeline = computed(() =>
    this.events().flatMap((e) => {
      switch (e.type) {
        case 'tool_call':
          return [
            {
              agent: e.agent,
              icon: e.decision === 'denied' ? 'lock' : 'tool',
              tone: e.decision === 'denied' ? 'text-deny' : e.decision === 'allowed' ? 'text-ok' : 'text-warn',
              title: `${e.server}.${e.tool}`,
              badge: e.decision,
              pii: piiTotal(e.pii_masked),
              detail: e.reason || `${compactArgs(e.arguments)} · ${formatMs(e.latency_ms)}`,
              highlight: e.decision === 'denied',
            },
          ];
        case 'llm':
          return [
            {
              agent: e.agent,
              icon: 'brain',
              tone: 'text-info',
              title: e.mode === 'live' ? `LLM · ${e.provider} ${e.model}` : 'LLM · scripted',
              badge: '',
              pii: piiTotal(e.pii_masked),
              detail: e.tokens ? `${e.tokens} tokens` : 'canned text, no key needed',
              highlight: false,
            },
          ];
        case 'a2a':
          return [
            {
              agent: e.from,
              icon: 'message',
              tone: 'text-accent-soft',
              title: `hands off to ${e.to}`,
              badge: '',
              pii: 0,
              detail: firstLine(e.message),
              highlight: false,
            },
          ];
        case 'run_finished':
          return [
            {
              agent: 'crew',
              icon: e.status === 'succeeded' ? 'check' : 'x',
              tone: e.status === 'succeeded' ? 'text-ok' : 'text-deny',
              title: e.status === 'succeeded' ? 'Run finished' : 'Run failed',
              badge: '',
              pii: 0,
              detail: e.approved === false ? 'Reviewer asked for changes' : '',
              highlight: false,
            },
          ];
        default:
          return [];
      }
    }),
  );

  protected readonly briefHtml = computed(() => {
    const done = this.events().find((e) => e.type === 'run_finished');
    return done && done.type === 'run_finished' && done.output ? renderMarkdown(done.output) : null;
  });

  protected stateClass(s: AgentState): string {
    return {
      idle: 'bg-surface-2 text-text-muted',
      running: 'bg-accent/15 text-accent-soft',
      done: 'bg-ok/15 text-ok',
      error: 'bg-deny/15 text-deny',
    }[s];
  }

  async start(): Promise<void> {
    const task = this.task.trim();
    if (task.length < 3 || this.running()) return;
    this.stop?.();
    this.events.set([]);
    this.error.set('');
    this.runId.set(null);
    this.running.set(true);
    try {
      const run = await this.api.startRun(task);
      this.runId.set(run.id);
      this.stop = this.api.streamRun(
        run.id,
        (e) => this.events.update((list) => [...list, e]),
        (err) => {
          this.running.set(false);
          if (err) this.error.set(`Lost the live stream (${err}). The run may still finish; check Traces.`);
        },
      );
    } catch (err) {
      this.running.set(false);
      const status = err instanceof HttpErrorResponse ? err.status : 0;
      this.error.set(
        status === 429
          ? 'Too many runs right now. Wait a few seconds and try again.'
          : status === 0
            ? "Can't reach the API. It may be waking up; try again shortly."
            : `Couldn't start the run (HTTP ${status}).`,
      );
    }
  }
}

function compactArgs(args: Record<string, unknown>): string {
  const text = json(args).replace(/\s+/g, ' ');
  return text.length > 80 ? `${text.slice(0, 77)}…` : text;
}

function firstLine(text: string): string {
  const line = text.split('\n').find((l) => l.trim()) ?? '';
  return line.length > 120 ? `${line.slice(0, 117)}…` : line;
}
