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
        check("settings.json registers 8 hook events", len(settings.get("hooks", {})) == 8)
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

        # ---------------------------------------------------------- task ledger
        ledger_cli = [sys.executable, str(project / ".claude/kit/ledger.py")]

        def ledger_json() -> dict:
            return json.loads(run(ledger_cli + ["show", "--json"], project).stdout)

        run(ledger_cli + ["goal", "Add rate limiting to the search endpoint"], project)
        out = hook(project, "prompt", {**sid, "prompt": "ok, let's go with a sliding window instead of a fixed window"})
        ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
        led = ledger_json()
        d_user = next((d for d in led["decisions"] if "sliding window" in d["text"]), {})
        check("user phrase becomes an approved decision", d_user.get("status") == "approved" and d_user.get("by") == "user", json.dumps(led["decisions"]))
        check("prompt hook tells Claude the decision was recorded", "approved decision" in ctx, ctx)
        out = hook(project, "prompt", {**sid, "prompt": "use pandas to load the csv file please"})
        check("plain instruction is not taken as a decision", len(ledger_json()["decisions"]) == 1)

        msg = ("Done with the limiter skeleton.\n\nDecision: key the limiter on the API key, because agents share one IP\n"
               "Dead end: a global token bucket, because one noisy client starved the others\nNext: add the 429 test\n"
               "```\nDecision: lines inside code blocks are ignored\n```")
        hook(project, "stop", {"session_id": "smoke-ledger", "stop_hook_active": False, "last_assistant_message": msg})
        led = ledger_json()
        d_claude = next((d for d in led["decisions"] if "API key" in d["text"]), {})
        check("Decision: line is filed as proposed with its reason", d_claude.get("status") == "proposed" and "share one IP" in d_claude.get("why", ""), json.dumps(led["decisions"]))
        check("Dead end: and Next: lines are filed", led["dead_ends"] and led["dead_ends"][0]["text"].startswith("a global token bucket") and (led.get("next") or {}).get("text") == "add the 429 test")
        check("markers inside code blocks are ignored", not any("ignored" in d["text"] for d in led["decisions"]))

        ask = {**sid, "tool_name": "AskUserQuestion",
               "tool_input": {"questions": [{"question": "Where should limiter state live?", "header": "Storage", "options": [], "multiSelect": False}]},
               "tool_response": {"questions": [], "answers": {"Where should limiter state live?": "Redis"}}}
        hook(project, "post-tool", ask)
        d_ask = next((d for d in ledger_json()["decisions"] if d["text"].startswith("Storage")), {})
        check("AskUserQuestion answer is filed as approved", d_ask.get("text") == "Storage: Redis" and d_ask.get("status") == "approved", json.dumps(d_ask))

        tr = tmp / "transcript.jsonl"
        base = {"sessionId": "smoke-ledger", "cwd": str(project), "timestamp": "2026-11-22T10:00:00"}
        rows = [
            {**base, "type": "user", "message": {"role": "user", "content": "Add rate limiting to the search endpoint so one client cannot flood it"}},
            {**base, "type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "Looking at the endpoint first."},
                {"type": "tool_use", "name": "Edit", "input": {"file_path": str(project / "src/demo/db.py")}}]}},
            {**base, "type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
            {**base, "type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "Base directory for this skill: /x\n# Skill body"}]}},
            {**base, "type": "user", "isMeta": True, "message": {"role": "user", "content": "meta noise"}},
            {**base, "type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": msg}]}},
            {**base, "type": "user", "message": {"role": "user", "content": "keep going and add the 429 test"}},
        ]
        tr.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        hook(project, "pre-compact", {**sid, "trigger": "auto", "transcript_path": str(tr)})
        briefs = list((project / ".claude/kit/briefs").glob("*.md"))
        brief = briefs[0].read_text(encoding="utf-8") if briefs else ""
        check("pre-compact writes a resume brief", bool(briefs))
        check("brief has goal, latest request, files and decisions",
              all(s in brief for s in ("Add rate limiting", "Latest request", "src/demo/db.py", "key the limiter on the API key", "check the files on disk")), brief[:600])
        check("brief skips skill text, tool results and meta entries", "Skill body" not in brief and "meta noise" not in brief)

        out = hook(project, "session-start", {"session_id": "smoke-3", "source": "compact"})
        ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
        check("after compaction the ledger comes back", "Decisions" in ctx and "sliding window" in ctx and "PROPOSED" in ctx and "Dead ends" in ctx, ctx[-800:])
        out = hook(project, "session-start", {"session_id": "smoke-4", "source": "clear"})
        ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
        check("after /clear Claude is pointed to the ledger", "Task ledger for branch" in ctx and "after /clear" in ctx, ctx[-500:])

        pid = d_claude.get("id", "D2")
        run(ledger_cli + ["decide", "key anonymous users by IP", "--why", "they have no API key", "--status", "approved", "--by", "user"], project)
        new_id = ledger_json()["decisions"][-1]["id"]
        run(ledger_cli + ["status", pid, "superseded", "--by", new_id], project)
        led = ledger_json()
        old = next(d for d in led["decisions"] if d["id"] == pid)
        check("change keeps history (superseded_by)", old["status"] == "superseded" and old["superseded_by"] == new_id, json.dumps(old))
        rev = json.loads(run(ledger_cli + ["review", "--json"], project).stdout)
        check("review lists no stale proposals after the change", all(d["id"] != pid for d in rev["proposed"]), json.dumps(rev["proposed"]))
        res = run(ledger_cli + ["brief", "--transcript", str(tr), "--max-chars", "1500"], project)
        check("brief respects its character budget", 0 < len(res.stdout) <= 1501, str(len(res.stdout)))
        run(ledger_cli + ["archive"], project)
        out = hook(project, "session-start", {"session_id": "smoke-5", "source": "clear"})
        check("archived ledger is no longer offered", "Task ledger" not in json.dumps(out), json.dumps(out)[-300:])

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
