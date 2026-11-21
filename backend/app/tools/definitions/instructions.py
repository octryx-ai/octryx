from __future__ import annotations


def get_instruction_definitions() -> dict[str, dict]:
    return {
        "instruction_get": {
            "type": "function",
            "function": {
                "name": "instruction_get",
                "description": (
                    "Read one published instruction by its exact key, global or of the active Workspace. "
                    "The instructions bound to this turn are already in the system prompt; use this only for "
                    "another instruction you were pointed to by key. Read-only."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Exact instruction key."},
                    },
                    "required": ["key"],
                },
            },
        }
    }
