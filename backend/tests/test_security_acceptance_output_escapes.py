"""Review escapes, kubectl file-reading outputs and string escapes are refused while bound and inline reads stay allowed."""

from __future__ import annotations

import pytest

from app.services.exec_policy import DEFAULT_EXEC_POLICY_CONFIG
from app.tools import kubernetes

# --- Flag-scanning counterexamples ------------------------------------------------------------------------
# ``--`` consumed as a flag VALUE must not end flag scanning; a standalone ``--`` is ambiguous here
# (fail closed). Packed short flags are parsed per character like pflag (``-As…`` hides ``-s``).
# Leading environment assignments, wrappers and path-qualified binaries on read-only paths.
from app.tools.kubernetes_kubectl_argv import kubectl_is_read_only  # noqa: E402
from app.tools.runtime_impl._runtime_kubectl_tool import RunKubectlCommandTool
from tests.security_acceptance_support import _context, _diagnosis_report, _gateway, runtime  # noqa: F401

# --- Closed allowlist of read commands ----------------------------------------------------------------
# The read commands are a CLOSED allowlist: exact options with known arity, '--' makes every later word an
# operand, abbreviations of long options (GNU getopt_long accepts unambiguous prefixes) and unknown
# options fail closed. Verified effects (private temp dir only): ``uniq -- input -output`` and
# ``sort --out=output input`` create the output file.
REVIEW6_ESCAPES = [
    "uniq -- input -output",
    "uniq -- -input output",
    "uniq -c -- in out",
    "sort --out=output input",
    "sort --outp output input",
    "sort --compress-prog=sh input",
    "sort --compress=sh input",
    "sort -T /tmp/x input",
    "sort --temporary-directory=/tmp/x input",
    "sort --files0-from=list",
    "sort --random-source=/dev/x input",
    "wc --files0-from=list",
    "wc --files0=list",
    "rg --pr=sh pattern",
    "rg --pre-g='*' pattern",
    "rg --search-z pattern",
    "rg --hostname-bin=sh pattern",
    "rg --unknown-option pattern",
    "sed --in-pl 's/a/b/' a",
    "sed --expr='w /tmp/x' a",
    "sed --file=script a",
    "sed -- -n a",
    "find . -fpr /tmp/x",
    "find . -newerXY x",
    "find . -unknownprimary",
    "date -s 2020-01-01",
    "date --set=2020-01-01",
    "date --se=2020-01-01",
    "date 0101000020",
    "date -f dates.txt",
    "head --unknown a",
    "tail --unknown a",
    "cat --unknown a",
    "ls --unknown",
    "printenv --unknown",
    "id --unknown",
    "whoami extra",
    "pwd --unknown",
]


REVIEW6_READS = [
    "uniq -c in",
    "uniq -- in",
    "sort -u -k2,2 -t, in",
    "sort --unique --key=2,2 --field-separator=, in",
    "sort -- -in",
    "wc -l a b",
    "head -n 20 a",
    "head -5 a",
    "tail -n +5 a",
    "tail -f log",
    "cat -n a",
    "ls -la",
    "ls --color=never -1",
    "rg -n -i --glob '*.py' pattern src",
    "rg --type py -e pattern",
    "find . -maxdepth 2 -name '*.py' -type f -print",
    "find . -name a -o -name b -prune",  # grouping parens are shell separators to the parser: refused
    "date +%Y-%m-%d",
    "date -u",
    "date --date=yesterday +%F",
    "printenv HOME",
    "id -u",
    "whoami",
    "pwd",
    "echo --anything goes",
    "sed -n 1,5p a",
]


# kubectl output forms that read arbitrary local files are refused; inline forms stay reads.
KUBECTL_FILE_OUTPUTS = [
    ["get", "pods", "-o", "go-template-file=/tmp/canary"],
    ["get", "pods", "-ogo-template-file=/tmp/canary"],
    ["get", "pods", "--output=go-template-file", "--template=/tmp/canary"],
    ["get", "pods", "-o", "jsonpath-file=/tmp/canary"],
    ["get", "pods", "--output", "jsonpath-file", "--template", "/tmp/canary"],
    ["get", "pods", "-o", "custom-columns-file=/tmp/canary"],
    ["get", "pods", "-o", "templatefile=/tmp/canary"],
    ["events", "-o", "go-template-file=/tmp/canary"],
    ["auth", "whoami", "-o", "jsonpath-file=/tmp/canary"],
    ["get", "pods", "-o", "unknown-format"],
]


KUBECTL_INLINE_OUTPUTS = [
    ["get", "pods", "-o", "json"],
    ["get", "pods", "-oyaml"],
    ["get", "pods", "-o", "wide"],
    ["get", "pods", "-o", "name"],
    ["get", "pods", "-o", "jsonpath={.items[*].metadata.name}"],
    ["get", "pods", "-o=jsonpath={.items[0]}"],
    ["get", "pods", "-o", "go-template={{range .items}}{{.metadata.name}}{{end}}"],
    ["get", "pods", "-o", "go-template", "--template={{.kind}}"],
    ["get", "pods", "-o", "custom-columns=NAME:.metadata.name"],
    ["version", "-o", "json"],
]


