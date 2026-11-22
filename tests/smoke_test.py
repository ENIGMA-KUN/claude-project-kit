#!/usr/bin/env python3
"""End-to-end smoke test for the project kit.

Creates a throwaway Python project in a temp folder, installs the kit, then
exercises the graph engine and every hook event with realistic hook input.

    python tests/smoke_test.py          # exit 0 when every check passes
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
RESULTS: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))


def run(args: list, cwd: Path, stdin: str = "", env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, text=True, encoding="utf-8", env=env)


def hook(project: Path, event: str, payload: dict) -> dict:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    res = run([sys.executable, str(project / ".claude/hooks/kit_hook.py"), event], project, json.dumps(payload), env)
    if res.returncode != 0:
        return {"_error": res.stderr}
    return json.loads(res.stdout) if res.stdout.strip() else {}


def make_project(root: Path) -> Path:
    p = root / "demo-app"
    (p / "src" / "demo").mkdir(parents=True)
    (p / "tests").mkdir()
    (p / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.1.0"\n', encoding="utf-8")
    (p / "src" / "demo" / "__init__.py").write_text("", encoding="utf-8")
    (p / "src" / "demo" / "db.py").write_text("def connect():\n    return None\n", encoding="utf-8")
    (p / "tests" / "test_db.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (p / "README.md").write_text("# Demo\n\nA demo app.\n", encoding="utf-8")
    if shutil.which("git"):
        run(["git", "init", "-q"], p)
        run(["git", "add", "."], p)
        run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], p)
    return p


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="kit-smoke-"))
    try:
        project = make_project(tmp)
        kg = [sys.executable, str(project / ".claude/kit/kg.py"), "--root", str(project)]

        res = run([sys.executable, str(KIT / "install.py"), str(project), "--python-cmd", "python"], tmp)
        check("installer runs", res.returncode == 0, res.stdout + res.stderr)
        for rel in ["CLAUDE.md", ".claude/settings.json", ".claude/hooks/kit_hook.py", ".claude/kit/kg.py",
                    ".claude/skills/kit-init/SKILL.md", ".claude/agents/verifier.md", "knowledge/index.md",
                    "knowledge/decisions/use-project-kit.md", ".claude/constitution.md"]:
            check(f"installed {rel}", (project / rel).exists())
        settings = json.loads((project / ".claude/settings.json").read_text(encoding="utf-8"))
        check("settings.json registers 7 hook events", len(settings.get("hooks", {})) == 7)
        cfg = json.loads((project / ".claude/kit/config.json").read_text(encoding="utf-8"))
        check("config records kit_home", cfg.get("kit_home") == str(KIT))
        check(".gitignore has kit block", "project-kit: local state" in (project / ".gitignore").read_text(encoding="utf-8"))
        node = (project / "knowledge/decisions/use-project-kit.md").read_text(encoding="utf-8")
        check("date placeholders substituted", "{{" not in node)

        res = run(kg + ["validate"], project)
        check("fresh install validates without errors", res.returncode == 0, res.stdout)

        res = run(kg + ["new", "lesson", "use-uv-not-pip", "--title", "Use uv, not pip",
                        "--description", "pip installs into the global interpreter; uv manages the venv",
                        "--rule", "Run uv sync and uv run; never call pip install directly", "--source", "smoke test"], project)
        check("kg new lesson", res.returncode == 0, res.stderr)
        lesson = project / "knowledge/lessons/use-uv-not-pip.md"
        text = lesson.read_text(encoding="utf-8").replace("trigger: []", "trigger: [pip install, ModuleNotFoundError]")
        text = text.replace("paths: []", "paths: [pyproject.toml]").replace("tags: []", "tags: [python, tooling]")
        lesson.write_text(text, encoding="utf-8")
        run(kg + ["new", "architecture", "database", "--title", "Database layer",
                  "--description", "Connection handling in src/demo/db.py"], project)
        arch = project / "knowledge/architecture/database.md"
        arch.write_text(arch.read_text(encoding="utf-8").replace("paths: []", "paths: [src/demo/db.py]"), encoding="utf-8")
        run(kg + ["build"], project)
        res = run(kg + ["validate"], project)
        check("graph with new nodes validates", res.returncode == 0, res.stdout)
        res = run(kg + ["query", "pip install fails with ModuleNotFoundError", "--json"], project)
        hits = json.loads(res.stdout or "[]")
        check("BM25 query finds the lesson", bool(hits) and hits[0]["id"] == "lessons/use-uv-not-pip", res.stdout[:300])
        check("index.md lists the lesson", "Use uv, not pip" in (project / "knowledge/index.md").read_text(encoding="utf-8"))

        bad = project / "knowledge/lessons/broken.md"
        bad.write_text("---\ntype: lesson\ntitle: Broken\nstatus: active\nrelations:\n  depends_on: [architecture/missing]\n---\nkey: AKIA" + "A" * 16 + "\n", encoding="utf-8")
        res = run(kg + ["validate"], project)
        check("validate flags missing strong edge and secret", res.returncode == 1 and "does not exist" in res.stdout and "secret" in res.stdout, res.stdout)
        bad.unlink()

        sid = {"session_id": "smoke-1"}
        out = hook(project, "session-start", {**sid, "source": "startup"})
        ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
        check("session-start suggests /kit-init before init", "/kit-init" in ctx, json.dumps(out))
        check("session-start lists recent lesson", "uv" in ctx, ctx)

        out = hook(project, "prompt", {**sid, "prompt": "no, that's wrong, pip install keeps failing with ModuleNotFoundError again"})
        ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
        check("prompt hook detects the correction", "correcting" in ctx, json.dumps(out))
        check("prompt hook injects the matching lesson", "lessons/use-uv-not-pip" in ctx, ctx)
        out = hook(project, "prompt", {**sid, "prompt": "pip install ModuleNotFoundError once more please"})
        ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
        check("prompt hook does not repeat a node in one session", "use-uv-not-pip" not in ctx, ctx)
        out = hook(project, "prompt", {**sid, "prompt": "add a dark mode toggle to the settings page"})
        check("unrelated prompt injects nothing", out == {}, json.dumps(out))

        def decision(payload: dict) -> str:
            return hook(project, "pre-tool", {**sid, **payload}).get("hookSpecificOutput", {}).get("permissionDecision", "")

        check("guard denies rm -rf /", decision({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}) == "deny")
        check("guard allows rm -rf ./build", decision({"tool_name": "Bash", "tool_input": {"command": "rm -rf ./build"}}) == "")
        check("guard denies force push to main", decision({"tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}}) == "deny")
        check("guard asks on git reset --hard", decision({"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD~1"}}) == "ask")
        check("guard asks on reading .env", decision({"tool_name": "Bash", "tool_input": {"command": "cat .env"}}) == "ask")
        check("guard ignores .env.example", decision({"tool_name": "Bash", "tool_input": {"command": "cp .env.example .env.sample"}}) == "")
        check("guard allows ls", decision({"tool_name": "Bash", "tool_input": {"command": "ls -la"}}) == "")
        check("guard denies PowerShell recursive delete of a drive", decision({"tool_name": "PowerShell", "tool_input": {"command": "Remove-Item -Recurse -Force C:\\"}}) == "deny")
        check("guard asks before editing the constitution", decision({"tool_name": "Edit", "tool_input": {"file_path": str(project / ".claude/constitution.md"), "old_string": "a", "new_string": "b"}}) == "ask")
        secret = "api_key = sk-" + "a1B2c3D4" * 4
        check("guard denies a secret written into knowledge", decision({"tool_name": "Write", "tool_input": {"file_path": str(project / "knowledge/lessons/x.md"), "content": secret}}) == "deny")
        check("guard allows a placeholder in knowledge", decision({"tool_name": "Write", "tool_input": {"file_path": str(project / "knowledge/lessons/x.md"), "content": "api_key = ${API_KEY}"}}) == "")

        fail = {**sid, "tool_name": "Bash", "tool_input": {"command": "pytest -q"}, "error": "Exit code 1\nImportError: cannot import name 'connect' from 'demo.db' (/tmp/x/src/demo/db.py)"}
        outs = [hook(project, "tool-failure", fail) for _ in range(3)]
        check("first two identical failures stay quiet", outs[0] == {} and outs[1] == {}, json.dumps(outs[:2]))
        check("third identical failure triggers the loop budget", "Loop budget" in json.dumps(outs[2]), json.dumps(outs[2]))

        out = hook(project, "stop", {**sid, "stop_hook_active": False})
        check("stop suggests /reflect after friction", "/reflect" in out.get("systemMessage", ""), json.dumps(out))
        out = hook(project, "stop", {**sid, "stop_hook_active": False})
        check("stop nudges only once per session", out == {}, json.dumps(out))
        hook(project, "pre-compact", {**sid, "trigger": "auto"})
        hook(project, "session-end", {**sid, "reason": "exit"})

        res = run(kg + ["signals", "--days", "1", "--json"], project)
        sig = json.loads(res.stdout)
        check("signals record failures, corrections, injections", sig["events"].get("tool_failure") == 3 and sig["events"].get("correction") == 1 and sig["events"].get("injected", 0) >= 1, json.dumps(sig["events"]))
        lesson_row = next((r for r in sig["lessons"] if r["id"] == "lessons/use-uv-not-pip"), {})
        check("lesson effectiveness is measured", lesson_row.get("injected", 0) >= 1, json.dumps(lesson_row))
        check("signals are redacted on disk", "sk-a1B2" not in (project / ".claude/kit/signals/events.jsonl").read_text(encoding="utf-8"))

        res = run(kg + ["doctor", "--json"], project)
        doc = json.loads(res.stdout)
        check("doctor sees registered hooks", doc.get("hooks_registered") is True, res.stdout)
        res = run(kg + ["codemap"], project)
        cmap = (project / ".claude/kit/code-map.yaml").read_text(encoding="utf-8")
        check("codemap lists manifests and languages", "pyproject.toml" in cmap and "python" in cmap, cmap[:400])
        res = run(kg + ["mermaid"], project)
        check("mermaid export", res.stdout.startswith("flowchart"), res.stdout[:200])

        (project / "CLAUDE.md").write_text("# Demo\n\nMy own instructions.\n", encoding="utf-8")
        res = run([sys.executable, str(KIT / "install.py"), str(project), "--python-cmd", "python"], tmp)
        check("re-install keeps the user's CLAUDE.md", (project / "CLAUDE.md").read_text(encoding="utf-8").startswith("# Demo\n\nMy own"))
        check("re-install puts the new CLAUDE.md in incoming", (project / ".claude/kit/incoming/CLAUDE.md").exists(), res.stdout)
        out = hook(project, "session-start", {"session_id": "smoke-2", "source": "startup"})
        check("session-start reports incoming files", "incoming" in json.dumps(out), json.dumps(out))

        res = run([sys.executable, str(project / ".claude/hooks/kit_hook.py"), "prompt"], project, "not json at all",
                  {**os.environ, "CLAUDE_PROJECT_DIR": str(project)})
        check("hooks fail open on bad input", res.returncode == 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
