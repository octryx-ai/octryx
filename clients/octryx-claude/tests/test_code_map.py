import subprocess
import uuid

from octryx_claude.code_map import code_map, relevant
from octryx_claude.phase_brief import code_map_once

KEY = str(uuid.UUID(int=21))
FILES = ["coffee/flutter/claude/lib/features/brews/presentation/brew_form_screen.dart",
         "coffee/flutter/claude/lib/features/brews/data/brew_repository.dart",
         "coffee/flutter/claude/lib/features/grinders/grinder_settings.dart",
         "coffee/flutter/claude/lib/main.dart",
         "coffee/flutter/claude/test/features/brews/brew_form_test.dart",
         "coffee/flutter/claude/pubspec.yaml", "coffee/web/index.html"]


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name in FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    return str(tmp_path)


def _contract(title):
    return {"phase": {"title": "Story"}, "work_item": {"title": title},
            "preparation": {"environment": {"app_folder": "coffee/flutter/claude"}}}


def test_the_map_names_the_files_the_work_item_speaks_of_first_and_the_apps_folders(tmp_path):
    root = _repo(tmp_path)
    text = code_map(root, _contract("The brew form should remember the grinder setting"), "HEAD")
    lines = text.splitlines()
    assert lines[0] == "HEAD" and "coffee/web/index.html" not in text  # only the run's app
    relevant_part = text.split("Folders of")[0]
    assert "brew_form_screen.dart" in relevant_part and "grinder_settings.dart" in relevant_part
    assert "main.dart" not in relevant_part
    assert "- coffee/flutter/claude/lib/features/brews/presentation/ (1)" in lines


def test_a_word_in_most_paths_tells_nothing_and_the_map_comes_once_per_session_and_app(tmp_path, state):
    assert relevant([f"a/claude/{name}.dart" for name in "uvwxyz"], "claude crashes") == []
    root = _repo(tmp_path)
    first = code_map_once(state, KEY, _contract("brew"), root, "HEAD")
    assert first.startswith("HEAD")
    assert code_map_once(state, KEY, _contract("brew"), root, "HEAD") == ""
    assert code_map_once(state, KEY, {"phase": None}, root, "HEAD") == ""
