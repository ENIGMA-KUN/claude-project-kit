#!/usr/bin/env python3
"""Install or upgrade the project kit in a repository.

    python install.py [TARGET] [--python-cmd CMD] [--global] [--dry-run]

TARGET defaults to the current directory. The installer never overwrites files
you own. Kit-managed files (engine, hook dispatcher, skills, agents, schema) are
upgraded in place with a backup. Files you own that already exist (CLAUDE.md,
.claude/settings.json, .claude/constitution.md) get the new version written to
.claude/kit/incoming/ so /kit-init --refresh can merge it with you.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

KIT_HOME = Path(__file__).resolve().parent
TEMPLATE = KIT_HOME / "template"

# Upgraded in place (old copy backed up) on every install.
MANAGED = [
    ".claude/kit/kg.py",
    ".claude/kit/ledger.py",
    ".claude/kit/runlog.py",
    ".claude/kit/review.py",
    ".claude/kit/upkeep.py",
    ".claude/hooks/kit_hook.py",
    ".claude/rules/knowledge-authoring.md",
    ".claude/agents/verifier.md",
    ".claude/agents/curator.md",
    "knowledge/_schema.md",
]
MANAGED_PREFIXES = [".claude/skills/"]

# Owned by the user once installed; a newer kit version goes to .claude/kit/incoming/.
MERGE_VIA_INCOMING = ["CLAUDE.md", ".claude/settings.json", ".claude/constitution.md"]

GITIGNORE_MARKER = "# project-kit: local state"
GITIGNORE_LINES = [
    ".claude/kit/signals/",
    ".claude/kit/state/",
    ".claude/kit/handoffs/",
    ".claude/kit/ledger/",
    ".claude/kit/briefs/",
    ".claude/kit/reviews/",
    ".claude/kit/backup/",
    ".claude/kit/incoming/",
    ".claude/settings.local.json",
    "CLAUDE.local.md",
    "knowledge/_graph.json",
]


def is_managed(rel: str) -> bool:
    return rel in MANAGED or any(rel.startswith(p) for p in MANAGED_PREFIXES)


def substitute(rel: str, text: str, py: str) -> str:
    today = dt.date.today()
    if rel.startswith("knowledge/"):
        text = text.replace("{{DATE}}", str(today))
        text = text.replace("{{REVIEW_DATE}}", str(today + dt.timedelta(days=90)))
    if rel == "CLAUDE.md":
        text = text.replace("{{PY}}", py)
    if rel == ".claude/settings.json" and py != "python":
        text = text.replace('"command": "python ', f'"command": "{py} ')
    return text


def merge_missing(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if k not in dst:
            dst[k] = v
        elif isinstance(dst[k], dict) and isinstance(v, dict):
            merge_missing(dst[k], v)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description="Install the project kit into a repository")
    ap.add_argument("target", nargs="?", default=".")
    ap.add_argument("--python-cmd", default="", help="interpreter command the hooks should use (default: auto)")
    ap.add_argument("--global", dest="global_", action="store_true", help="also install the /kit-adopt skill for all projects")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"target folder not found: {target}")
        return 1
    if target == KIT_HOME or KIT_HOME in target.parents:
        print("refusing to install the kit into its own folder")
        return 1
    py = args.python_cmd or ("python" if sys.platform == "win32" else "python3")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = target / ".claude" / "kit" / "backup" / stamp
    incoming_dir = target / ".claude" / "kit" / "incoming"
    already = (target / ".claude" / "kit" / "config.json").exists()

    created, upgraded, incoming, kept = [], [], [], []

    for src in sorted(TEMPLATE.rglob("*")):
        if src.is_dir() or "__pycache__" in src.parts or src.suffix == ".pyc":
            continue
        rel = src.relative_to(TEMPLATE).as_posix()
        dst = target / rel
        if rel == ".claude/kit/config.json":
            continue  # merged below
        is_text = src.suffix in {".md", ".py", ".json", ".yaml", ".yml", ".txt", ""}
        new_bytes = substitute(rel, src.read_text(encoding="utf-8"), py).encode("utf-8") if is_text else src.read_bytes()

        if not dst.exists():
            created.append(rel)
            if not args.dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(new_bytes)
            continue
        if dst.read_bytes() == new_bytes:
            continue
        if is_managed(rel):
            upgraded.append(rel)
            if not args.dry_run:
                (backup_dir / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, backup_dir / rel)
                dst.write_bytes(new_bytes)
        elif rel in MERGE_VIA_INCOMING:
            incoming.append(rel)
            if not args.dry_run:
                (incoming_dir / rel).parent.mkdir(parents=True, exist_ok=True)
                (incoming_dir / rel).write_bytes(new_bytes)
        else:
            kept.append(rel)

    # config.json: keep user values, add new keys, record kit location and interpreter.
    cfg_path = target / ".claude" / "kit" / "config.json"
    template_cfg = json.loads((TEMPLATE / ".claude" / "kit" / "config.json").read_text(encoding="utf-8"))
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    except ValueError:
        cfg = {}
        if not args.dry_run:
            (backup_dir / ".claude/kit").mkdir(parents=True, exist_ok=True)
            shutil.copy2(cfg_path, backup_dir / ".claude/kit/config.json")
    cfg = merge_missing(cfg, template_cfg)
    cfg["kit_version"] = template_cfg["kit_version"]
    cfg["kit_home"] = str(KIT_HOME)
    cfg["python"] = py
    if not args.dry_run:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    gi = target / ".gitignore"
    gi_text = gi.read_text(encoding="utf-8", errors="replace") if gi.exists() else ""
    present = {line.strip() for line in gi_text.splitlines()}
    missing = [line for line in GITIGNORE_LINES if line not in present]
    gi_added = bool(missing)
    if missing and not args.dry_run:
        block = ([GITIGNORE_MARKER] if GITIGNORE_MARKER not in present else []) + missing
        with gi.open("a", encoding="utf-8") as fh:
            fh.write(("\n" if gi_text and not gi_text.endswith("\n") else "") + "\n".join(block) + "\n")

    if args.global_ and not args.dry_run:
        skill = Path.home() / ".claude" / "skills" / "kit-adopt" / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(GLOBAL_SKILL.format(kit=KIT_HOME, py=py), encoding="utf-8")

    if not args.dry_run:
        subprocess.run([sys.executable, str(target / ".claude/kit/kg.py"), "--root", str(target), "build"],
                       capture_output=True, text=True)

    mode = "upgrade" if already else "install"
    print(f"project kit {template_cfg['kit_version']} {mode}{' (dry run)' if args.dry_run else ''}: {target}")
    print(f"  hooks will run with: {py}")
    print(f"  created {len(created)} files, upgraded {len(upgraded)} kit files" + (f" (backup in .claude/kit/backup/{stamp})" if upgraded else ""))
    for rel in incoming:
        print(f"  kept your {rel}; new kit version saved to .claude/kit/incoming/{rel}")
    if kept:
        print(f"  kept {len(kept)} existing files untouched")
    if gi_added:
        print("  added the kit block to .gitignore")
    if args.global_:
        print("  installed /kit-adopt in ~/.claude/skills (works in every project)")
    print()
    if not already:
        print("Next: open Claude Code in this folder and run /kit-init")
    else:
        print("Next: run /kit-init --refresh in Claude Code to merge incoming files and repair drift")
    return 0


GLOBAL_SKILL = """---
name: kit-adopt
description: Install the project kit into the current project (or upgrade it) and adapt it to the repository. Use when the user asks to set up, import, adopt or upgrade the project kit, the self-improving Claude setup, or the knowledge graph in this project.
argument-hint: "[--refresh] [--new]"
disable-model-invocation: true
---

# Adopt the project kit here

The kit lives at `{kit}`.

1. Find the project root: the git top level (`git rev-parse --show-toplevel`) or, outside git, the current working directory. Confirm it with the user if it looks wrong (for example a home folder).
2. Run the installer and show its summary:

   ```
   {py} "{kit}/install.py" "<project root>"
   ```

3. Read `<project root>/.claude/skills/kit-init/SKILL.md` and follow it with these arguments: $ARGUMENTS. If the installer said this was an upgrade, add `--refresh`.
4. Hooks and skills from the new files load in the next session. Tell the user to restart Claude Code in this folder once /kit-init is done.
"""


if __name__ == "__main__":
    sys.exit(main())
