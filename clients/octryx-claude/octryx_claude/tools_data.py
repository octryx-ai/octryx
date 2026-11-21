"""The tools the launcher brings, pinned: data only (the served wheel carries Python files only).

Everything the platform needs comes with the launcher, installed into the launcher's own
environment, never system-wide. ``pip``: a dependency of the launcher package (pyproject.toml pins the same
version, a test keeps them equal); ``playwright``: a browser Playwright downloads for its pinned version;
``download``: a release archive checked against its sha256 and unpacked into ``<state>/tools/bin``; the
download and the unpacked binary may be at most ``max_bytes`` each. Versions are at least two weeks old when
pinned. The device reports ``{id: version}`` of what it has (``tools.inventory``).
"""

from __future__ import annotations

TOOLS: tuple[dict, ...] = (
    {"id": "ast-grep", "source": "pip", "package": "ast-grep-cli", "version": "0.51.0", "bin": "ast-grep",
     "version_args": ["--version"]},
    {"id": "playwright", "source": "pip", "package": "playwright", "version": "1.64.1"},
    # The platform's Python code style (code_style built_in.json: ``ruff format``, ``ruff check``), the backend's
    # version (backend/uv.lock), never the device's global ruff.
    {"id": "ruff", "source": "pip", "package": "ruff", "version": "0.15.7", "bin": "ruff",
     "version_args": ["--version"]},
    {"id": "chromium", "source": "playwright", "browser": "chromium", "version": "1.64.1"},
    {"id": "gitleaks", "source": "download", "version": "8.30.1", "bin": "gitleaks", "version_args": ["version"],
     "max_bytes": 30_000_000,
     "url": "https://github.com/gitleaks/gitleaks/releases/download/v{version}/gitleaks_{version}_{platform}.tar.gz",
     "sha256": {
         "darwin_arm64": "b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5",
         "darwin_x64": "dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709",
         "linux_arm64": "e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080",
         "linux_x64": "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"}},
    # SAST: opengrep (LGPL-2.1), the binary only; the rules come from the platform
    # as data, from sources whose licence allows passing them on (never the Semgrep registry's). The release
    # publishes Sigstore signatures, no checksum file: the sha256 are of the release assets, taken when pinned.
    {"id": "opengrep", "source": "download", "archive": "raw", "version": "1.33.1", "bin": "opengrep",
     "version_args": ["--version"], "max_bytes": 64_000_000,  # the largest asset is 49.8 MB
     "url": "https://github.com/opengrep/opengrep/releases/download/v{version}/opengrep_{platform}",
     "platforms": {"darwin_arm64": "osx_arm64", "darwin_x64": "osx_x86", "linux_arm64": "manylinux_aarch64",
                   "linux_x64": "manylinux_x86"},
     "sha256": {
         "darwin_arm64": "a17c1881bb40e3214266a7a291cf4f2ae3bc56c1715628b5712d2ec816bc3e2d",
         "darwin_x64": "c3bd18e0d898d44e28419d95dad57c8928bb46ab32889a0ee1f72a87ad9627af",
         "linux_arm64": "d1433f63a90b8bc0b6ad4b498a13b372b856ce9a754a43484ba4920fe2d76dcf",
         "linux_x64": "46e8133cc490f9f50518061590ce2f6be5a08afaeda034471c0ceda4b3899808"}},
    # Dependencies (Apache-2.0); the sha256 are the release's own SHA256SUMS.
    {"id": "osv-scanner", "source": "download", "archive": "raw", "version": "2.7.0", "bin": "osv-scanner",
     "version_args": ["--version"], "max_bytes": 80_000_000,  # the largest asset is 58.9 MB
     "url": "https://github.com/google/osv-scanner/releases/download/v{version}/osv-scanner_{platform}",
     "platforms": {"darwin_arm64": "darwin_arm64", "darwin_x64": "darwin_amd64", "linux_arm64": "linux_arm64",
                   "linux_x64": "linux_amd64"},
     "sha256": {
         "darwin_arm64": "d4926ef8da134332543be276dff157e4c170f99ad91fc48e89448a8816bdf70b",
         "darwin_x64": "e82c5df7ab0a42dff29a1cd0660711447b56b4c0483ff66ad8634df10fd81a45",
         "linux_arm64": "4061ef4c021ed3c47f203b818f337e351336cc5cd67c0274fc36bd1dfc728dd7",
         "linux_x64": "160c6253e2922e9e0a6a9771c5c4c40a4b3c6090b34a3cdd5e80c96cc2e4218b"}},
)
