#!/usr/bin/env python3
"""Hook dispatcher for the project kit.

Usage (from .claude/settings.json): python kit_hook.py <event>

Events:
  session-start  inject a short project snapshot (graph health, recent lessons, handoff, git)
  prompt         retrieve relevant knowledge nodes for the prompt; log user corrections
  pre-tool       deny or ask on destructive commands and on secrets written into knowledge
  tool-failure   log the failure; warn when the same failure repeats (loop budget)
  pre-compact    log a context-pressure signal and rebuild the resume brief
  post-tool      store AskUserQuestion answers as approved decisions in the task ledger
  stop           file Decision/Dead end/Next lines into the ledger; once per session, suggest /reflect
  brief          rebuild the resume brief from the transcript (throttled, runs async on Stop)
  session-end    write a one-line session summary to the signal log and rebuild the brief

The task ledger (.claude/kit/ledger/<branch>.json) is put back into context by
session-start after compaction, and pointed to after /clear or on a new session.

Every handler fails open: an exception is written to .claude/kit/state/hook-errors.log
and the session continues. Signals stay local (gitignored) and are redacted for secrets.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
KIT = ROOT / ".claude" / "kit"
STATE_DIR = KIT / "state"
SIGNALS = KIT / "signals" / "events.jsonl"
sys.dont_write_bytecode = True  # keep __pycache__ out of the project tree
sys.path.insert(0, str(KIT))

CORRECTION_START = re.compile(
    r"^\s*(no\b|nope\b|wrong\b|incorrect\b|that'?s (not|wrong|incorrect)|not (what|like that|that one)|"
    r"why did you|you (forgot|missed|broke|ignored|didn'?t|did not|should have)|"
    r"i (told|said|asked) you|undo\b|revert (that|this|it)|stop\b|actually,? (no|it'?s|we|use|the)|"
    r"instead,? use|wrong (file|approach|command|function|branch))",
    re.I,
)
CORRECTION_ANY = re.compile(
    r"(i (already )?told you|as i said|you keep|still (wrong|broken|failing)|not again|"
    r"same (mistake|error) again|that'?s not what i (asked|wanted|meant)|you did it again)",
    re.I,
)
KIT_COMMANDS = re.compile(r"^\s*/(reflect|learn|curate|kit-init|audit|handoff|recall|loop-contract)\b")


# ---------------------------------------------------------------- small helpers


def read_input() -> dict:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", "replace")
        return json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        return {}


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=True))
    sys.stdout.flush()


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def config() -> dict:
    try:
        return json.loads((KIT / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def short_session(data: dict) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", str(data.get("session_id") or "nosession"))[:36] or "nosession"


def redact(text: str) -> str:
    try:
        import kg  # noqa: PLC0415

        for pat in kg.SECRET_PATTERNS:
            text = pat.sub("[REDACTED]", text)
    except Exception:  # noqa: BLE001
        pass
    return text


def log_event(event: dict) -> None:
    try:
        SIGNALS.parent.mkdir(parents=True, exist_ok=True)
        event = {"ts": now_iso(), **event}
        if "text" in event:
            event["text"] = redact(str(event["text"]))[:400]
        with SIGNALS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def load_state(sid: str) -> dict:
    try:
        return json.loads((STATE_DIR / f"{sid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"failures": 0, "corrections": 0, "patterns": {}, "injected": [], "nudged": False, "reflected": False}


def save_state(sid: str, state: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_DIR / f"{sid}.json.tmp"
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, STATE_DIR / f"{sid}.json")
    except OSError:
        pass


def git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=3,
            encoding="utf-8", errors="replace",
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


# ------------------------------------------------------------------- handlers


def on_session_start(data: dict) -> None:
    import kg  # noqa: PLC0415

    source = data.get("source", "startup")
    cfg = config()
    # Housekeeping: drop per-session state older than a week.
    if STATE_DIR.is_dir():
        cutoff = time.time() - 7 * 86400
        for p in STATE_DIR.glob("*.json"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                pass
    log_event({"event": "session_start", "session": short_session(data), "source": source})

    lines = []
    if not cfg.get("initialized"):
        lines.append("Project kit is installed but not adapted to this repo yet. Suggest the user run /kit-init.")
    incoming = KIT / "incoming"
    if incoming.is_dir() and any(incoming.iterdir()):
        lines.append("Kit files are waiting in .claude/kit/incoming/ to be merged; suggest /kit-init --refresh.")

    nodes, _ = kg.load_nodes(ROOT)
    if nodes:
        active = [n for n in nodes.values() if n["status"] == "active"]
        counts = {}
        for n in active:
            counts[n["type"]] = counts.get(n["type"], 0) + 1
        stale = len(kg.stale_report(ROOT, nodes))
        pending = sum(1 for n in nodes.values() if n["type"] == "proposal" and n["status"] == "proposed")
        summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "no active nodes"
        extra = []
        if stale:
            extra.append(f"{stale} stale")
        if pending:
            extra.append(f"{pending} proposals pending")
        lines.append(
            f"Knowledge graph (knowledge/index.md): {summary}"
            + (f"; {', '.join(extra)}" if extra else "")
            + ". Query it with `python .claude/kit/kg.py query \"<terms>\"` before guessing about architecture, past decisions or known errors."
        )
        lessons = sorted(
            (n for n in active if n["type"] == "lesson"),
            key=lambda n: (n["updated"] or n["created"]),
            reverse=True,
        )[:3]
        if lessons:
            lines.append("Most recent lessons:")
            for n in lessons:
                lines.append(f"- {n['rule'] or n['title']} ({n['file']})")

    handoffs = sorted((KIT / "handoffs").glob("*.md")) if (KIT / "handoffs").is_dir() else []
    if handoffs:
        latest = handoffs[-1]
        age = (time.time() - latest.stat().st_mtime) / 86400
        if age < 14:
            lines.append(f"Latest handoff: .claude/kit/handoffs/{latest.name} ({age:.0f} days old). Read it if the user is continuing that work.")

    branch = git("branch", "--show-current")
    if branch:
        dirty = len([line for line in git("status", "--porcelain").splitlines() if line.strip()])
        lines.append(f"Git: branch {branch}, {dirty} changed files.")

    last = kg.parse_date(cfg.get("last_curate"))
    every = int(cfg.get("curate_every_days", 7))
    recent = len(kg.read_events(ROOT, every))
    if recent >= 10 and (last is None or (dt.date.today() - last).days >= every):
        lines.append(f"Meta loop due: {recent} friction/usage events since the last /curate. Mention it to the user once.")

    research = protected_globs()
    if research:
        baseline = KIT / "research-baseline.json"
        when = time.strftime("%Y-%m-%d", time.localtime(baseline.stat().st_mtime)) if baseline.exists() else "none yet"
        lines.append(
            f"Research guard on: {len(research)} protected evaluation paths (baseline: {when}). Run experiments through "
            "`python .claude/kit/runlog.py run --name <name> -- <command>`, report only numbers a logged run produced "
            "(failed runs included), and run `runlog.py check` before reporting results."
        )

    lines += ledger_context(source, cfg)

    if lines:
        emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "[project-kit]\n" + "\n".join(lines)}})


def ledger_context(source: str, cfg: dict) -> list:
    """Bring the task ledger back after compaction or /clear, or point to it on a new session."""
    lcfg = cfg.get("ledger", {})
    if not lcfg.get("enabled", True) or source == "resume":
        return []
    import ledger as lg  # noqa: PLC0415

    led = lg.load(ROOT)
    if lg.is_empty(led):
        if source == "compact":
            return ["Context was just compacted. If a task was in progress, re-read its loop contract in .claude/kit/contracts/ or the latest handoff before continuing."]
        return []
    slug = lg.branch_slug(ROOT)[0]
    brief = f".claude/kit/briefs/{slug}.md"
    if source == "compact":
        return [
            "Context was just compacted. The task ledger below was kept on disk and is more reliable than the summary for "
            "decisions, dead ends and the next step. Approved decisions are settled: do not reopen them unless the user does. "
            f"Proposed ones still need the user's yes. Full brief with recent turns: {brief}.",
            lg.compact_context(led, int(lcfg.get("compact_inject_chars", 3000))).strip(),
        ]
    try:
        updated = dt.datetime.fromisoformat(led.get("updated", "")[:19])
        age_days = (dt.datetime.now() - updated).total_seconds() / 86400
    except ValueError:
        age_days = 0
    if source == "startup" and age_days > float(lcfg.get("stale_days", 7)):
        return []
    approved = sum(1 for d in led["decisions"] if d["status"] == "approved")
    proposed = sum(1 for d in led["decisions"] if d["status"] == "proposed")
    goal = (led.get("goal") or {}).get("text", "")
    nxt = (led.get("next") or {}).get("text", "")
    why = "after /clear" if source == "clear" else f"updated {age_days:.0f} days ago"
    return [
        f"Task ledger for branch '{led.get('branch')}' ({why}): goal \"{goal[:160]}\"; {approved} approved and {proposed} proposed decisions; "
        f"{len(led['dead_ends'])} dead ends" + (f"; next: {nxt[:120]}" if nxt else "") + ". "
        f"If the user is continuing that work, read {brief} (or run `python .claude/kit/ledger.py show`) before acting. "
        "If they started something new, ignore it; `python .claude/kit/ledger.py archive` closes it when the task is done."
    ]


def on_prompt(data: dict) -> None:
    prompt = str(data.get("prompt") or "")
    sid = short_session(data)
    state = load_state(sid)
    cfg = config()
    context = []

    if KIT_COMMANDS.match(prompt):
        if re.match(r"^\s*/(reflect|learn)\b", prompt):
            state["reflected"] = True
        save_state(sid, state)
        return

    lcfg = cfg.get("ledger", {})
    if lcfg.get("enabled", True) and not prompt.lstrip().startswith("/"):
        try:
            import ledger as lg  # noqa: PLC0415

            led = lg.load(ROOT)
            changed = False
            if not led.get("goal") and len(prompt.split()) >= 6:
                lg.set_goal(led, prompt[:600], "first request")
                changed = True
            if lcfg.get("capture_user_decisions", True):
                for sentence in lg.user_decisions(prompt):
                    did = lg.add_decision(led, sentence, "", "approved", "user", sid)
                    context.append(f"Recorded in the task ledger as approved decision {did}: \"{sentence[:120]}\". Follow it in later steps.")
                    changed = True
            if changed:
                lg.save(ROOT, led)
        except Exception as exc:  # noqa: BLE001
            note_error("prompt-ledger", exc)

    if CORRECTION_START.search(prompt) or CORRECTION_ANY.search(prompt):
        state["corrections"] = state.get("corrections", 0) + 1
        log_event({"event": "correction", "category": "semantic", "session": sid, "text": prompt[:300]})
        context.append(
            "The user seems to be correcting earlier work. Fix it first. If the mistake could recur in a later "
            "session, offer to record it with /learn (one sentence, no pressure)."
        )

    rcfg = cfg.get("retrieval", {})
    if rcfg.get("enabled", True) and len(prompt.split()) >= 3 and not prompt.lstrip().startswith("/"):
        try:
            import kg  # noqa: PLC0415

            nodes, _ = kg.load_nodes(ROOT)
            if nodes:
                idx = kg.Index(nodes, kg.SERVED_STATUSES)
                hits = idx.search(
                    prompt[:2000],
                    k=int(rcfg.get("max_nodes", 3)) + 3,
                    min_terms=int(rcfg.get("min_terms", 2)),
                )
                seen = set(state.get("injected", []))
                picked = [
                    nd for score, _, nd in hits
                    if score >= float(rcfg.get("min_score", 3.0)) and nd["id"] not in seen
                ][: int(rcfg.get("max_nodes", 3))]
                if picked:
                    rows = []
                    for nd in picked:
                        line = nd["rule"] or nd["description"] or nd["title"]
                        rows.append(f"- [{nd['type']}] {nd['title']}: {line} ({nd['file']})")
                    context.append(
                        "Project knowledge that may apply (read the file before relying on details; say so if a node looks wrong or outdated):\n"
                        + "\n".join(rows)
                    )
                    state["injected"] = list(seen | {nd["id"] for nd in picked})
                    log_event({"event": "injected", "session": sid, "nodes": [nd["id"] for nd in picked]})
        except Exception as exc:  # noqa: BLE001
            note_error("prompt-retrieval", exc)

    save_state(sid, state)
    if context:
        emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "[project-kit]\n" + "\n\n".join(context)}})


RM_ROOT = re.compile(
    r"(^|[;&|(]|\s)\s*rm(\s+(-[a-zA-Z]+|--[a-zA-Z-]+))*\s+(-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)"
    r"(\s+(-[a-zA-Z]+|--[a-zA-Z-]+))*\s+['\"]?(/|~|\$\{?HOME\}?|[A-Za-z]:[\\/]?)[*/\\]*['\"]?\s*($|[;&|])"
)
PS_RM_ROOT = re.compile(
    r"remove-item\b[^;|]*-recurse[^;|]*\s['\"]?([A-Za-z]:\\?|~|\$home|\$env:userprofile)['\"]?(\s|$)", re.I
)
DENY_SUBSTRINGS = ["mkfs", ":(){:|:&};:", "> /dev/sda", "of=/dev/sd", "chmod -R 777 /", "--no-preserve-root", "format-volume"]
ASK_PATTERNS = [
    (re.compile(r"git\s+push\b.*(\s-f\b|--force)"), "force push"),
    (re.compile(r"git\s+reset\s+--hard"), "git reset --hard discards local changes"),
    (re.compile(r"git\s+clean\s+-[a-z]*f"), "git clean deletes untracked files"),
    (re.compile(r"\b(drop\s+(database|table|schema)|truncate\s+table)\b", re.I), "destructive SQL"),
    (re.compile(r"\b(npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b|\bcargo\s+publish\b"), "package publication"),
    (re.compile(r"(^|[\s'\"/])(\.env(\.local|\.production)?|id_rsa|id_ed25519|credentials\.json|\.aws/credentials)([\s'\"]|$)"), "command touches a credential file"),
]
PROTECTED_KNOWLEDGE = re.compile(r"(^|[/\\])(knowledge|\.claude[/\\](rules|skills|agents))[/\\]|(^|[/\\])CLAUDE(\.local)?\.md$")

# Shell verbs that change or remove a file named on the same command line.
WRITE_VERBS = re.compile(
    r"(^|[;&|(]|\s)(rm|del|erase|mv|move|cp|copy|truncate|tee|dd|shred|unlink|rmdir|"
    r"git\s+(rm|mv|restore|checkout\s+--)|sed\s+-[a-zA-Z]*i|perl\s+-[a-zA-Z]*i|"
    r"remove-item|move-item|copy-item|rename-item|set-content|add-content|clear-content|out-file)\b",
    re.I,
)
REDIRECT_TARGET = re.compile(r">{1,2}\s*['\"]?([^\s'\";&|]+)")
PROTECTED_REASON = (
    "{path} is a protected research path (evaluation data, metric code or a baseline listed in "
    "research.protected_paths). Changing it changes what results mean, so the user must approve it; "
    "record the approval with /decide."
)


def protected_globs() -> list:
    out = []
    for g in config().get("research", {}).get("protected_paths", []):
        g = str(g).strip().replace("\\", "/")
        while g.startswith("./"):
            g = g[2:]
        if g:
            out.append(g)
    return out


def project_relative(path: str) -> str:
    p = path.strip().strip("'\"").replace("\\", "/")
    root = str(ROOT).replace("\\", "/").rstrip("/")
    if p.lower().startswith(root.lower() + "/"):
        p = p[len(root) + 1:]
    while p.startswith("./"):
        p = p[2:]
    return p


def is_protected(path: str, globs: list) -> bool:
    import fnmatch  # noqa: PLC0415

    rel = project_relative(path)
    if not rel or not globs:
        return False
    for g in globs:
        g = g.rstrip("/")
        if any(ch in g for ch in "*?["):
            if fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(rel, g.replace("/**", "")):
                return True
        elif rel == g or rel.startswith(g + "/"):
            return True
    return False


def protected_in_command(cmd: str, globs: list) -> str:
    """Return the protected path a shell command would change, or ''."""
    for target in REDIRECT_TARGET.findall(cmd):
        if is_protected(target, globs):
            return target
    if WRITE_VERBS.search(cmd):
        for token in re.findall(r"['\"]([^'\"]+)['\"]|(\S+)", cmd):
            word = token[0] or token[1]
            if ("/" in word or "\\" in word or "." in word) and is_protected(word, globs):
                return word
    return ""


def on_pre_tool(data: dict) -> None:
    tool = data.get("tool_name", "")
    tin = data.get("tool_input") or {}

    def decide(decision: str, reason: str) -> None:
        log_event({"event": "guard", "category": "alignment", "session": short_session(data), "tool": tool, "text": reason})
        emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision, "permissionDecisionReason": f"[project-kit] {reason}"}})

    globs = protected_globs()
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit") and globs:
        target = str(tin.get("file_path") or tin.get("notebook_path") or "")
        if is_protected(target, globs):
            return decide("ask", PROTECTED_REASON.format(path=project_relative(target)))

    if tool in ("Bash", "PowerShell"):
        cmd = str(tin.get("command") or "")
        if RM_ROOT.search(cmd) or PS_RM_ROOT.search(cmd):
            return decide("deny", "Recursive delete aimed at a root or home directory. Ask the user to run it themselves if it is really intended.")
        low = cmd.lower()
        for s in DENY_SUBSTRINGS:
            if s.lower() in low:
                return decide("deny", f"Blocked destructive command pattern '{s}'.")
        if re.search(r"git\s+push\b.*(\s-f\b|--force)[^;&|]*\b(main|master)\b", cmd):
            return decide("deny", "Force push to main/master is not allowed by the project constitution.")
        hit = protected_in_command(cmd, globs) if globs else ""
        if hit:
            return decide("ask", PROTECTED_REASON.format(path=project_relative(hit)))
        for pat, why in ASK_PATTERNS:
            if pat.search(cmd):
                return decide("ask", f"Needs the user's confirmation: {why}.")
        return

    if tool in ("Edit", "Write", "MultiEdit"):
        path = str(tin.get("file_path") or "").replace("\\", "/")
        if path.endswith(".claude/constitution.md"):
            return decide("ask", "The constitution holds invariants the learning loops may not change on their own. Confirm this edit.")
        if PROTECTED_KNOWLEDGE.search(path):
            parts = [str(tin.get("content") or ""), str(tin.get("new_string") or "")]
            for edit in tin.get("edits") or []:
                if isinstance(edit, dict):
                    parts.append(str(edit.get("new_string") or ""))
            try:
                import kg  # noqa: PLC0415

                hits = kg.find_secrets("\n".join(parts))
            except Exception:  # noqa: BLE001
                hits = []
            if hits:
                return decide("deny", f"This text looks like it contains a secret ({hits[0]}). Knowledge and instruction files are shared and long-lived; reference the env var name instead.")


def failure_key(tool: str, tin: dict, err: str) -> str:
    lines = [line.strip() for line in (err or "").splitlines() if line.strip()]
    meaningful = [line for line in lines if not re.match(r"^(exit code|error:?$|command failed)", line, re.I)]
    first = (meaningful or lines or [""])[0]
    first = re.sub(r"([A-Za-z]:)?[\\/][^\s:'\"]+", "<path>", first)
    first = re.sub(r"'[^']*'|\"[^\"]*\"", "<str>", first)
    first = re.sub(r"\d+", "N", first)
    head = ""
    if tool in ("Bash", "PowerShell"):
        words = str(tin.get("command") or "").strip().split()
        head = f"[{words[0]}]" if words else ""
    return f"{tool}{head}: {first[:90]}"


def on_tool_failure(data: dict) -> None:
    tool = data.get("tool_name", "?")
    tin = data.get("tool_input") or {}
    err = str(data.get("error") or "")
    sid = short_session(data)
    if data.get("is_interrupt"):
        log_event({"event": "interrupt", "category": "semantic", "session": sid, "tool": tool})
        return
    low = err.lower()
    if any(s in low for s in ("permission", "denied", "blocked", "not allowed")):
        category = "procedural"
    elif tool in ("Edit", "MultiEdit", "Write") and any(s in low for s in ("not been read", "read it first", "not found in file", "old_string")):
        category = "procedural"
    else:
        category = "syntactic"
    key = failure_key(tool, tin, err)
    detail = str(tin.get("command") or tin.get("file_path") or "")[:160]
    log_event({"event": "tool_failure", "category": category, "session": sid, "tool": tool, "key": key, "text": f"{detail} :: {err[:240]}"})

    state = load_state(sid)
    state["failures"] = state.get("failures", 0) + 1
    patterns = state.setdefault("patterns", {})
    patterns[key] = patterns.get(key, 0) + 1
    save_state(sid, state)
    limit = int(config().get("loop", {}).get("max_same_failure", 3))
    if patterns[key] in (limit, limit * 2):
        emit({"hookSpecificOutput": {"hookEventName": "PostToolUseFailure", "additionalContext": (
            f"[project-kit] This failure has now happened {patterns[key]} times in this session ({key}). "
            "Loop budget reached: stop retrying the same approach. Diagnose the cause, check the knowledge graph "
            "for a known fix, or ask the user. If you find the fix, it is a good /learn candidate."
        )}})


def refresh_brief(data: dict, force: bool) -> None:
    """Rebuild the resume brief from the transcript. Throttled to every 2 minutes unless forced."""
    lcfg = config().get("ledger", {})
    transcript = str(data.get("transcript_path") or "")
    if not lcfg.get("enabled", True) or not transcript:
        return
    import ledger as lg  # noqa: PLC0415

    path = lg.brief_path(ROOT)
    if not force and path.exists() and time.time() - path.stat().st_mtime < 120:
        return
    lg.write_brief(ROOT, transcript, int(lcfg.get("brief_max_chars", 8000)), short_session(data))


def on_brief(data: dict) -> None:
    refresh_brief(data, force=False)


def on_pre_compact(data: dict) -> None:
    log_event({"event": "compact", "category": "performance", "session": short_session(data), "trigger": data.get("trigger", "")})
    refresh_brief(data, force=True)


def on_post_tool(data: dict) -> None:
    """AskUserQuestion answers are the user's sign-off: store them as approved decisions."""
    if data.get("tool_name") != "AskUserQuestion" or not config().get("ledger", {}).get("enabled", True):
        return
    import ledger as lg  # noqa: PLC0415

    led = lg.load(ROOT)
    ids = lg.record_answers(led, data.get("tool_input") or {}, data.get("tool_response"), short_session(data))
    if ids:
        lg.save(ROOT, led)
        log_event({"event": "decision", "session": short_session(data), "source": "ask", "ids": ids})


