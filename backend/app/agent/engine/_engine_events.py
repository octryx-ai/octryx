"""Engine event model."""


class AgentEvent:
    def __init__(
        self,
        role: str,
        content: str | None = None,
        tool_calls: list | None = None,
        tool_results: list | None = None,
        model: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost: float = 0.0,
    ) -> None:
        self.role = role
        # The assistant's text goes to a person (chat, Teams/Slack replies, calls): no fence marker it copied from a
        # fenced read reaches them (fences belong only at a model's input). Tool results keep their fences.
        self.content = _unfenced(content) if role == "assistant" and isinstance(content, str) else content
        self.tool_calls = tool_calls
        self.tool_results = tool_results
        self.model = model
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.cost = cost


def _unfenced(text: str) -> str:
    from ...services.content_security.knowledge_fence import unfence_text

    return unfence_text(text)
