// Shapes returned by the AgentHub API (see backend/app/models.py).

export type Role = 'admin' | 'developer' | 'agent' | 'viewer';
export type Decision = 'allowed' | 'denied' | 'error' | 'rate_limited';

export interface Skill {
  id: string;
  name: string;
  description?: string;
  tags?: string[];
}

export interface Agent {
  id: number;
  slug: string;
  name: string;
  description: string;
  version: string;
  framework: string;
  owner: string;
  status: 'active' | 'inactive';
  endpoint: string | null;
  skills: Skill[];
  created_at: string;
  updated_at: string;
}

export interface McpServer {
  id: number;
  slug: string;
  name: string;
  description: string;
  transport: 'stdio' | 'http';
  command: string | null;
  args: string[];
  url: string | null;
  enabled: boolean;
  status: 'unknown' | 'connected' | 'error';
  last_error: string | null;
}

export interface JsonSchema {
  type?: string;
  properties?: Record<string, { type?: string; title?: string; description?: string; default?: unknown }>;
  required?: string[];
}

export interface Tool {
  id: number;
  server_slug: string;
  name: string;
  description: string;
  input_schema: JsonSchema;
}

export interface ServerWithTools {
  server: McpServer;
  tools: Tool[];
}

export interface Policy {
  id?: number;
  priority: number;
  role: string;
  server: string;
  tool: string;
  effect: 'allow' | 'deny';
  mask_pii: boolean;
  description: string;
}

export interface AuditEvent {
  id: number;
  ts: string;
  principal: string;
  role: string;
  kind: 'tool' | 'llm' | 'a2a';
  server: string | null;
  tool: string | null;
  decision: Decision;
  reason: string;
  pii_masked: number;
  latency_ms: number;
  run_id: string | null;
  detail: Record<string, unknown>;
}

export interface Stats {
  agents: number;
  servers: number;
  tools: number;
  calls_24h: number;
  denied_24h: number;
  errors_24h: number;
  pii_masked_24h: number;
  avg_latency_ms: number;
  timeline: { hour: string; allowed: number; denied: number; error: number }[];
}

export interface Run {
  id: string;
  task: string;
  status: 'running' | 'succeeded' | 'failed';
  mode: 'scripted' | 'live';
  started_by: string;
  started_at: string;
  finished_at: string | null;
  output: string | null;
}

export interface Span {
  id: string;
  run_id: string | null;
  parent_id: string | null;
  name: string;
  kind: 'run' | 'agent' | 'llm' | 'tool' | 'a2a';
  status: 'ok' | 'error' | 'denied';
  start: string;
  end: string | null;
  attrs: Record<string, unknown>;
}

export interface A2AMessage {
  id: number;
  run_id: string | null;
  ts: string;
  sender: string;
  recipient: string;
  content: string;
}

export interface RunDetail {
  run: Run;
  spans: Span[];
  messages: A2AMessage[];
  audit: AuditEvent[];
}

export interface ToolOutcome {
  ok: boolean;
  decision: Decision;
  reason: string;
  content: { type: string; text?: string }[];
  structured: Record<string, unknown> | null;
  pii_masked: Record<string, number>;
  latency_ms: number;
  audit_id: number | null;
}

export interface LlmProvider {
  provider: string;
  model: string;
  mode: 'live' | 'scripted';
}

/** Events streamed from /runs/{id}/events */
export type RunEvent =
  | { type: 'run_started'; ts: string; run_id: string; task: string }
  | { type: 'agent_started'; ts: string; agent: string }
  | { type: 'agent_finished'; ts: string; agent: string; status: string }
  | {
      type: 'tool_call';
      ts: string;
      agent: string;
      server: string;
      tool: string;
      arguments: Record<string, unknown>;
      decision: Decision;
      reason: string;
      pii_masked: Record<string, number>;
      latency_ms: number;
    }
  | {
      type: 'llm';
      ts: string;
      agent: string;
      mode: string;
      provider: string;
      model: string;
      tokens: number;
      pii_masked: Record<string, number>;
    }
  | { type: 'a2a'; ts: string; from: string; to: string; message: string }
  | { type: 'run_finished'; ts: string; status: string; output: string; approved: boolean | null };
