"""Seeds of the texts the platform sends an agent between the phases of a workflow run (kept in the catalog, not in the
code; a workflow's owner overrides them per workflow, a Workspace per Workspace)."""

from __future__ import annotations

from ..contract import PromptKeySpec

AREA = "run"


# The editor's groups (display text, order) by key prefix; data for the frontend, never a table there.
GROUPS = (("launcher.", "Pipeline and launcher", 20), ("device.", "Pipeline and launcher", 20),
          ("pipeline_red", "Pipeline and launcher", 20), ("hands_on_red", "Pipeline and launcher", 20),
          ("evidence.", "Evidence", 30), ("item.", "Team and coordinator", 40),
          ("coordinator.", "Team and coordinator", 40),
          ("light.", "Light path", 50), ("model.", "Models", 60), ("block.", "Blocks and pauses", 70),
          ("protected.", "Blocks and pauses", 70),
          ("pause.", "Blocks and pauses", 70), ("remedy.", "Blocks and pauses", 70), ("brief.", "Phase brief", 15),
          ("", "Continuation", 10))

# What each placeholder carries (one English sentence), shared by every key that uses the name.
PLACEHOLDERS = {
    "code": "The failure's structured code (failure_codes.json).",
    "problem": "What the step reported (its own words).",
    "plain": "The same test run without the redirection into a file.",
    "codes": "The platform's answer codes, e.g. ' (unreachable)'.",
    "reason_text": "Why the rule refused it (the matched rule's own words).",
    "path": "The path the call named, relative to the repository.",
    "patterns": "The phase's write patterns (path_rules.write).",
    "tool": "The tool the call used.",
    "denied_as": "The platform tool the phase's agent denies.",
    "target": "The folder or path the command named.",
    "detail": "The refusal's own detail (what the rule found).",
    "run_state": "The run's state in one line (paused, waiting, its phase and loops).",
    "loop": "The loop's title (the edge the run took back).",
    "used": "How often the run took that loop.",
    "limit": "The loop's limit.", "keys": "The budget keys the run used up.",
    "gate": "The gate's title (a check step after a phase).",
    "failed": "The gate's failed checks with their detail.",
    "run_id": "The workflow run's id.",
    "workflow_key": "The workflow's key, e.g. epic-delivery.",
    "read_contract": "The sentence that sends the agent to its run contract (run.read_contract).",
    "step": "The title of the platform step that prepared the folder.",
    "phase": "The phase's title.",
    "capability_class": "What the phase may do (read_only, code_change, ...).",
    "what_changed": "Why the phase runs again, joined from the run.changed.* texts.",
    "resumed": "The rendered run.resumed text this one continues.",
    "details": "The changed contract fields as indented JSON.",
    "lead": "run.plain_story.epic_lead for a further story of the epic, else empty.",
    "key": "The work item's key.", "title": "The work item's (or story's) title.",
    "description": "The work item's description.",
    "tests": "The environment file note or run.plain_story.tests, with its blank line; empty without tests.",
    "brief": "The phase's own brief (its when_to_use).",
    "commands": "The test commands, quoted and joined.",
    "how": "run.evidence.concurrent.with or .one_file, rendered.",
    "item_id": "The work item's id in the team plan.",
    "iteration": "How often the item ran (1, 2, ...).",
    "why": "The coordinator's reason for reopening, else run.item.reopened.",
    "merged": "run.item.merged when the merge left conflicts, else empty.",
    "files": "The files with merge conflicts, comma separated.",
    "messages": "The board message ids addressed to the coordinator.",
    "open_items": "The ids of the plan's items not merged yet, or none.",
    "role": "The item's role in the team.", "ticket": "The run's ticket key or title.",
    "summary": "The red commands with their failed tests and output tail.",
    "file": "The environment file's path.",
    "folder": "The app folder the pipeline runs in.",
    "from_phase": "The phase that sent the run back.",
    "command": "The repository's declared test command.",
    "hint": "The matching runner's hint from the stack data (stacks.json test_runner.hint), with its separator; may be "
            "empty.",
    "hints": "Every stack's runner label and hint (stacks.json test_runner), joined.",
    "missing": "Each declared command that did not run in full or failed, joined.",
    "full_run_hint": "What a full run of the command may add (stacks.json test_runner.full_run_hint).",
    "intent": "What that phase tried and was refused (the tool and its command or path).",
    "refusal": "The platform's refusal message there.",
    "model": "The model the phase's seat turn runs on.",
    "options": "The choices the person picks from, comma separated.",
    "times": "How often the run was refused the same request, this time included.",
    "paths": "The phase's path patterns, quoted and comma separated.",
    "error": "The environment error an earlier run of the app stopped on (its first line).",
    "ran": "The setup and test commands that ran green after that error, joined with '; '.",
    "reason": "Why the platform refused the call (the refusal's reason code).",
    "refused": "The refused command or path.",
    "worked": "The call of the same tool the platform allowed next.",
    "kb": "How many KB the command printed.",
    "format": "The environment file's format (its keys and what each holds).",
    "tools": "The tools a check names, comma separated.",
    "shorter": "The short form of the same command that printed little.",
    "checks": "The phase's checks the platform judges at its end, joined with '; '.",
    "source": "Where that model comes from (seat_models.json source_labels, e.g. \"Workspace default 'implement'\").",
}


def _group(key: str) -> tuple[str, int]:
    return next((label, order) for prefix, label, order in GROUPS if key.startswith(prefix))


def _spec(key: str, title: str, seed: str, *placeholders: str) -> PromptKeySpec:
    label, order = _group(key)
    return PromptKeySpec(key=f"run.{key}", area=AREA, title=title, seed=seed, placeholders=frozenset(placeholders),
                         group=label, group_order=order,
                         placeholder_descriptions=tuple((name, PLACEHOLDERS[name]) for name in placeholders))


