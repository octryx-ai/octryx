"""The repository fixture writer shared by the test_code_intelligence_* modules."""

from __future__ import annotations

from pathlib import Path


def _write_repo_fixture(repo_root: Path) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "app.py").write_text(
        "from fastapi import FastAPI\n"
        "\n"
        "app = FastAPI()\n"
        "\n"
        "class Greeter:\n"
        "    def hello(self) -> str:\n"
        "        return helper()\n"
        "\n"
        "def helper() -> str:\n"
        "    return 'hello world'\n"
        "\n"
        "@app.get('/hello')\n"
        "def hello_route() -> str:\n"
        "    return helper()\n",
        encoding="utf-8",
    )
    (repo_root / "src" / "usage.py").write_text(
        "from app import Greeter, helper\n"
        "\n"
        "def use_helper() -> str:\n"
        "    greeter = Greeter()\n"
        "    return greeter.hello() + ' / ' + helper()\n",
        encoding="utf-8",
    )
    (repo_root / "web.ts").write_text(
        "import { renderGreeting } from './view';\n"
        "export function webHandler(): string {\n  return renderGreeting();\n}\n"
        "router.get('/web', webHandler);\n",
        encoding="utf-8",
    )
    (repo_root / "view.ts").write_text(
        "export function renderGreeting(): string {\n  return 'hello';\n}\n",
        encoding="utf-8",
    )
    (repo_root / "GreetingController.java").write_text(
        "import org.springframework.web.bind.annotation.GetMapping;\n"
        "class GreetingController {\n"
        "  @GetMapping(\"/java\")\n"
        "  public String javaRoute() {\n"
        "    return javaService();\n"
        "  }\n"
        "  public String javaService() { return \"hello\"; }\n"
        "}\n",
        encoding="utf-8",
    )
