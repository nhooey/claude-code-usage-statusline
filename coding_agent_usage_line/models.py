"""Immutable, vendor-neutral data passed between adapters and renderers."""
from typing import NamedTuple, Optional


class TokenUsage(NamedTuple):
    input_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    reasoning_output_tokens: Optional[int] = None

    @property
    def input_total(self):
        # Codex's total input already includes its cached subset. A subset is
        # not a defensible total when the provider omitted the total field.
        return self.input_tokens

    @property
    def output_total(self):
        # Likewise reasoning output is a subset, not a fallback total.
        return self.output_tokens


class UsageRequest(NamedTuple):
    request_id: str
    session_id: str
    turn_id: str
    root_turn_id: str
    parent_thread_id: str
    timestamp: Optional[float]
    model: str
    effort: str
    usage: TokenUsage
    cost_usd: Optional[float] = None
    thread_id: str = ""
    child: bool = False
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    user_message: str = ""
    assistant_message: str = ""
    completed: bool = False