SPECS: tuple[PromptKeySpec, ...] = (
    # The launcher's system prompt of a run's phase turn: the phase's contract arrives in the turn's context;
    # workflow_run_status is only for what is missing.
    _spec("device.system_prompt", "The system prompt of a run's phase turn on a device",
          "You are a software engineer working one phase of an Octryx AI workflow run in this repository. The "
          "phase's contract (its task, rules and checks) comes with the prompt; call workflow_run_status only if it "
          "is missing or you need more. Do exactly that phase. Look at what exists before you change it. Bash runs "
          "your tests and the commands the work needs; the platform refuses only what could destroy work, leak "
          "secrets or touch git's own files, and a refusal names the reason and the way instead. When the phase's "
          "checks can pass, stop; when something blocks you, say what blocks you, why, and what you need."),
    # A model can read "Continue workflow run epic-delivery" as a run id; workflow_run_status then
    # answers unknown_run and the agent tries to start a new workflow instead of following its own.
    # the launcher puts the phase's compact contract into the turn's context, so a call
    # at every turn's start only cost time (its 64 KB answer was even unreadable to the agent).
    # The story and plain session prompts live here too: as code constants (device_sdk) they kept saying
    # "read your run contract first with workflow_run_status" after the contract came with the prompt.
    _spec("device.story_session_prompt", "The run paragraph of a story session on a device",
          "You are building one story of an Octryx workflow run in this repository, in this one session. Your run "
          "contract for this phase (the work item, its acceptance criteria, the specification sections and the "
          "declared test commands) comes with the prompt; call workflow_run_status only if it is missing or you need "
          "more. Work like an experienced developer: plan the story with your own task list (TodoWrite), and use your "
          "own subagents (the Agent tool) for independent parts such as backend, frontend and tests: start them with "
          "several Agent calls in one message so they run in parallel (there are no background tasks in this "
          "session: each call returns when its subagent is done); give each a self-contained brief (the files it "
          "owns, the interface it builds against), then integrate and verify yourself. The platform checks every "
          "tool call, your subagents' too; a refusal names its reason, so adjust instead of repeating the call. Run "
          "the declared test commands as declared before you finish (piping one into tail or grep is fine; chain "
          "nothing after it): only then they run outside the sandbox, where the app's port and the browser work. "
          "When the story is done, end your turn with a short summary; the platform then runs the declared tests "
          "itself and an independent review, and sends anything red back into this session."),
    _spec("device.plain_session_prompt", "The run paragraph of a plain story session (epic-delivery)",
          "You are building a story of an Octryx epic in this repository, in this one session; the story is in the "
          "user's message. Use your own subagents (the Agent tool) for independent parts, started with several "
          "Agent calls in one message so they run in parallel (there are no background tasks in this session). Run "
          "the declared test commands as declared before you finish. The platform then runs the tests itself and an "
          "independent review, and sends anything red back into this session; workflow_run_status shows the details "
          "then."),
    # The run contract's own notes (rendered by octryx/contract.py).
    _spec("contract.device_tools_note", "Contract: how to read the phase's tool lists",
          "Call the tools in on_device. allow/deny are the platform's policy names; the names in parentheses are "
          "what each native tool stands for, not tools to call."),
    _spec("contract.web_requests", "Contract: how web requests work in the sandbox",
          "Fetch web pages and APIs with the WebFetch tool or with Node (fetch, a node script): in this sandbox curl "
          "and Python HTTPS requests fail the certificate check for some hosts."),
    _spec("contract.knowledge_first", "Contract: the Workspace's knowledge before the web",
          "Before you search the web, check the Workspace's knowledge (knowledge_search: its specifications, pages "
          "and decisions, with earlier specs' rule values and sources) and the code; use what it finds and cite it "
          "with its cite_as link."),
    _spec("contract.new_tests", "Contract: how new tests import new code",
          "Import the code under test from the module where the implementation will live (for example `from "
          "<package>.<module> import <Name>`). Never define, stub or copy the code under test inside a test file: "
          "the implement phase may not change the confirmed tests, so a stub there could never be replaced. When "
          "that module does not exist yet, the new tests fail at the import (ModuleNotFoundError / ImportError) — the "
          "platform counts that as red for new code; an existing module's new behaviour fails on an assertion."),
    _spec("contract.pipeline_after", "Contract: the CI pipeline after a building phase",
          "After this phase the CI pipeline runs the repository's declared test and system test commands on your "
          "change, without you, and checks that every task's proof test passes there. It is the judge of green and "
          "of each task: run tests as you like while you work (any options, a single file or a filter, piped into "
          "tail), then finish; a red pipeline comes back to you with the failing tests and the tasks without a "
          "passing proof."),
    _spec("contract.environment_file", "Contract: declare the story's test commands in the environment file",
          "Declare this story's test commands in {file} ({format}) The pipeline runs exactly those in {folder}/ (the "
          "working directory of every command; path entries are relative to it) and nothing else; create or update "
          "the file with the story's tests, including the Playwright system test.", "file", "format", "folder"),
    _spec("contract.codex_tools_note", "Contract: how a Codex session reads its tools",
          "Call the tools in on_device. You are Codex: read with the shell (cat, rg, ls, find), change files with "
          "apply_patch, run commands and tests with the shell; the platform's tools are the "
          "mcp__octryx_knowledge__* ones. allow/deny are the platform's policy names; the names in "
          "parentheses are what each tool stands for, not tools to call. Without an apply_patch tool, run it in the "
          "shell in exactly this form: apply_patch <<'PATCH' / *** Begin Patch / *** Add File: <path> (each line "
          "starts with +) or *** Update File: <path> (@@, -old, +new) / *** End Patch / PATCH (one line each, no "
          "JSON). Shell redirection (>, tee) never writes files here."),
    _spec("contract.plain_agent", "Contract: the Engineer's instructions in a plain story session",
          "You are the Engineer building this story in one Claude Code session. Never weaken, skip or delete a test "
          "to make it pass. Report what you changed and which tests prove it."),
    _spec("read_contract", "Read the run contract first",
          "Read your run contract first: the launcher puts this phase's contract into your context with this prompt. "
          "Only if it is not there, or you need more, call workflow_run_status with no arguments (this session's run "
          "is {run_id}; detail=true adds the code style and the earlier change). Work only within it. Never select "
          "or start another workflow.", "run_id"),
    _spec("continue_prepared", "A fresh turn after the platform prepared the folder",
          "Continue the {workflow_key} workflow run: the platform prepared this folder ({step}). {read_contract}",
          "workflow_key", "step", "read_contract"),
    _spec("continue_phase", "A fresh phase turn",
          "Continue the {workflow_key} workflow run: phase '{phase}' ({capability_class}). {read_contract}",
          "workflow_key", "phase", "capability_class", "read_contract"),
    _spec("pipeline_red", "The pipeline was red: the building phase's session continues",
          "Phase '{phase}' of this run ({run_id}) continues in this session: the platform's CI pipeline ran the "
          "repository's declared test commands on your change and they are red. Your earlier work, plan and reading "
          "still stand: do not re-read the specification or files you already know. The failing commands, the "
          "failing tests and the end of their output follow below (the launcher adds them; phase.pipeline_failure in "
          "workflow_run_status has the same). Fix exactly that, run the declared commands verbatim, then end your "
          "turn with a short summary.", "phase", "run_id"),
    # A red hands-on test has its own text: with the hands-on step's generic text, named after the step, the
    # building phase's session changed nothing.
    _spec("hands_on_red", "The hands-on test was red: the building phase's session continues",
          "Phase '{phase}' of this run ({run_id}) continues in this session: the platform used the built app like a "
          "person would and the hands-on test is red. Your earlier work, plan and reading still stand: do not re-read "
          "the specification or files you already know. phase.hands_on_failure in workflow_run_status names each "
          "failed scenario with its failed step. Fix the app (not the test) so those scenarios pass, run the declared "
          "commands verbatim, then end your turn with a short summary.", "phase", "run_id"),
    _spec("changed.pipeline_failure", "What changed: the pipeline failed",
          "the pipeline failed on your change (phase.pipeline_failure names the failing commands)"),
    _spec("changed.product_owner_answers", "What changed: the product owner answered",
          "the product owner answered (phase.product_owner_answers: apply each answer)"),
    _spec("changed.review_findings", "What changed: the review returned findings",
          "the review returned findings (phase.review_findings: fix each one)"),
    _spec("changed.findings", "What changed: the phase's checks failed", "the phase's checks failed (phase.findings)"),
    # without it a red hands-on pass re-fetched the whole contract instead of its delta.
    _spec("changed.hands_on_failure", "What changed: the hands-on test failed",
          "the hands-on test of the built app failed (phase.hands_on_failure names the scenario and step)"),
    _spec("changed.none", "What changed: nothing named", "the platform runs this phase again"),
    # A phase's refusals rule sent the run back here: the agent reads why (otherwise the
    # reproduce phase runs again without knowing the fix phase cannot change the test that asserts the bug).
    _spec("changed.change_plan", "What changed: a later phase sent the run back here",
          "the platform sent the run back here from phase '{from_phase}', which was refused {intent} ({refusal}); "
          "make what it needed possible in this phase", "from_phase", "intent", "refusal"),
    # Size classes with session "shared": the next phase in the session that did the earlier ones.
    _spec("next_phase", "The next phase in the run's shared session",
          "The run moves on to its next phase in this session: phase '{phase}' ({capability_class}). What you did and "
          "read so far still stands: do not re-read the ticket, the specification or files you already know. This "
          "phase has its own rules (tools, paths, checks). {read_contract}",
          "phase", "capability_class", "read_contract"),
    # A failed gate's loop back into its phase has its own text: with "moves on to its next phase" the agent
    # never learned why it was back.
    _spec("back_after_gate", "Back in a phase after its gate failed",
          "Gate '{gate}' failed: {failed}. The run is back in phase '{phase}' to fix exactly that; what you did and "
          "read so far still stands, do not redo the rest. {read_contract}",
          "gate", "failed", "phase", "read_contract"),
    _spec("gate_failure.line", "Stop: why the phase is back (its failed gate)",
          "Back here because gate '{gate}' failed: {failed}.", "gate", "failed"),
    _spec("changed.gate_failed", "What changed: the gate after the phase failed",
          "gate '{gate}' failed: {failed}", "gate", "failed"),
    # Size classes with context_cap_tokens: a fresh session after the context cap.
    _spec("context_cap.handoff", "A fresh session after the context cap",
          "An earlier session of this run grew too large to continue, so this one starts fresh. The work so far is in "
          "this branch: read `git log --oneline` and `git diff` against the base branch first, then go on from there; "
          "do not redo what the commits already did."),
    _spec("epic_next_story", "The next story of the epic in the same session",
          "A new story of the same epic starts in this session: phase '{phase}' of the {workflow_key} run {run_id}. "
          "What you read for the previous story (the specification, the earlier story contracts, the code) still "
          "stands: do not re-read it; read only what this story names and what changed since. {read_contract}",
          "phase", "workflow_key", "run_id", "read_contract"),
    _spec("plain_story.epic_lead", "Plain story brief: lead of a further story of the epic",
          "A new story of the same epic starts in this session; what you read and built for the previous story "
          "still stands. "),
    _spec("plain_story.tests", "Plain story brief: the declared test commands",
          "Declared test commands: {commands}.\n\n", "commands"),
    _spec("plain_story", "Plain story brief",
          "{lead}Build this story in this repository (workflow run {run_id}).\n\n# {key} {title}\n\n{description}\n\n"
          "{tests}{brief}\n\nThe platform's run contract (workflow_run_status) adds nothing you need now; the platform "
          "sends a red pipeline or review findings back into this session.",
          "lead", "run_id", "key", "title", "description", "tests", "brief"),
    _spec("resumed_retry", "Resume after a temporary model service error",
          "Your last turn in phase '{phase}' (run {run_id}) stopped on a temporary error of the model service. "
          "Continue exactly where you stopped; nothing else changed.", "phase", "run_id"),
    _spec("resumed", "Resume of the phase's own session: what changed",
          "Phase '{phase}' of this run ({run_id}) continues in this session: {what_changed}. Your earlier work, plan "
          "and reading still stand: do not re-read the specification or files you already know.",
          "phase", "run_id", "what_changed"),
    _spec("resumed.ask", "Resume without details: fetch them once",
          "{resumed} Call workflow_run_status once for the details, fix exactly that, then finish the phase.",
          "resumed"),
    _spec("resumed.details", "Resume with the changed contract fields",
          "{resumed} The details are below; fix exactly that, then finish the phase (workflow_run_status only if you "
          "need more than this).\n\n{details}", "resumed", "details"),
    _spec("evidence.concurrent", "Hint after a concurrent test run",
          "Your last test run ran several test files concurrently, so the platform could attribute only its "
          "failures and could not see your confirmed tests pass. {how} (the whole suite or the test files), without "
          "piping the output through tail/head, so every test's result is reported.", "how"),
    _spec("evidence.concurrent.with", "Hint after a concurrent test run: the evidence commands",
          "Run the tests with {commands}", "commands"),
    _spec("evidence.concurrent.one_file", "Hint after a concurrent test run: without evidence commands",
          "Run the tests one file at a time"),
    # How a phase runs its tests on the device (contract phase.how_to_run_tests); the runner's hint is stack data
    # (stacks.json test_runner.hint): a fixed text would name pytest in a Flutter repository.
    _spec("tests.how", "How to run the tests on the device",
          "Run the tests in the shell on this device; that run is the phase's run_test_suite evidence. {how}", "how"),
    _spec("tests.declared", "How to run the tests: the declared command",
          "Use the repository's declared test command exactly as declared: `{command}`{hint}.", "command", "hint"),
    _spec("tests.environment_file", "How to run the tests: the environment file's command",
          "Use the test command of {file} (its test entry) exactly as declared{hint}.", "file", "hint"),
    _spec("tests.undeclared", "How to run the tests: no declared command",
          "Use the repository's own test runner: {hints}.", "hints"),
    # A size class whose agent runs the affected tests only (agent_tests: affected).
    _spec("tests.affected", "How to run the tests: only the affected test files",
          "Run only the test files of the confirmed tests and of the code you changed, not the whole suite: the "
          "pipeline runs the whole suite after this phase and sends anything red back to you."),
    # A class with "agent_system_test": "pipeline" leaves the system test to the pipeline.
    _spec("tests.system_by_pipeline", "How to run the tests: the system test runs in the pipeline",
          "Do not run the system test yourself: the pipeline after this phase runs it on every pass and sends a red "
          "result back to you with its output; run it only to look into such a red result."),
    # The full suite after the last change (Stop feedback of a changing phase); the runner's hint is stack data
    # (stacks.json test_runner.full_run_hint): a generic "-q, -x are fine" makes a Flutter agent run
    # `flutter test -q`, which the shell policy refuses.
    _spec("full_suite.not_run", "Full suite: the declared command did not run in full",
          "`{command}` did not run in full after the last change", "command"),
    _spec("full_suite.failed", "Full suite: the last full run failed",
          "`{command}` failed in its last full run after the last change", "command"),
    _spec("full_suite.required", "Full suite: green after the last change",
          "The full test suite must be green after your last change: {missing}. Run it with its whole selection "
          "(no file or test filter; {full_run_hint}) and make it green", "missing", "full_run_hint"),
    # A shell write in a strict phase (e.g. `cat >> tests/test_split.py <<'EOF'`) gets its own text: the generic
    # refusal said nothing about what to change.
    _spec("shell.write_refused", "Shell: a file written through the shell in a strict phase",
          "Phase '{phase}' writes files with Edit or Write, not through the shell (no redirection into a file, no "
          "heredoc): this phase's shell is strict. Next: write the same content with the Write tool, or add it with "
          "Edit.", "phase"),
    _spec("shell.strict_refused", "Shell: a command a phase without free shell refused",
          "Phase '{phase}' runs only plain test and read-only commands in the shell: no redirection, variables, nested "
          "shells or options that load code or write files. A "
          "declared test or lint command, or one `&&` step of it, may run on its own, also after `cd` into the app "
          "folder and piped into `tail`. The Workspace admin sets which reads run (Settings → Security → Command "
          "safety). Next: run the declared test command or a read-only command, and create or change files with "
          "Edit or Write.", "phase"),
    # Every block explains itself, "<what>. <why>. Next: <step>." A guard test
    # (tests/test_blocks_explain_themselves.py) keeps every denial of the run's tool policy and every pause on a key
    # of this group, each with a "Next:".
    _spec("block.hard_deny", "Block: a command that never runs in a run",
          "This command never runs during a workflow run: {reason_text}. It can expose secrets or destroy work. "
          "Next: do the step another way, or end your turn and say what you needed.", "reason_text"),
    _spec("block.scm_client", "Block: an SCM or Jira client on the device",
          "Jira, pull requests and CI go through the platform during a workflow run, not through a client on this "
          "device. Next: ask for it with workflow_action_request, or leave it to the run's later steps.", ),
    _spec("block.push", "Block: git push on the device",
          "git push never runs here: the platform pushes the reviewed change. Next: commit nothing yourself; finish "
          "the phase and the run pushes after its review.", ),
    _spec("block.path_outside", "Block: a path outside the repository",
          "'{path}' is outside the repository this run works in. Every change stays inside it. Next: use a path "
          "inside the repository (relative to its root).", "path"),
    # "a person confirmed" only when a person did.
    _spec("protected.confirmed_by_person", "Block: a test a person confirmed",
          "'{path}' is a test a person confirmed: phase '{phase}' makes the code pass, it never changes the test.",
          "path", "phase"),
    _spec("protected.confirmed_by_run", "Block: the reproduction test this run submitted",
          "'{path}' is the reproduction test this run submitted and the platform bound: phase '{phase}' makes the "
          "code pass, it never changes the test.", "path", "phase"),
    _spec("block.protected", "Block: a protected path",
          "{detail} Next: change the code (or the files the phase may change) so the protected file can stay as it "
          "is; if it really must change, end your turn and say why.", "detail"),
    # With the refusal, the concrete form this run allows (``refusal_hints``).
    _spec("block.instead_test", "Block addition: the run's own test command",
          "Next: run the declared test command `{command}` as its own call in `{folder}` (cd there first; piping into "
          "`tail` is fine).", "command", "folder"),
    _spec("block.instead_confirmed", "Block addition: a confirmed test stays as it is",
          "`{path}` is a confirmed test: it shows the bug and stays as it is. Next: make the code pass it; if the test "
          "itself is wrong, say so in your summary and the run goes back to correct it.", "path"),
    _spec("block.again", "Block addition: the same request was refused before",
          "This is the same request refused {times} times in this run. Next: do not retry it; take the way named "
          "here or end your turn and say what you need.", "times"),
    _spec("same_pass.checks", "Delta: the name of a pass's own checks", "the phase's own checks"),
    _spec("same_pass.unknown", "Delta: unfinished checks without a name",
          "its checks did not pass at the last stop; finish what is open, the work so far stays"),
    _spec("block.contract_file", "Block detail: the run's environment file is its contract",
          "'{path}' is this run's environment file, its contract: the pipeline, the hands-on test and every check run "
          "what it declared when the run started, and phase '{phase}' does not change it. Next: make the code fit "
          "the declared commands; if the contract itself is wrong, end your turn and say what must change.",
          "path", "phase"),
    _spec("block.path_rules", "Block: a file outside the phase's paths",
          "Phase '{phase}' may only change: {patterns}. Next: change only files under these patterns, or end your "
          "turn and say which other file is needed and why.", "phase", "patterns"),
    _spec("block.no_write_tools", "Block: a change in a phase that changes no files",
          "Phase '{phase}' changes no files: it reads, plans or checks. Next: write what you found into your answer "
          "and finish the phase; a later phase makes the change.", "phase"),
    _spec("block.pytest_names", "Block: pytest without test names",
          "The platform matches every test by its name, and -q prints none. Next: run pytest with -v (for example "
          "`.venv/bin/python -m pytest -v`).", ),
    _spec("block.folder_removal", "Block: removing a folder outside the phase's paths",
          "'{target}' is no generated folder and not wholly inside the paths of phase '{phase}'. Next: remove it with "
          "`git rm -r {target}` (tracked files only, git can restore them) or its files one by one.", "target",
          "phase"),
    _spec("block.agent_tool", "Block: a tool the phase denies",
          "Phase '{phase}' denies the tool '{tool}'. Next: use the phase's own tools (your run contract lists them).",
          "phase", "tool"),
    _spec("block.agent_native_tool", "Block: a native tool that does what a denied tool does",
          "The phase's agent denies '{denied_as}', and '{tool}' does the same. Next: use the phase's own tools (your "
          "run contract lists them).", "denied_as", "tool"),
    _spec("block.web_research_only", "Block: web research outside a research phase",
          "Phase '{phase}' does not research on the web in this Workspace. Next: work from the repository and the "
          "run's documents; a Workspace admin can allow the web for every phase.", "phase"),
    _spec("block.web_off", "Block: the web is off in this Workspace",
          "This Workspace does not use the web in its runs. Next: work from the repository and the run's documents; "
          "a Workspace admin can turn the web on.", ),
    _spec("block.run_not_running", "Block: a change while the run is paused or waiting",
          "The run does not take changes now: {run_state} Next: end your turn; the run goes on when a person "
          "decides (the link above).", "run_state"),
    _spec("block.capability_in_run", "Block: a change the phase's capability does not allow",
          "{detail} Next: stay within phase '{phase}' (your run contract says what it may do), or end your turn and "
          "say what you needed.", "detail", "phase"),
    _spec("block.phase_not_done", "Stop: the phase is not done yet",
          "Phase '{phase}' is not done: {detail}. Next: do what is missing, then finish again. {run_state}",
          "phase", "detail", "run_state"),
    # Without this pause, an agent that changes nothing after a red hands-on test has the same tree run the same
    # scenarios again (minutes each) until the loop limit.
    _spec("hands_on.unchanged", "Pause: the hands-on test is red and the agent changed nothing",
          "The hands-on test was red on this code ({failed}) and the agent made no change since, so running it again "
          "would show the same. The scenario may be wrong, or the agent may have missed it. Next: read the agent's "
          "answer and the failed step, then waive the scenario with a reason, regenerate the scenarios, or run the "
          "phase again with a hint.", "failed"),
    _spec("failure.deterministic", "Pause: a step failed the same way every time (configuration)",
          "The step stopped on {code}: {problem} Retrying would fail the same way, so the run uses no loop round. "
          "Next: fix it as described (the repository's environment file or the device), then retry the step.",
          "code", "problem"),
    _spec("pause.default", "Pause: why the run waits for a person",
          "The run is paused. Next: open the run and choose: continue, change the plan or abort.", ),
    _spec("pause.no_reply", "Pause: No reply arrived in time",
          "The run asked a question and no reply arrived in time. "
          "Next: answer it in the run card, or continue without it, change the plan or abort."),
    _spec("pause.device_unreachable", "Pause: The device did not answer",
          "Next: check or restart the launcher on the device (octryx-claude device start), then continue: the step "
          "runs again, no loop round is spent."),
    _spec("pause.seat_required", "Pause: The run needs your seat",
          "This step needs a person's seat (subscription), and the server runners never hold one. Next: take the run "
          "over on your device with that seat, change where it runs, or abort."),
    _spec("pause.watch_timeout", "Pause: A watched state did not arrive",
          "The state the run waits for (a merge, a CI result) did not arrive in time. "
          "Next: check the pull request or CI, then continue or abort."),
    _spec("pause.approval_timeout", "Pause: An approval did not arrive",
          "The approval the run needs was not decided in time. "
          "Next: ask the approver to decide, or continue, change the plan or abort."),
    _spec("pause.review_no_decision", "Pause: The review gave no verdict",
          "The independent review gave no verdict (its model was unavailable or answered without one). "
          "Next: continue to review again; if it repeats, check the review model's setup."),
    _spec("pause.action_failed", "Pause: A platform step failed",
          "A platform step failed for a reason a person can fix (access, configuration, a conflict). "
          "Next: read the step's reason on the run, fix it, then retry the step."),
    _spec("pause.environment_not_ready", "Pause: The working folder is not ready",
          "The working folder cannot run the repository's commands yet (a tool or module is missing). "
          "Next: fix the environment as the pause says, then retry."),
    _spec("pause.workspace_dirty", "Pause: The working folder has foreign changes",
          "The working folder has changes that are not the run's. Next: commit, stash or remove them, then retry."),
    _spec("pause.evidence_unresolved", "Pause: Test evidence could not be matched",
          "The platform could not match the test results to the confirmed tests. "
          "Next: continue to run the phase again; if it repeats, report it (the platform, not the agent, is stuck)."),
    _spec("pause.needs_configuration", "Pause: A setting is missing",
          "The run needs a setting or connection that is missing. "
          "Next: an admin sets it up as the pause says, then continue."),
    _spec("pause.needs_input", "Pause: The run needs an answer",
          "The run cannot decide this itself (e.g. which app of the repository it works on). "
          "Next: name it in the note and continue; the options are listed with the pause."),
    _spec("pause.app_choice", "Pause: Which app the run works on",
          "This repository holds several apps and the work item names none of them: {options}. "
          "Next: continue with the app's folder in the note.", "options"),
    _spec("pause.publish_unverified", "Pause: A publication could not be proven",
          "A publication may have gone out but could not be proven. "
          "Next: check the target, then retry (the run reconciles first) or abort."),
    _spec("pause.audience_unproven", "Pause: The audience is not proven",
          "The run could not prove who received it. "
          "Next: add the receipt, or decide the declared exception, then continue."),
    _spec("pause.acceptance_timeout", "Pause: The acceptance did not arrive",
          "The acceptance the run waits for did not arrive in time. "
          "Next: ask for it, or continue, change the plan or abort."),
    _spec("pause.documentation_missing", "Pause: Documentation is missing",
          'The documentation the run needs is missing. Next: add it, then continue.'),
    _spec("pause.content_blocked", "Pause: Content was blocked",
          "A content guardrail blocked the input or output. "
          "Next: check what was blocked, adjust the input, then continue or abort."),
    _spec("pause.runtime_failed", "Pause: The run's turn could not finish",
          "The run's turn could not finish (the device, the session or the phase stopped). "
          "Next: read the reason on the run, then retry, continue in a new chat or abort."),
    _spec("pause.pipeline_not_for_head", "Pause: The pipeline ran on another tree",
          "The change to push is not the one the pipeline ran green on. "
          "Next: continue to run the pipeline on the current change."),
    _spec("pause.phase_scope_exceeded", "Pause: The phase kept asking for more than it may",
          "The phase was refused the same thing several times. "
          "Next: change the plan (give the phase what it needs) or abort."),
    _spec("pause.protected_path", "Pause: A protected file had to change",
          "The work needs a change to a protected file. "
          "Next: decide whether it may change, change the plan, or abort."),
    _spec("pause.loop_detected", "Pause: The agent repeated itself",
          "The agent repeated the same steps without progress. "
          "Next: continue in a new chat, change the plan or abort."),
    _spec("pause.emergency_stop", "Pause: The emergency stop is on",
          'An admin stopped all runs. Next: wait until the stop is lifted, then continue.'),
    _spec("pause.phase_not_finished", "Pause: the agent ended its turn with the phase unfinished",
          "The agent ended its turn, but the phase's checks did not pass. "
          "Next: read what is open on the run, then run the phase again, change the plan or abort."),
    _spec("pause.phase_stalled", "Pause: the phase made no progress",
          "The phase stopped several times on the same open checks without progress. "
          "Next: read the open checks on the run, then run the phase again with a note, change the plan or abort."),
    _spec("pause.agent_loop", "Pause: the agent repeated itself",
          "The agent repeated the same calls without progress. "
          "Next: continue in a new chat, change the plan or abort."),
    _spec("pause.service_restarted", "Pause: the device service restarted during the turn",
          "The launcher on the device restarted or stopped while the turn ran; the work so far is on the branch. "
          "Next: run the phase again when the device is back."),
    _spec("pause.turn_failed", "Pause: the turn failed on the device or server",
          "The agent's turn failed in its runtime (the code on the run says where). "
          "Next: run the phase again; if it repeats, check the device and its engine."),
    _spec("pause.seat_limit", "Pause: the seat is at its usage limit",
          "The seat reached its usage limit and no model of the same class could take over. "
          "Next: continue when the limit resets, or choose another model or route and continue."),
    _spec("pause.scenarios_failed", "Pause: the hands-on scenarios could not be written",
          "The platform could not write the hands-on scenarios; the built change is not at fault. "
          "Next: retry the step; if it repeats, check the review model's setup."),
    _spec("pause.loop_limit", "Pause: a loop reached its limit",
          "'{loop}' reached its limit: the work went back {used} of {limit} times. Next: read the last round's "
          "reason on the run, then continue once more, change the plan or abort.", "loop", "used", "limit"),
    _spec("pause.checks_failed", "Pause: the checks stayed red", "The checks after '{loop}' failed {used} of "
          "{limit} attempts: not offered as done. Next: read them, retry, re-plan or abort.", "loop", "used", "limit"),
    _spec("pause.needs_approval", "Pause: a change needs a person's approval", "The run wants to change an "
          "expensive path or one outside its approved plan. Next: approve the plan or the path, or change the plan."),
    _spec("pause.budget_limit", "Pause: the run used up its budget",
          "The run used up its budget ({keys}). Next: raise the budget and continue, or abort.", "keys"),
    _spec("system_tests.rule", "System tests: the rule of a building phase",
          'System tests run the app like a user and like CI. The command below starts the app itself (fixtures '
          'in the system test folder) and drives it: HTTP calls for every API endpoint the work item names, and '
          'a real browser for every page it changes. For each acceptance criterion a user or client can '
          'observe, add or extend a test in the system test folder: real server, no mocks, short timeouts. For '
          'every screen the work item builds or changes, save a full-page screenshot under '
          'test-reports/screenshots/ of each state a user reaches: as it opens, empty and filled, and after '
          'each interaction that changes what it shows (a dialog or focus mode opened, a filter applied, an '
          "item added, a page with little content), one file per screen and state named '<screen>-<state>.png' "
          "(for example 'cart-open.png', 'catalog-empty.png'); the independent review sees only "
          'these screenshots. In the same test assert what that state must show: each region under a heading '
          "has its content (the line items under 'Your cart'), the texts are in the chosen language. Look at "
          'every screenshot with Read before you finish: a screen is done when it looks like a finished product '
          "and meets the specification's Look and feel checks (LF1, LF2, ...), not only when its test passes. "
          'Improve what you see until it does: visual anchors drawn as the specification draws them, a clear '
          "visual hierarchy, spacing and type from the design system's scales, aligned grids, backgrounds and "
          'side bars that reach the bottom of the page, designed empty states, no raw values (ISO dates, ids, '
          'keys), no untranslated text or unit and no unstyled browser controls. Every test run, in any form (a '
          "single file, a test filter, piped into tail), starts the app on 127.0.0.1 and this device's Google "
          "Chrome (Playwright's chromium.launch() gets it without a download; pass no channel or executable "
          'path). While you work, run the tests you are changing; before you finish, run the command above with '
          'its whole selection (no file or test filter; {full_run_hint}). The phase finishes only when that '
          'full run after your last change is green with no skipped test. Every system test asserts what the '
          'user sees (assert or expect), a screenshot alone is no test. Never skip, xfail or weaken a system '
          'test to make it pass: if the app cannot start or a browser cannot open, say so in your summary.',
          "full_run_hint"),
    # With the system test left to the pipeline (pipeline_scope agent_system_test), a rule saying "run it before
    # you finish" next to a brief saying "do not run it" makes the agent end phases unfinished.
    _spec("system_tests.pipeline_rule", "System tests: the rule when the pipeline runs them",
          "System tests run the app like a user and like CI. For each acceptance criterion a user can observe, add "
          "or extend a test in the system test folder (real server, no mocks). Do not run the command below "
          "yourself: the pipeline after this phase runs it on every pass and sends a red result back to you with "
          "its output and screenshots. Never skip, xfail or weaken a system test."),
    _spec("system_tests.plain_pipeline_rule", "System tests: the rule of a plain story session, run by the pipeline",
          "The pipeline after this phase runs the system test below on every pass and sends a red result back to "
          "you with its output; do not run it yourself, and never skip, xfail or weaken a system test."),
    _spec("system_tests.plain_rule", "System tests: the rule of a plain story session",
          "The command below starts the app on 127.0.0.1 and this device's Google Chrome (Playwright's "
          "chromium.launch(), no channel or path), like CI. Before you finish run it verbatim, whole selection, until "
          "it is green; never skip, xfail or weaken a system test."),
    _spec("item.appends_rule", "A team work item: shared files it adds to",
          "appends_to names shared files an item you depend on owns (a router, the navigation, translations, a "
          "package's or module's index, the test runner's shared fixtures, the project's manifest): add your own "
          "entries there and keep everything the owner and earlier items wrote."),
    _spec("item.resumed", "A team work item continues in its session",
          "Your work item '{title}' ({item_id}) of run {run_id} continues in this session (iteration {iteration}): "
          "{why}.{merged} Your earlier work still stands; fix what changed, then finish with submit_phase_result. "
          "{read_contract}", "title", "item_id", "run_id", "iteration", "why", "merged", "read_contract"),
    _spec("item.build", "A team work item starts",
          "Build work item '{title}' ({item_id}) of the {workflow_key} run {run_id}: your contract names its "
          "instructions, the paths you own and the team.{merged} Never wait for anyone: when blocked, ask the owner "
          "on the board and finish with submit_phase_result \"blocked\". {read_contract}",
          "title", "item_id", "workflow_key", "run_id", "merged", "read_contract"),
    _spec("item.merged", "A team work item: the story's work was merged with conflicts",
          " The story's current work was merged into your branch and conflicts in {files}: resolve the conflict "
          "markers there (keep both sides' intent) before anything else.", "files"),
    _spec("item.reopened", "A team work item: the default reason it continues", "the coordinator reopened it"),
    _spec("coordinator.board", "The coordinator answers the team's board messages",
          "The team working on this story (run {run_id}) wrote to you on the board: message(s) {messages}. Read them "
          "(board_read; they are addressed to you), answer each one with board_post reply_to=<its id>, and submit a "
          "revised work plan only when the split must change (reopen a blocked item, add or change an item that has "
          "not started). Items still open: {open_items}. Do not change code yourself; end the turn once you "
          "answered.", "run_id", "messages", "open_items"),
    # The launcher's own texts (octryx-claude pipeline.py): sent as the run contract's ``prompt_texts``, filled on the
    # device; the launcher keeps a copy for a hook that has no run contract to read (no run, or the platform is
    # unreachable when it denies a call fail-closed).
    _spec("launcher.pipeline_red", "Launcher: the red pipeline's result in the prompt",
          "The CI pipeline's red result on this change:\n\n{summary}", "summary"),
    _spec("launcher.env_missing", "Launcher: the environment file does not exist",
          "{file} does not exist: declare this story's test commands there (the format of coding_setup.environment: "
          "test, system_test, setup, check, lint, path, browser); the pipeline runs exactly those in {folder}/.",
          "file", "folder"),
    _spec("launcher.env_setup_failed", "Launcher: the environment file's setup failed",
          "the setup of {file} failed in {folder}/:", "file", "folder"),
    _spec("launcher.env_invalid", "Launcher: the environment file is not valid",
          "{file} is not a valid environment file; nothing ran:", "file"),
    # The launcher's own denial texts, sent like the ones above.
    _spec("launcher.wrapper_denied", "Launcher: the agent typed the launcher's own test-run form",
          "`octryx-claude test-run` is the launcher's own form of a test run. Next: run the test command itself "
          "(pytest, python -m pytest, the declared command), piped into tail or grep as you like."),
    _spec("launcher.plain_form", "Launcher: a test run redirected into a file",
          "A test run whose output goes to a file (`>`, `tee`) runs inside the sandbox, where the browser cannot "
          "start. Next: run `{plain}` instead, without redirecting to a file; pipe into tail or grep if you need less "
          "output.", "plain"),
    _spec("launcher.fail_closed", "Launcher: the platform could not confirm a tool call",
          "Octryx could not confirm this tool call{codes}; it is denied (fail closed). Next: ask the user to check "
          "`octryx-claude status`.", "codes"),
    _spec("launcher.proof_unavailable", "Launcher: a confirmation could not be proven",
          'Octryx could not prove this confirmation (hook_signer_unavailable). Next: ask the user to restart '
          'octryx-claude, then confirm again.'),
    _spec("launcher.takeover_denied", "Launcher: an agent tried to decide a takeover",
          'A takeover is confirmed or declined by a person in the Octryx UI (Agents → Claims and handoffs), never by '
          'an agent. Next: tell the person and go on with your own work.'),
    _spec("launcher.patch_format", "Launcher: an unreadable Codex patch",
          "Write files with apply_patch in the shell, exactly this form (one call per change, paths relative to the "
          "repository):\napply_patch <<'PATCH'\n*** Begin Patch\n*** Add File: docs/NEW.md\n+first line\n+second "
          "line\n*** Update File: src/app.py\n@@\n-old line\n+new line\n*** End Patch\nPATCH\nEvery line of an added "
          "file starts with '+'. No JSON, no other markers (only Add File, Update File, Delete File)."),
    # The system test among other commands, refused at once with the plain form.
    _spec("launcher.compound_test", "Launcher: the system test inside a longer command",
          "The system test starts the app and a browser, and the browser starts only outside the sandbox: only a "
          "command that is the test run alone runs there. Next: run `{command} 2>&1 | tail -15` as its own call, and "
          "the other steps before or after it.", "command"),
    # The agent runs the platform's style check the same way and place.
    _spec("launcher.compound_tool", "Launcher: a style tool that cannot run in the sandbox, among other commands",
          "`{tool}` cannot run inside the sandbox (it writes its SDK's cache), so among other commands it fails and "
          "its silence says nothing about your code. Next: run `{tool} <files>` as its own call; it then runs outside "
          "the sandbox, as the platform's own style check does.", "tool"),
    _spec("launcher.style_tools", "Launcher: the platform's style commands in the code map",
          "The platform checks the code style with these commands in `{folder}`; run them the same way, each as its "
          "own call (they then run where the platform's do):", "folder"),
    # Cost lever 3: the app's code map, once per session (launcher code_map).
    _spec("launcher.code_map", "Launcher: the head of the app's code map",
          "Where this app's files are (tracked files; read what you need, no need to list the tree again):"),
    _spec("launcher.sandbox_browser", "Launcher: a browser that cannot start in the sandbox",
          'This cannot run here: Chromium cannot start inside this sandbox, and waiting or retrying does not change '
          'that, so do not schedule a wakeup for it. Next: take a screenshot with `python -m playwright screenshot '
          '--viewport-size 1280,800 http://127.0.0.1:<port>/ <file inside the repository>` (it runs outside the '
          'sandbox, loopback URLs only; start the app first), or skip the visual check and note it in your summary.'),
    # The phase brief, the agent's rules before its first call
    # (``octryx/phase_brief``); each line only when it applies.
    _spec("brief.head", "Phase brief: first line",
          "Phase '{phase}', in short (the platform enforces exactly this):", "phase"),
    _spec("brief.tests_declared", "Phase brief: the declared test command",
          "- Tests: `{command}` in `{folder}` (also as `cd {folder} && {command}`, piped into tail or grep).",
          "command", "folder"),
    _spec("brief.lint_declared", "Phase brief: the declared lint command",
          "- Lint: `{command}` in `{folder}`.", "command", "folder"),
    _spec("brief.tests_undeclared", "Phase brief: no declared test command",
          "- Tests: this repository declares no test command; run its own runner in `{folder}`: {hints}.",
          "folder", "hints"),
    # The system test runs as its own call: inside a longer command it hangs in the sandbox.
    _spec("brief.system_test_alone", "Phase brief: the system test runs as its own call",
          "- System test: run `{command} 2>&1 | tail -15` in `{folder}` as its own call. It starts the app and a "
          "browser, which start only outside the sandbox, and only a command that is the test run alone runs there.",
          "command", "folder"),
    _spec("brief.shell_strict", "Phase brief: the strict shell",
          "- Shell: test and read-only commands only; create and change files with Edit or Write, "
          "never through the shell (no redirection into a file, no heredoc)."),
    _spec("brief.read_only", "Phase brief: a read-only phase",
          "- Files: this phase changes nothing; read, search and run tests only."),
    _spec("brief.write_paths", "Phase brief: the paths the phase may change",
          "- You may change: {paths}.", "paths"),
    _spec("brief.write_any", "Phase brief: the phase may change any file",
          "- You may change any file of the repository, except git's own files and environments (.venv, "
          "node_modules)."),
    _spec("brief.create_paths", "Phase brief: where new files go",
          "- New files only under: {paths}.", "paths"),
    _spec("brief.tests_locked", "Phase brief: tests are locked",
          "- Tests are locked here: make the code pass them, change no test file and no test runner config. "
          "Confirmed tests: {files}.", "files"),
    _spec("brief.tests_writable", "Phase brief: write the failing test, the confirmed ones stay",
          "- Write the failing test yourself (Edit or Write); once the platform confirmed a test it is locked. "
          "Confirmed tests: {files}.", "files"),
    _spec("brief.contract_file", "Phase brief: the pinned environment file",
          "- `{file}` is the run's contract (pinned at preparation): leave it unchanged; the platform runs the "
          "pinned commands.", "file"),
    _spec("brief.platform_confirms", "Phase brief: the platform confirms the reproduction",
          "- The platform confirms your failing test itself: submit the reproduction, it proves the test red on "
          "the base commit. No person confirms it; do not wait for one."),
    _spec("brief.platform_pipeline", "Phase brief: the pipeline after the phase",
          "- After this phase the CI pipeline runs the declared tests on your change and judges green; a red "
          "pipeline comes back to you with the failing tests."),
    _spec("brief.platform_push", "Phase brief: the platform pushes",
          "- The platform commits, pushes and opens the pull request; never push yourself."),
    _spec("brief.checks", "Phase brief: the evidence checked at the end",
          "- At the end the platform checks: {checks}.", "checks"),
    # Run memory: what earlier runs of the app learned, verified by the platform.
    _spec("brief.memory_head", "Phase brief: the run memory's first line",
          "What earlier runs of this app learned (verified by the platform; information, not a rule):"),
    _spec("brief.memory_test_command", "Phase brief: a command that ran green in the pipeline",
          "- Ran green in the platform's pipeline: `{command}`.", "command"),
    _spec("brief.memory_environment_fix", "Phase brief: an environment error and what ran past it",
          "- An environment error stopped an earlier run: {error}. What ran green after it: {ran}.", "error", "ran"),
    _spec("brief.memory_denial", "Phase brief: a refused call and what worked instead",
          "- Refused before ({reason}): `{refused}`. What worked instead: `{worked}`.", "reason", "refused",
          "worked"),
    # Short output (a long test log stays in the context and is paid again in every later call): inform, never
    # refuse.
    _spec("brief.short_output", "Phase brief: print only the result (the pipeline makes the evidence)",
          "- Output: the pipeline after this phase makes the full test evidence itself, so print only the result, "
          "e.g. `{command}`; pipe build, analyze and log output into tail too. A long output is carried in every "
          "later call of this session.", "command"),
    _spec("brief.short_output_general", "Phase brief: print only the result, no command known",
          "- Output: the pipeline after this phase makes the full test evidence itself, so print only the result "
          "(pipe test, build and log output into tail). A long output is carried in every later call of this session."),
    _spec("brief.memory_large_output", "Phase brief: a command whose output was too long",
          "- `{command}` printed {kb} KB in an earlier run: print only its result.", "command", "kb"),
    _spec("brief.memory_large_output_shorter", "Phase brief: a too-long command and the short form that worked",
          "- `{command}` printed {kb} KB in an earlier run; `{shorter}` was enough.", "command", "kb", "shorter"),
    _spec("brief.tail", "Phase brief: last line",
          "Everything else is in workflow_run_status (detail=true)."),
    # Each failed check of a Stop says what to do (octryx/check_remedies);
    # a guard test keeps one text per check type.
    _spec("remedy.no_command", "Remedy: no declared test command known", "the repository's test command"),
    _spec("remedy.tool_called", "Remedy: a tool the phase must call",
          "call {tools} (the platform records the call); for a test run, running the declared test "
          "command `{command}` in the shell counts as run_test_suite.", "command", "tools"),
    _spec("remedy.tool_not_called", "Remedy: a tool the phase must not call",
          "do the step without {tools}; the phase's own tools are in your run contract.", "tools"),
    _spec("remedy.evidence_count", "Remedy: more evidence calls",
          "call {tools} until the phase has the evidence it asks for (each call counts once).", "tools"),
    _spec("remedy.artifact_created", "Remedy: the phase's artefact is missing",
          "submit the phase's result with its tool (your run contract names the output it expects)."),
    _spec("remedy.citations_present", "Remedy: the answer cites no source",
          "cite the sources you used in your answer with their cite_as links."),
    _spec("remedy.urls_cited", "Remedy: too few web sources cited",
          "name the web pages you used as full http(s) links in what you write."),
    _spec("remedy.answer_contains_any", "Remedy: the answer lacks a required term",
          "say it explicitly in your answer (the check names what it looks for)."),
    _spec("remedy.field_present", "Remedy: a required field is missing",
          "submit the result again with every field the check names filled."),
    _spec("remedy.test_command_passed", "Remedy: no green test run after the last change",
          "run the declared test command `{command}` after your last change and make it pass; the "
          "platform records the run.", "command"),
    _spec("remedy.tests_red", "Remedy: the confirmed tests do not fail yet",
          "write or correct the test so it fails for the reason the work item describes, then run "
          "`{command}` to show it red.", "command"),
    _spec("remedy.tests_green", "Remedy: the confirmed tests do not pass yet",
          "change the code (not the confirmed tests) until they pass, then run `{command}` after your"
          " last change.", "command"),
    _spec("remedy.confirmed_tests_intact", "Remedy: a confirmed test changed or is missing",
          "restore the confirmed test as it was confirmed (git restore <file>) and make the code pass it instead."),
    _spec("remedy.ci_green", "Remedy: the CI result is not green",
          "read the CI failure in your run contract, fix it, and finish; the platform reruns CI on "
          "the pushed change."),
    _spec("remedy.reproduces", "Remedy: the reproduction does not show the bug",
          "make the test fail with the bug's symptom (the assertion the work item describes), run "
          "`{command}` to show it red, then submit the reproduction.", "command"),
    _spec("remedy.review_passed", "Remedy: the review has open findings",
          "fix each review finding in your run contract (phase.review_findings), then finish; the "
          "review runs again."),
    _spec("remedy.artefact_review_passed", "Remedy: the artefact review has open findings",
          "revise the artefact for each finding in your run contract, then submit it again."),
    _spec("remedy.slices_merged", "Remedy: a delegated slice is not merged yet",
          "wait for the open slices or resolve their merge conflicts as your run contract names them,"
          " then finish."),
    _spec("remedy.definition_of_ready", "Remedy: the Definition of Ready is incomplete",
          "fill the missing parts of the Definition of Ready the check names, then submit it again."),
    _spec("remedy.specification_ready", "Remedy: the specification is not ready",
          "complete the specification sections the check names, then submit it again."),
    _spec("remedy.ci_findings_addressed", "Remedy: the CI failure is not fixed on fresh evidence",
          "fix the CI failure named in your run contract and run the failing command again after your change."),
    _spec("remedy.evidence_families", "Remedy: an evidence family is unanswered",
          "gather the evidence family the check names for the alert's target and window, then submit it."),
    _spec("remedy.judge", "Remedy: the judge's note (advisory)",
          "read the judge's note and improve what it names; it does not block the phase."),
    _spec("remedy.code_style", "Remedy: the code style found errors",
          "run the command named above in its folder as its own call (it then runs outside the sandbox, as the "
          "platform's did), fix what it reports in the files you changed, and run it again."),
    _spec("remedy.declared_tests", "Remedy: the declared test suite did not run green in full",
          "run `{command}` with its whole selection after your last change and make it green.", "command"),
    _spec("remedy.system_tests", "Remedy: the system tests did not run green in full",
          "run the system test command from your run contract with its whole selection after your "
          "last change and make it green."),
    _spec("remedy.questions_asked", "Remedy: the question round is not done",
          "ask the open questions in one round as your run contract describes, or finish with the "
          "defaults you will use."),
    _spec("remedy.item_result", "Remedy: the work item's result is missing",
          "finish with submit_phase_result: done, or blocked with what you need."),
    # The run event that names the seat turn's model and where it came from.
    _spec("model.chosen", "Models: the seat turn's model and its source", "Model {model} from {source}.",
          "model", "source"),
)

__all__ = ["AREA", "SPECS"]
