"""octryx plugin: check and pack a plugin package the way Octryx checks it at import (also for CI).

    python scripts/octryx_plugin.py validate <folder|package.zip>
    python scripts/octryx_plugin.py pack <folder> [<out.zip>]

``validate`` runs exactly the import checks (manifest, skills, workflows, roles, settings schema, declared writes) and
the skill scanner, and prints what an installer will be asked to confirm. Exit code 0 = installable content,
1 = issues, 2 = usage. ``pack`` validates first and writes a zip with the package at its root.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.plugins.install import permissions, skill_findings  # noqa: E402
from app.services.plugins.package import PackageError, files_from_folder, files_from_zip, read_package  # noqa: E402


def _load(target: Path):
    files = files_from_zip(target.read_bytes()) if target.is_file() else files_from_folder(target)
    return read_package(files)


def validate(target: Path) -> int:
    try:
        package = _load(target)
    except PackageError as error:
        print(f"✗ {target}: {len(error.issues)} issue(s)")
        for item in error.issues:
            where = f" [{item['path']}]" if item.get("path") else ""
            print(f"  - {item['code']}: {item['message']}{where}")
        return 1
    manifest, granted = package.manifest, permissions(package)
    print(f"✓ {manifest.id} {manifest.version} ({manifest.name}, {manifest.publisher})  {package.digest}")
    print(f"  skills: {', '.join(s['name'] for s in granted['skills']) or '-'}")
    print(f"  workflows: {', '.join(w['key'] for w in granted['workflows']) or '-'}")
    print(f"  roles: {', '.join(r['key'] for r in granted['roles']) or '-'}"
          f"  functions: {', '.join(f['key'] for f in granted['functions']) or '-'}")
    print(f"  mcp servers: {', '.join(s['name'] + ' ' + s['url'] for s in granted['mcp_servers']) or '-'}")
    print(f"  uses: {', '.join(granted['connections']) or '-'}  writes: {', '.join(granted['writes']) or '-'}"
          f"  egress: {', '.join(granted['egress']) or '-'}")
    blocking = 0
    for name, findings in skill_findings(package).items():
        for item in findings:
            blocking += bool(item.get("blocks"))
            print(f"  finding {name}: {item['severity']} {item['rule']}: {item['message']}"
                  + (" (blocks the install)" if item.get("blocks") else ""))
    return 1 if blocking else 0


def pack(folder: Path, out: Path | None) -> int:
    if validate(folder):
        return 1
    package = _load(folder)
    out = out or Path(f"{package.manifest.id}-{package.manifest.version}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(package.files.items()):
            archive.writestr(path, data)
    print(f"→ {out}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "validate":
        return validate(Path(argv[1]))
    if len(argv) >= 2 and argv[0] == "pack":
        return pack(Path(argv[1]), Path(argv[2]) if len(argv) > 2 else None)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
