import inspect

from app.agent.core.context.run_context_prompt_policy import compose_memory_prompt


def test_compose_memory_prompt_injects_only_the_engineering_resolution() -> None:
    assert compose_memory_prompt(engineering_knowledge_prompt="## Engineering Context\nCoding standards") == (
        "## Engineering Context\nCoding standards"
    )
    assert compose_memory_prompt() == ""


def test_compose_memory_prompt_takes_no_legacy_memory_or_knowledge_map_slot() -> None:
    # The retired memory blocks, project memory and KnowledgeMap critical entries have no slot left.
    assert set(inspect.signature(compose_memory_prompt).parameters) == {"engineering_knowledge_prompt"}