def on_stop(data: dict) -> None:
    if data.get("stop_hook_active"):
        return
    sid = short_session(data)
    if config().get("ledger", {}).get("enabled", True):
        try:
            import ledger as lg  # noqa: PLC0415

            led = lg.load(ROOT)
            changes = lg.apply_markers(led, str(data.get("last_assistant_message") or ""), sid)
            if changes:
                lg.save(ROOT, led)
                log_event({"event": "decision", "session": sid, "source": "markers", "ids": [c[1] for c in changes if c[0] == "decision"]})
        except Exception as exc:  # noqa: BLE001
            note_error("stop-ledger", exc)
    state = load_state(sid)
    if state.get("nudged") or state.get("reflected"):
        return
    threshold = int(config().get("reflect_nudge_threshold", 3))
    friction = state.get("failures", 0) + 2 * state.get("corrections", 0)
    if friction >= threshold:
        state["nudged"] = True
        save_state(sid, state)
        emit({"systemMessage": (
            f"[project-kit] This session had {state.get('corrections', 0)} corrections and {state.get('failures', 0)} tool failures. "
            "Before closing, /reflect turns them into lessons so the next session starts smarter."
        )})


def on_session_end(data: dict) -> None:
    sid = short_session(data)
    state = load_state(sid)
    log_event({
        "event": "session_end", "session": sid, "reason": data.get("reason", ""),
        "failures": state.get("failures", 0), "corrections": state.get("corrections", 0),
        "injected": len(state.get("injected", [])), "reflected": bool(state.get("reflected")),
    })
    refresh_brief(data, force=True)


HANDLERS = {
    "session-start": on_session_start,
    "prompt": on_prompt,
    "pre-tool": on_pre_tool,
    "tool-failure": on_tool_failure,
    "pre-compact": on_pre_compact,
    "post-tool": on_post_tool,
    "stop": on_stop,
    "brief": on_brief,
    "session-end": on_session_end,
}


def note_error(where: str, exc: BaseException) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with (STATE_DIR / "hook-errors.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{now_iso()} {where}: {type(exc).__name__}: {exc}\n")
    except OSError:
        pass


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    handler = HANDLERS.get(event)
    if handler is None:
        sys.stderr.write(f"kit_hook.py: unknown event '{event}'\n")
        return 0
    data = read_input()
    try:
        handler(data)
    except Exception as exc:  # noqa: BLE001
        note_error(event, exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
