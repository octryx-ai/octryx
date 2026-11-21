"""A runtime mode stub shared by the test_runtime_defaults_* modules."""


class _Mode:
    def __init__(self, key: str, name: str, capability_type: str, prompt_instructions: str = "") -> None:
        self.key = key
        self.name = name
        self.capability_type = capability_type
        self.prompt_instructions = prompt_instructions
