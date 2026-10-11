import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { AuthService } from './auth';
import { API_URL } from './config';
import { Policy, Run, RunEvent, ToolOutcome } from './models';

export const api = (path: string) => `${API_URL}${path}`;

/** Write operations and streams. Reads use httpResource() directly in components. */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);

  startRun(task: string): Promise<Run> {
    return firstValueFrom(this.http.post<Run>(api('/runs'), { task }));
  }

  /** Calls a tool through the gateway. Denials (403) still carry an outcome body. */
  async callTool(server: string, tool: string, args: Record<string, unknown>): Promise<ToolOutcome> {
    try {
      return await firstValueFrom(
        this.http.post<ToolOutcome>(api(`/gateway/tools/${server}/${tool}`), { arguments: args }),
      );
    } catch (err: unknown) {
      const body = (err as { error?: unknown }).error;
      if (body && typeof body === 'object' && 'decision' in body) return body as ToolOutcome;
      throw err;
    }
  }

  savePolicies(policies: Policy[]): Promise<Policy[]> {
    return firstValueFrom(this.http.put<Policy[]>(api('/policies'), policies));
  }

  refreshServer(slug: string): Promise<unknown> {
    return firstValueFrom(this.http.post(api(`/servers/${slug}/refresh`), {}));
  }

  /**
   * Streams run events over SSE using fetch (so the token goes in a header, not the URL).
   * Returns a function that stops the stream.
   */
  streamRun(runId: string, onEvent: (e: RunEvent) => void, onDone: (error?: string) => void): () => void {
    const controller = new AbortController();
    (async () => {
      try {
        const res = await fetch(api(`/runs/${runId}/events`), {
          headers: { Authorization: `Bearer ${this.auth.token}` },
          signal: controller.signal,
        });
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buffer.indexOf('\n\n')) >= 0) {
            const chunk = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            const data = chunk
              .split('\n')
              .filter((l) => l.startsWith('data: '))
              .map((l) => l.slice(6))
              .join('\n');
            if (data) onEvent(JSON.parse(data) as RunEvent);
          }
        }
        onDone();
      } catch (e) {
        if (!controller.signal.aborted) onDone(e instanceof Error ? e.message : 'Stream failed');
      }
    })();
    return () => controller.abort();
  }
}
