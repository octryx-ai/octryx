"""Golden digests of the knowledge keys, pinned for their scenario inputs."""

GOLDEN = {
    "knowledge.episode.system": "317f69a6e2906dcfa12f97664783aa5f42365c33a91414a1b8d6c493139232ed",
    "knowledge.episode.turn": "665cdee37260be682efcaf409b8d20a73984be71682c1c7f5f11bfe81a376c52",
    "knowledge.memory.capture_system": "ba82c85cbe60cc754d71713f25a6963b7c1132ada7fd30b7fc1af37ea84482cf",
    "knowledge.memory.capture_turn": "8c6847b88aa259e73c25f63d10d8754e4c7d6cad1fdb4ecbc5109102c2b0f73b",
    "knowledge.memory.notice": "888ca581245b0d03f9c301ef52d954f4b077e65600d978be2e2ce0b314b23860",
    "knowledge.package.plan_system": "28cb523c109972a0e28ca56f88547344c165f0e4f1ec1452708996eedf89dab3",
    "knowledge.package.select_system": "0f3c2381894146650695e1b7e7604db5c5a1dca31497674c81367d1dd42e0df5",
    "knowledge.graph.community_report": "750410d94e69ebde9aa20e64f86d50dc11231f07dde4357ac042df2afdfc6816",
    "knowledge.graph.global_answer": "dc551e5a876ea2a64aa670db59a297e23e447f132064e84f50c36d0af8d2e9de",
    "knowledge.graph.extraction": "4515957e7ecbe4672d7a7569d1a3ca3dd1dc19e9303c475b7243c96924bdd54c",
    "knowledge.graph.gleaning": "73ffee44da18ad4c4fb171888eeb80cc5c15651bcf9042169749452c083b1e64",
    "knowledge.graph.keywords": "643959baa416a837af3397229c490f6098a3a83e0af50d2fc6570aa5cf7693bc",
    "knowledge.graph.resummarize": "50007d8becb1ffc2e9f5f7e29a4a7a8b8be88379dd3890079bbbab3eb17c2c8a",
    "knowledge.mcp.instructions": "0e75bfb6522da64711cc55da94352c0f8ca458538d0e97620077b2501829f82f",
    "knowledge.teams.call_default_system": "386d92a497d256e714f4659bd1dc8da6c513a5f2f29105c12641fc52b6b5f5e1",
    "knowledge.teams.meeting_summary_system": "330b41c686ecb10dfabb1b031d722b40b9b69f00d5d6be6e1a813b9093c5437e",
    "knowledge.teams.meeting_summary_request": "2ead6e39a34536a0091e8c90a386d0d85d21dcdec3b042b41adf310e387783ff",
    "knowledge.readme.worker_system": "6141a4adc3aa6dd6d4fa9749aa7b640c708b049a98fd02c408f96d0138f1d310",
    "knowledge.readme.worker_task": "afde49e63ea44e44812e3c7b00af2661a8c8facf653f2f022628e9926a42b5e9",
}

# Pinned builder outputs for the scenario inputs (sha256).
SCENARIOS = {
    "episode:system": "ef51b1d4e74929a4aa759f1c16656fd31f0716df508e4a8e4ce49cab2ce3ad0b",
    "episode:turn": "882a63f8395aa4f8ba283b823b749fc5f62c558219af6884dd56a15525446e21",
    "episode:turn:empty": "2c6d6af69a67d515248aa2fdd2252093e0309dcc5001f09cbff7c34d27b9753c",
    "graph:extraction": "6354753615b413b0ed21eba35eb46d84b39ad9fee706a412d445842d68e612b7",
    "graph:gleaning": "1891822e3115b8be2e8f14b4a68561cf2bb893f06d90ffd1ec2158245b61ee43",
    "graph:gleaning:none": "69c1a3900c5a3575e5efc37ead6a706213a67f301834535f3d1f8ad497b2acf7",
    "graph:global": "16effe500502d6512e399f7f82f8e22fbb1bca62ce8ad53eabc90691286cd09d",
    "graph:keywords": "e4e0c7b73cc42766a2a66ef37b24fe927e60350bde8bed685891823149f55c49",
    "graph:report": "f80fa55a5f5fbe4e3de5c3aa0c2d04dafc37eebc9ff7abecd205e69c869ca7f2",
    "graph:resummarize": "e0baf8b32bdeefe29f9dadb78f4b504ee40d1421ac4ecdc79a602e592624ea3b",
    "mcp:instructions": "0e75bfb6522da64711cc55da94352c0f8ca458538d0e97620077b2501829f82f",
    "memory:notice": "888ca581245b0d03f9c301ef52d954f4b077e65600d978be2e2ce0b314b23860",
    "memory:system": "46741433ba68478d3b9a339c310dcc462183b024a9c79f07d789c6aafd47f36f",
    "memory:turn": "998a0076bbffacece6232e306b6de77cce9e579066552ee33ab4ff8fd2900054",
    "memory:turn:empty": "cb75d822d8a903288b47000750e77bb4673a1e946ab83152a5ac0b67d36bd4f1",
    "package:plan": "1f7aa59cdbf9ba7bf03b19606c5c0fb57c76a1651574a3236d55555e80b47372",  # neutral example product key
    "package:select": "ffc9a4056af88ed683d55262e5b36bf98f3d128982bf4e21fdd02f1b3d30aef0",
    "readme:system": "6141a4adc3aa6dd6d4fa9749aa7b640c708b049a98fd02c408f96d0138f1d310",
    "readme:task": "2717a94d0266900a6ed7c1febf058ebb980473d6354a9cde4b3e7ab0798d3095",
    "teams:call": "386d92a497d256e714f4659bd1dc8da6c513a5f2f29105c12641fc52b6b5f5e1",
    "teams:request": "2ead6e39a34536a0091e8c90a386d0d85d21dcdec3b042b41adf310e387783ff",
    "teams:summary": "330b41c686ecb10dfabb1b031d722b40b9b69f00d5d6be6e1a813b9093c5437e",
}