# --- Output and template values -----------------------------------------------------------------------
# Every spelling, repetition and order of the output/template values; classification counts them
# as writes (not reads) too.
R6_1_FILE_OUTPUT_FORMS = [
    ["get", "pods", "-o=go-template-file=/tmp/canary"],
    ["get", "pods", "--output", "go-template-file=/tmp/canary"],
    ["get", "pods", "--template=/tmp/canary", "--output=go-template-file"],
    ["get", "pods", "--template", "/tmp/canary", "-o", "jsonpath-file"],
    ["get", "pods", "-o", "json", "-o", "go-template-file=/tmp/canary"],
    ["get", "pods", "-o", "go-template-file=/tmp/canary", "-o", "json"],
    ["get", "pods", "-ojsonpath-file=/tmp/canary"],
    ["get", "pods", "--output=custom-columns-file=/tmp/canary"],
]


# The same completeness on the string paths.
R6_23_STRING_ESCAPES = [
    "uniq in out",
    "uniq -c in out",
    "uniq -- in out",
    "uniq in -- out",
    "uniq -c -- -in -out",
    "sort --o=out in",
    "sort --ou out in",
    "sort --output out in",
    "sort -oout in",
    "sort -u -o out in",
    "sort --compress-program=sh in",
    "sort --comp=sh in",
    "sort -k",
    "sort --key",
]


@pytest.mark.parametrize("command", REVIEW6_ESCAPES)
def test_review6_escapes_are_refused_on_helper_and_gateway(command):
    from app.services.security_analyzer.builtins import read_only_command_finding

    assert read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG).action != "allow", command
    decision = _gateway(command)
    assert decision is not None and decision.decision == "deny", command


@pytest.mark.asyncio
@pytest.mark.parametrize("command", REVIEW6_ESCAPES)
async def test_review6_escapes_are_refused_on_platform_bash(monkeypatch, command):
    assert (await _diagnosis_report(monkeypatch, "bash", command)).action != "allow"


@pytest.mark.parametrize("command", REVIEW6_READS)
def test_review6_bound_reads_stay_allowed(command):
    from app.services.security_analyzer.builtins import read_only_command_finding

    assert read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG).action == "allow", command
    assert _gateway(command) is None, command


def test_a_configured_read_command_without_an_option_binding_fails_closed():
    from app.services.security_analyzer.builtins import read_only_command_finding

    config = {**DEFAULT_EXEC_POLICY_CONFIG,
              "diagnosis_read_only_commands": [*DEFAULT_EXEC_POLICY_CONFIG["diagnosis_read_only_commands"], "awk"]}
    assert read_only_command_finding("awk 'BEGIN{system(\"touch /tmp/x\")}'", config).action != "allow"


@pytest.mark.asyncio
@pytest.mark.parametrize("args", KUBECTL_FILE_OUTPUTS, ids=" ".join)
async def test_kubectl_file_reading_outputs_are_refused_on_every_path(monkeypatch, runtime, args):  # noqa: F811
    import shlex

    assert kubectl_is_read_only(args) is False
    returncode, _, _ = await kubernetes._run_kubectl(_context(), args)
    tool = await RunKubectlCommandTool().execute({"args": list(args)}, _context())
    assert returncode == 1 and tool.get("error") and runtime.commands == []
    report = await _diagnosis_report(monkeypatch, "run_kubectl", ["kubectl", "--context", "demo", *args])
    assert report.action != "allow"
    decision = _gateway("kubectl --context=dev " + shlex.join(args))
    assert decision is not None and decision.decision == "deny"


@pytest.mark.parametrize("args", KUBECTL_INLINE_OUTPUTS, ids=" ".join)
def test_kubectl_inline_outputs_stay_reads(args):
    import shlex

    assert kubectl_is_read_only(args) is True
    assert _gateway("kubectl --context=dev " + shlex.join(args)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("args", KUBECTL_FILE_OUTPUTS + R6_1_FILE_OUTPUT_FORMS, ids=" ".join)
async def test_r6_1_file_outputs_are_refused_on_all_paths_incl_classification(monkeypatch, runtime, args):  # noqa: F811
    import shlex

    from app.services.classification_tool_policy import tool_writes as writes
    from app.services.security_analyzer.builtins import read_only_command_finding

    assert kubectl_is_read_only(args) is False
    assert writes("run_kubectl", {"args": args}) is True
    assert read_only_command_finding("kubectl " + shlex.join(args), DEFAULT_EXEC_POLICY_CONFIG).action != "allow"
    returncode, _, _ = await kubernetes._run_kubectl(_context(), args)
    tool = await RunKubectlCommandTool().execute({"args": list(args)}, _context())
    assert returncode == 1 and tool.get("error") and runtime.commands == []
    decision = _gateway("kubectl --context=dev " + shlex.join(args))
    assert decision is not None and decision.decision == "deny"


@pytest.mark.asyncio
async def test_r6_1_inline_outputs_run_on_the_runner_and_tool(runtime):  # noqa: F811
    # A template format runs where no container env can be printed (on pods it is refused, kubernetes_env_mask).
    returncode, _, _ = await kubernetes._run_kubectl(_context(), ["get", "nodes", "-o", "jsonpath={.items[*]}"])
    tool = await RunKubectlCommandTool().execute({"args": ["get", "pods", "-o", "yaml"]}, _context())

    assert returncode == 0 and tool.get("exit_code") == 0
    assert len(runtime.commands) == 2


@pytest.mark.parametrize("command", R6_23_STRING_ESCAPES)
def test_r6_2_3_uniq_operands_and_sort_options_are_closed(command):
    from app.services.security_analyzer.builtins import read_only_command_finding

    assert read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG).action != "allow", command
    decision = _gateway(command)
    assert decision is not None and decision.decision == "deny", command
