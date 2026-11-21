"""Golden digests of the workflow keys, pinned for their scenario inputs."""

GOLDEN = {
    "workflow.contract.coding_change_tdd": "b8d4ea77baf9403a64eb73a76825bd706965d2320c97f72e938f9c2ffce2e99b",
    "workflow.contract.knowledge_definition": "f65277f452a1ddd9471565863983ac467b5b3f14bc4c8274f5b17865cf90ceed",
    "workflow.contract.knowledge_lookup": "841c3fa56bb0fbb4ae8971ebfa4bb127fe387a4731ce27bce7636ab3b998c092",
    "workflow.contract.line.required_axes": "5a18e7ac409a4fae7729d170182a56f36238f0d23f92a16c6a11bd7dac39feab",
    "workflow.catalog.rules": "77ebfe2725902d363f187441aab6251357d02fa3dd2c8367af8dbbf2ebaad331",
}

# SHA-256 of build_workflow_contract_message / build_workflow_capability_prompt /
# render_model_workflow_catalog_prompt for the inputs of tests/prompt_catalog_workflow_scenarios_support.py.
SCENARIOS = {
    "catalog:catalog": "732d6d0f0de30b62547e7ce892365d36571dff2a4c16de73abf1662541346bdf",
    "catalog:catalog_empty": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "contract:coding": "70d8023c59a53a125298e3d17743b88d33fae0ceddf0b841d41d61000824ea1d",
    "contract:coding_bare": "11da9effa0dc42abb86819762dccb2a33d6002b21ec4460a6940db402e30a4c6",
    "contract:empty": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "contract:knowledge_lookup": "53ed0596181d9af5459721c361f0685214e1bbb7bbf5ca637d92e6645cb78c0c",
}
