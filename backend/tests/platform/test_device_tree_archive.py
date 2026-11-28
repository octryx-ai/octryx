"""Code for a device job goes as a reproducible archive only that device may fetch; what does not fit or is unsafe is
left out and named; results come back as uploads with the same limit."""

from __future__ import annotations

import io
import subprocess
import tarfile

from app.services.devices import tree_archive


def _names(data: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        return [member.name for member in archive.getmembers()]


def test_the_same_content_gives_the_same_archive_and_unsafe_or_large_files_are_named():
    entries = [("shop/b.py", b"b"), ("shop/a.py", b"a"), ("../etc/passwd", b"x"), ("/abs.py", b"x"),
               ("big.bin", b"0" * 30)]
    first = tree_archive.build_archive(entries, name="head", max_file=20)
    again = tree_archive.build_archive(list(reversed(entries)), name="head", max_file=20)
    assert first.sha256 == again.sha256 and first.data == again.data  # reproducible
    assert _names(first.data) == ["shop/a.py", "shop/b.py"]
    assert sorted(first.skipped) == ["../etc/passwd", "/abs.py", "big.bin"]
    total = tree_archive.build_archive([("a", b"12345"), ("b", b"12345")], name="x", max_total=8)
    assert total.skipped == ["b"]


def test_a_git_tree_skips_symlinks_and_reads_the_regular_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@example.invalid"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "app.py").write_text("x = 1\n")
    (repo / "link.py").symlink_to("/etc/passwd")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "c"], check=True)
    archive = tree_archive.build_from_git(repo, "HEAD", name="head")
    assert _names(archive.data) == ["app.py"] and archive.skipped == ["link.py"]


def test_an_offered_archive_is_only_that_device_s_and_uploads_have_a_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTRYX_DEVICE_ARCHIVE_DIR", str(tmp_path))
    archive = tree_archive.build_archive([("a.py", b"a")], name="before")
    offered = tree_archive.offer(archive, device_id="dev-1")
    ident = offered["url"].rsplit("/", 1)[-1]
    assert offered["sha256"] == archive.sha256 and tree_archive.fetch(ident, "dev-1") == archive.data
    assert tree_archive.fetch(ident, "dev-2") is None and tree_archive.fetch("../x", "dev-1") is None
    assert "over the limit" in tree_archive.accept_upload(b"0" * 10, device_id="dev-1", name="r", max_total=5)
    upload = tree_archive.accept_upload(b"sarif", device_id="dev-1", name="report.sarif")
    assert tree_archive.read_upload(upload["id"], "dev-1") == b"sarif" and tree_archive.read_upload(
        upload["id"], "dev-2") is None
