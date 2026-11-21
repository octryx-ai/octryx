"""The guard's vocabulary: command classes, program lists, patterns and the verdict type."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SERVER_BUILD_NOT_ALLOWED = "server_build_not_allowed"
SERVER_BUILD_MESSAGE = (
    "This step builds or tests the repository, which is not allowed on the Octryx server. "
    "Run it on your Mac (choose your device as the run location) — a sandbox for server runs is coming."
)

CLASS_ALLOWED = "read_only"
CLASS_BUILD_TOOL = "build_tool"
CLASS_PACKAGE_MANAGER = "package_manager"
CLASS_TEST_RUNNER = "test_runner"
CLASS_CODE_LOADING_LINTER = "code_loading_linter"
CLASS_INTERPRETER = "interpreter"
CLASS_REPOSITORY_SCRIPT = "repository_script"
CLASS_EXECUTING_OPTION = "executing_option"
CLASS_REPOSITORY_PATH = "repository_path"
CLASS_UNRECOGNIZED = "unrecognized"
CLASS_CLOUD_CLI = "cloud_cli"
CLASS_SECRET_READ = "secret_read"
CLASS_GIT_INTERNALS = "git_internals_write"
CLASS_GIT_COMMAND = "git_command"
CLASS_UNPARSEABLE = "unparseable"

# Build tools and compilers: they evaluate the repository's build definition (plugins, build scripts, recipes).
_BUILD_TOOLS = frozenset({
    "mvn", "mvnw", "mvnd", "gradle", "gradlew", "ant", "sbt", "lein", "bazel", "bazelisk", "buck", "buck2", "pants",
    "make", "gmake", "bmake", "cmake", "ctest", "ninja", "meson", "scons", "xcodebuild", "swift", "msbuild", "dotnet",
    "cargo", "rustc", "go", "gcc", "g++", "cc", "c++", "clang", "clang++", "javac", "kotlinc", "scalac", "tsc",
    "webpack", "vite", "rollup", "esbuild", "parcel", "turbo", "nx", "lerna", "rush", "mix", "rebar3", "cabal",
    "stack", "ghc", "dune", "zig", "nix", "nix-build", "nix-shell", "docker", "podman", "buildah", "earthly",
    "just", "task", "invoke", "rake", "gulp", "grunt", "bundle", "bundler", "setup.py",
})
# Package managers: install runs lifecycle/setup scripts, run/exec/test runs repository scripts.
_PACKAGE_MANAGERS = frozenset({
    "npm", "npx", "pnpm", "pnpx", "yarn", "yarnpkg", "bun", "bunx", "deno", "corepack", "pip", "pip3", "pipx",
    "uv", "uvx", "poetry", "pipenv", "pdm", "hatch", "conda", "mamba", "micromamba", "gem", "composer", "cpan",
    "cpanm", "nuget", "easy_install", "apt", "apt-get", "apk", "yum", "dnf", "brew",
})
_TEST_RUNNERS = frozenset({
    "pytest", "py.test", "tox", "nox", "jest", "vitest", "mocha", "karma", "jasmine", "ava", "playwright",
    "cypress", "phpunit", "rspec", "cucumber", "behave", "robot", "gotestsum", "nosetests", "trial",
})
# Linters and formatters that load code from the repository's configuration (eslint.config.js, mypy plugins,
# pylint load-plugins, flake8 local-plugins, prettier.config.js …).
_CODE_LOADING_LINTERS = frozenset({
    "eslint", "prettier", "stylelint", "mypy", "dmypy", "pylint", "flake8", "tslint", "biome", "oxlint",
})
_INTERPRETERS = frozenset({
    "python", "python3", "python2", "pypy", "pypy3", "node", "nodejs", "ruby", "perl", "php", "lua", "luajit",
    "Rscript", "R", "java", "groovy", "kotlin", "scala", "jshell", "osascript", "pwsh", "powershell", "tclsh",
    "expect", "julia", "erl", "elixir", "iex", "ts-node", "tsx",
})
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "mksh", "fish", "csh", "tcsh", "ash", "busybox"})

# Read-only, text, file, git and network-read tools: they read or move files, they never run the repository.
_ALLOWED_PROGRAMS = frozenset({
    "ls", "cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "ag", "ack", "find", "fd", "tree",
    "wc", "sort", "uniq", "cut", "tr", "sed", "awk", "gawk", "mawk", "nawk", "diff", "diff3", "cmp", "comm", "join",
    "paste", "column", "nl", "fold", "fmt", "tee", "xxd", "od", "hexdump", "strings", "file", "stat", "du", "df",
    "realpath", "readlink", "basename", "dirname", "md5sum", "sha1sum", "sha256sum", "sha512sum", "shasum", "cksum",
    "base64", "jq", "yq", "echo", "printf", "true", "false", "test", "[", "[[", "]]", "pwd", "cd", "pushd", "popd",
    "which", "type", "whereis", "date", "sleep", "mkdir", "rmdir", "touch", "cp", "mv", "rm", "ln", "chmod", "tar",
    "unzip", "zip", "gzip", "gunzip", "zcat", "bzip2", "bunzip2", "xz", "unxz", "git", "curl", "wget", "uname",
    "whoami", "id", "hostname", "export", "unset", "set", "read", "local", "declare", "typeset",
    "readonly", "exit", "return", "shift", "wait", "ps", "uptime", "free", "nproc", "getconf", "locale", "tput",
    "iconv", "dos2unix", "unix2dos", "expand", "unexpand", "rev", "tac", "seq", "split", "csplit", "shuf",
    "numfmt", "expr", "bc", "factor", "dig", "nslookup", "host", "ping",
    # Static formatters and scanners: they parse files, they load no code from the repository's configuration.
    "ruff", "black", "isort", "gofmt", "bandit", "semgrep", "shellcheck", "gitleaks", "hadolint",
})
# Shell keywords that open or close a compound command; the words after an opener are judged as a command.
_OPENING_KEYWORDS = frozenset({"!", "{", "if", "then", "else", "elif", "do", "while", "until", "time"})
_CLOSING_KEYWORDS = frozenset({"}", "fi", "done", "esac"})
# Keywords whose segment is a header of data words (loop variables, case subjects, a function name).
_HEADER_KEYWORDS = frozenset({"for", "case", "select", "function"})
_VERSION_FLAGS = frozenset({"--version", "-version", "-V"})
_SYSTEM_DIRS = ("/bin/", "/usr/bin/", "/usr/local/bin/", "/sbin/", "/usr/sbin/", "/opt/homebrew/bin/")
_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\+?=")
# Variables that make an allowed tool run another program (pager, editor, external diff, preload, PATH).
_EXECUTING_VARIABLE = re.compile(
    r"^(PATH|LD_\w+|DYLD_\w+|BASH_ENV|ENV|PROMPT_COMMAND|LESSOPEN|LESSCLOSE|\w*PAGER|\w*EDITOR|VISUAL|"
    r"GIT_\w+|\w*ASKPASS|PERL5OPT|PERL5LIB|PYTHON\w*|NODE_OPTIONS|NODE_PATH|RUBYOPT|RUBYLIB|JAVA_TOOL_OPTIONS|"
    r"_JAVA_OPTIONS|MAVEN_\w+|GRADLE_\w+|SHELLOPTS|BASHOPTS|IFS)$"
)
# Options with which an allowed tool runs another program.
_EXECUTING_OPTIONS: dict[str, tuple[str, ...]] = {
    "tar": ("--to-command", "--checkpoint-action", "--use-compress-program", "--info-script", "--new-volume-script",
            "-I", "-F"),
    "zip": ("-TT", "--unzip-command"),
    "sort": ("--compress-program",),
    "split": ("--filter",),
    "less": ("+!", "-+"),
    "find": ("-fprintf",),
    "curl": ("-K", "--config"),
    "wget": ("-e", "--execute", "--config"),
}
_GIT_EXECUTING_CONFIG = re.compile(
    r"^(alias\.|core\.(hookspath|fsmonitor|sshcommand|pager|editor|askpass|gitproxy)|.*\.(textconv|command|cmd|"
    r"process|clean|smudge|tool)|diff\.external|sequence\.editor|credential\.helper|filter\.|uploadpack\.|"
    r"protocol\.ext)", re.IGNORECASE,
)
_GIT_EXECUTING_GLOBALS = ("--exec-path", "--config-env", "--upload-pack", "-u")
_AWK_EXECUTING = re.compile(r"system\s*\(|\|\s*getline|\|\s*\"|\|&|print[f]?\b[^;]*\|")
_SED_EXECUTING = re.compile(r"(^|[;{}\n])\s*(\d+|\$|/[^/]*/)?\s*e(\s|$|;)|s(.).*\4.*\4[gpIiMm0-9]*e")
# Cloud and cluster CLIs: in the pod they act with its IRSA role and ServiceAccount (Secrets Manager, S3, cluster).
_CLOUD_CLIS = frozenset({
    "kubectl", "oc", "aws", "eksctl", "gsutil", "gcloud", "bq", "az", "s3cmd", "rclone", "vault", "helm", "crictl",
    "ctr", "nerdctl", "kubectx", "kubens", "k9s", "stern", "kustomize", "argocd", "flux", "terraform", "terragrunt",
    "pulumi", "consul", "nomad", "aws-vault", "session-manager-plugin", "kubeadm", "skopeo", "mc", "azcopy",
})
_ENVIRONMENT_DUMPS = frozenset({"printenv", "compgen"})
# Paths that hold the process environment or a mounted credential (the API's secrets, its ServiceAccount and IRSA
# tokens), in any argument or redirection.
_SECRET_PATH = re.compile(
    r"(^|/)proc/([0-9]+|self|thread-self|\*|[^/]*[$*?\[])(/|$)|(^|/)(var/)?run/secrets(/|$)|"
    r"eks\.amazonaws\.com/serviceaccount|serviceaccount/(token|namespace|ca\.crt)|(^|/)\.aws/(credentials|config)|"
    r"(^|/)\.kube/config|(^|/)\.docker/config\.json|(^|/)etc/shadow", re.IGNORECASE)
# Addresses an HTTP client may not reach from the pod: instance metadata, the cluster, private and loopback hosts.
_INTERNAL_HOST = re.compile(
    r"^(169\.254\.|100\.100\.100\.200$|fd00:ec2::254$|metadata(\.google)?(\.internal)?$|kubernetes(\.default)?|"
    r".*\.svc(\.|$)|.*\.cluster\.local$|.*\.internal$|localhost$|127\.|0\.|10\.|192\.168\.|"
    r"172\.(1[6-9]|2[0-9]|3[01])\.|\[?::1\]?$|\[?f[cd][0-9a-f]{2}:|\[?fe80:|[0-9]+$|0x[0-9a-f]+$)", re.IGNORECASE)
_CURL_REFUSED_OPTIONS = frozenset({"--resolve", "--connect-to", "--unix-socket", "--abstract-unix-socket", "-K",
                                   "--config", "--proxy", "-x", "--preproxy", "--doh-url"})
_WGET_REFUSED_OPTIONS = frozenset({"-i", "--input-file", "-e", "--execute", "--config", "--proxy"})
# git: the subcommands an agent command may run (an unknown name could be an alias of ``.git/config``; git never lets
# an alias shadow these builtins), and the configuration keys with which git runs a program.
_GIT_SUBCOMMANDS = frozenset({
    "status", "log", "diff", "show", "add", "commit", "checkout", "switch", "branch", "fetch", "pull", "push",
    "rev-parse", "ls-files", "ls-tree", "grep", "blame", "stash", "restore", "reset", "merge", "rebase", "tag",
    "remote", "config", "rev-list", "cat-file", "describe", "shortlog", "merge-base", "diff-tree", "show-ref",
    "for-each-ref", "reflog", "name-rev", "ls-remote", "check-ignore", "count-objects", "version", "mv", "rm",
    "cherry-pick", "revert", "apply", "format-patch", "clean", "init", "clone", "symbolic-ref", "whatchanged",
})
_GIT_EXEC_KEY = re.compile(
    r"^(core\.(pager|editor|fsmonitor|hookspath|sshcommand|askpass|gitproxy|alternaterefscommand|attributesfile|"
    r"worktree)|sequence\.editor|gpg\.(.+\.)?program|credential(\..*)?|alias\..*|filter\..*|diff\..*\.(command|"
    r"textconv)|diff\.external|merge\..*\.driver|mergetool\..*|difftool\..*|include\.path|includeif\..*|"
    r"uploadpack\..*|receive\..*|protocol\..*allow|url\..*|http\..*proxy|remote\..*\.(uploadpack|receivepack|"
    r"proxy|vcs)|pager\..*|submodule\..*\.update|man\..*|web\.browser|browser\..*|instaweb\..*|"
    r"interactive\.difffilter|ssh\.variant|.*\.(command|cmd|textconv|driver|program|process|clean|smudge|tool))$",
    re.IGNORECASE)
_GIT_CONFIG_READS = frozenset({"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l", "get", "list",
                               "--show-origin", "--show-scope", "--name-only", "--null", "-z", "--includes",
                               "--no-includes", "--local", "--global", "--system", "--worktree", "--type", "--bool",
                               "--int", "--path", "--default"})
_GIT_CONFIG_WRITE_ONLY = frozenset({"--edit", "-e", "edit", "--rename-section", "rename-section"})
# A path into git's internals (``.git`` itself, anything under it), also behind ``of=`` / ``--target-directory=``.
_GIT_INTERNAL_PATH = re.compile(r"(^|/|=)\.git(/|$)", re.IGNORECASE)
# A write target the lexer cannot judge: expanded at run time (``$X``, ``$(…)``), a glob, a brace or a tilde.
_UNJUDGEABLE_TARGET = re.compile(r"[$`*?\[{~]|(^|/)\.\*")
# Programs that never write a file named in their arguments (a ``.git`` path there is a read).
_PATH_READERS = frozenset({
    "cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "ag", "ack", "ls", "tree", "wc", "stat",
    "file", "du", "diff", "diff3", "cmp", "strings", "od", "hexdump", "md5sum", "sha1sum", "sha256sum", "sha512sum",
    "shasum", "cksum", "realpath", "readlink", "basename", "dirname", "test", "[", "[[", "]]", "echo", "printf",
    "git", "jq", "yq", "nl", "column", "fold", "fmt", "rev", "tac", "comm", "join", "paste", "cut", "tr", "uniq",
})
# Programs whose arguments name the files they write: a target there must be judgeable.
_PATH_WRITERS = frozenset({"cp", "mv", "ln", "install", "tee", "touch", "chmod", "chown", "dd", "mkdir", "truncate",
                           "rmdir", "split", "csplit", "gzip", "gunzip", "bzip2", "bunzip2", "xz", "unxz", "zip"})
_MAX_DEPTH = 6
_HEREDOC = re.compile(r"(?<!<)<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
_HEREDOC_EXPANSION = re.compile(r"\$\(|`")


@dataclass(frozen=True, slots=True)
class ForeignBuildVerdict:
    """The guard's verdict: ``blocked`` with the command class and program that decided it."""

    blocked: bool
    command_class: str
    program: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"blocked": self.blocked, "command_class": self.command_class, "program": self.program,
                "detail": self.detail}


_ALLOW = ForeignBuildVerdict(blocked=False, command_class=CLASS_ALLOWED)


def _blocked(command_class: str, program: str, detail: str) -> ForeignBuildVerdict:
    return ForeignBuildVerdict(blocked=True, command_class=command_class, program=program, detail=detail[:300])
