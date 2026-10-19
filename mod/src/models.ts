// Immutable, vendor-neutral data passed between adapters and renderers.
//
// The port of models.py.  A NamedTuple becomes a readonly record built by a
// function of the same name, with the same defaults; the fields keep their
// names in camelCase, and missing stays null rather than becoming zero.

export interface TokenUsage {
  readonly inputTokens: number | null;
  readonly cachedInputTokens: number | null;
  readonly outputTokens: number | null;
  readonly reasoningOutputTokens: number | null;
}

export function tokenUsage(u: Partial<TokenUsage> = {}): TokenUsage {
  return {
    inputTokens: u.inputTokens ?? null,
    cachedInputTokens: u.cachedInputTokens ?? null,
    outputTokens: u.outputTokens ?? null,
    reasoningOutputTokens: u.reasoningOutputTokens ?? null,
  };
}

// Codex's total input already includes its cached subset.  A subset is not a
// defensible total when the provider omitted the total field.
export function inputTotal(u: TokenUsage): number | null {
  return u.inputTokens;
}

// Likewise reasoning output is a subset, not a fallback total.
export function outputTotal(u: TokenUsage): number | null {
  return u.outputTokens;
}

export interface UsageRequest {
  readonly requestId: string;
  readonly sessionId: string;
  readonly turnId: string;
  readonly rootTurnId: string;
  readonly parentThreadId: string;
  readonly timestamp: number | null;
  readonly model: string;
  readonly effort: string;
  readonly usage: TokenUsage;
  readonly costUsd: number | null;
  readonly threadId: string;
  readonly child: boolean;
  readonly startedAt: number | null;
  readonly completedAt: number | null;
  readonly userMessage: string;
  readonly assistantMessage: string;
  readonly completed: boolean;
}

type Required_ = "requestId" | "sessionId" | "turnId" | "rootTurnId" |
  "parentThreadId" | "timestamp" | "model" | "effort" | "usage";

export function usageRequest(
  u: Pick<UsageRequest, Required_> & Partial<UsageRequest>): UsageRequest {
  return {
    costUsd: null, threadId: "", child: false, startedAt: null,
    completedAt: null, userMessage: "", assistantMessage: "",
    completed: false, ...u,
  };
}
