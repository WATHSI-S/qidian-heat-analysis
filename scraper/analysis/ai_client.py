"""One bounded client for optional model calls; imported only when requested."""
import os
import json

MODEL = "deepseek-chat"
PROMPT_VERSION = "2"


class AIClient:
    def __init__(self, max_calls=16, token_budget=100000):
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY is not configured")
        from openai import OpenAI
        self.client = OpenAI(api_key=key, base_url="https://api.deepseek.com/v1", timeout=45., max_retries=1)
        self.max_calls, self.remaining, self.calls = max_calls, token_budget, 0

    def complete(self, **kwargs):
        # Reserve a conservative input estimate and the maximum requested output.
        cost = len(json.dumps(kwargs["messages"], ensure_ascii=False)) + len(json.dumps(kwargs.get("tools", []), ensure_ascii=False)) + kwargs.get("max_tokens", 4096)
        if self.calls >= self.max_calls or cost > self.remaining:
            raise RuntimeError("AI call/token budget exhausted")
        self.calls += 1
        self.remaining -= cost
        return self.client.chat.completions.create(model=MODEL, **kwargs)
