export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '';
  const seconds = Math.round((Date.now() - parseDate(iso).getTime()) / 1000);
  if (seconds < 45) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/** The API returns naive UTC timestamps from SQLite; treat them as UTC. */
export function parseDate(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
}

export function durationMs(start: string, end: string | null): number {
  if (!end) return 0;
  return Math.max(0, parseDate(end).getTime() - parseDate(start).getTime());
}

export function formatMs(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(2)} s`;
}

export function piiTotal(counts: Record<string, number> | undefined | null): number {
  return Object.values(counts ?? {}).reduce((a, b) => a + b, 0);
}

export function json(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
}

/** Highlights masking placeholders like <PERSON> in already-escaped HTML. */
function highlightPii(html: string): string {
  return html.replace(/&lt;([A-Z_]{3,})&gt;/g, '<span class="pii">&lt;$1&gt;</span>');
}

/**
 * Tiny Markdown renderer for crew briefs: headings, bold, bullet lists, rules, paragraphs.
 * Input is HTML-escaped first, so LLM output can't inject markup.
 */
export function renderMarkdown(md: string): string {
  const inline = (s: string) => highlightPii(escapeHtml(s)).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  const out: string[] = [];
  let list = false;
  for (const raw of md.split('\n')) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    if (bullet) {
      if (!list) out.push('<ul>');
      list = true;
      out.push(`<li>${inline(bullet[1])}</li>`);
      continue;
    }
    if (list) out.push('</ul>');
    list = false;
    if (!line.trim()) continue;
    const heading = /^#{1,3}\s+(.*)$/.exec(line);
    if (heading) out.push(`<h2>${inline(heading[1])}</h2>`);
    else if (/^-{3,}$/.test(line.trim())) out.push('<hr>');
    else out.push(`<p>${inline(line)}</p>`);
  }
  if (list) out.push('</ul>');
  return out.join('');
}

/** Escapes text and highlights PII placeholders (for JSON/plain text blocks). */
export function highlightText(text: string): string {
  return highlightPii(escapeHtml(text));
}

/** Short label for what an audit row was about. */
export function auditTarget(e: { kind: string; server: string | null; tool: string | null }): string {
  if (e.kind === 'tool') return `${e.server}.${e.tool}`;
  if (e.kind === 'llm') return e.server === e.tool ? `llm · ${e.server}` : `llm · ${e.server} ${e.tool}`;
  return `a2a · ${e.server} → ${e.tool}`;
}
