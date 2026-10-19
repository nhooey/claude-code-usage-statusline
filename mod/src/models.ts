// Immutable, vendor-neutral data passed between adapters and renderers.
//
// The port of models.py.  A NamedTuple becomes a readonly record built by a
// function of the same name, with the same defaults; the fields keep the
// Python's names, so a record reads the same in both, and missing stays
// null rather than becoming zero.

export interface TokenUsage {
  readonly input_tokens: number | null;
  readonly cached_input_tokens: number | null;
  readonly output_tokens: number | null;
  readonly reasoning_output_tokens: number | null;
}

export function tokenUsage(u: Partial<TokenUsage> = {}): TokenUsage {
  return {
    input_tokens: u.input_tokens ?? null,
    cached_input_tokens: u.cached_input_tokens ?? null,
    output_tokens: u.output_tokens ?? null,
    reasoning_output_tokens: u.reasoning_output_tokens ?? null,
  };
}

// Codex's total input already includes its cached subset.  A subset is not a
// defensible total when the provider omitted the total field.
export function inputTotal(u: TokenUsage): number | null {
  return u.input_tokens;
}

// Likewise reasoning output is a subset, not a fallback total.
export function outputTotal(u: TokenUsage): number | null {
  return u.output_tokens;
}

export interface UsageRequest {
  readonly request_id: string;
  readonly session_id: string;
  readonly turn_id: string;
  readonly root_turn_id: string;
  readonly parent_thread_id: string;
  readonly timestamp: number | null;
  readonly model: string;
  readonly effort: string;
  readonly usage: TokenUsage;
  readonly cost_usd: number | null;
  readonly thread_id: string;
  readonly child: boolean;
  readonly started_at: number | null;
  readonly completed_at: number | null;
  readonly user_message: string;
  readonly assistant_message: string;
  readonly completed: boolean;
}

type Required_ = "request_id" | "session_id" | "turn_id" | "root_turn_id" |
  "parent_thread_id" | "timestamp" | "model" | "effort" | "usage";

export function usageRequest(
  u: Pick<UsageRequest, Required_> & Partial<UsageRequest>): UsageRequest {
  return {
    cost_usd: null, thread_id: "", child: false, started_at: null,
    completed_at: null, user_message: "", assistant_message: "",
    completed: false, ...u,
  };
}
