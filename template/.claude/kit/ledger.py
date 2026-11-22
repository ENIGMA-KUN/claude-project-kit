#!/usr/bin/env python3
"""Task ledger and resume brief for the project kit.

The ledger is working memory for one line of work (one git branch): the
current goal, decisions with their status, dead ends, open questions and the
next step. It lives on disk, so it survives compaction, /clear and new
sessions; the SessionStart hook puts it back into context.

The brief is built from the session transcript: the original and latest
requests, files touched and the most recent turns within a character budget,
plus the ledger. It is history, so every brief tells Claude to check the files
on disk before relying on it.

Commands:
  show [--json]                       print the ledger for the current branch
  review [--json]                     proposed decisions and open questions
  decide TEXT [--why W] [--status S] [--by B]
  status ID STATUS [--by NEW_ID]      approve, reject or supersede a decision
  promoted ID PATH                    mark a decision as promoted to knowledge/
  goal TEXT | next TEXT | deadend TEXT [--why W] | question TEXT | answer QID TEXT
  brief [--transcript PATH] [--max-chars N]   build and print the resume brief
  archive                             close the ledger when the task is done
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

DECISION_STATUSES = {"proposed", "approved", "rejected", "superseded"}

MARKER_RE = re.compile(
    r"^\s*(?:[-*>]\s*)?(?:\*\*|__)?(decision|dead[ -]?end|next(?: step)?|goal|open question|question)(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s*(.+?)\s*$",
    re.I,
)
BECAUSE_RE = re.compile(r"\s*(?:,|;|\s)\s*(?:because|since|as|so that)\s+", re.I)

USER_DECISION_RE = re.compile(
    r"(?:^|[.!?]\s+|\n)\s*((?:ok(?:ay)?,?\s+|yes,?\s+|right,?\s+)?"
    r"(?:let'?s go with|go with|let'?s use|we(?:'ll| will) use|we(?:'ll| will) go with|"
    r"(?:i|we) (?:have )?decided|decision is|stick with|keep using|"
    r"use [^.?!\n]{1,60} instead of|don'?t use [^.?!\n]{1,60}, use|approved?[:,]?\s)"
    r"[^.?!\n]{2,200})",
    re.I,
)

SKIP_USER_PREFIXES = ("<", "Base directory for this skill", "[Request interrupted", "Caveat:")
FILE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


# --------------------------------------------------------------------- storage


def find_root() -> Path:
    here = Path(__file__).resolve()
    if here.parent.name == "kit" and here.parent.parent.name == ".claude":
        return here.parents[2]
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env).resolve() if env else Path.cwd().resolve()


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def branch_slug(root: Path) -> str:
    try:
        out = subprocess.run(["git", "branch", "--show-current"], cwd=root, capture_output=True,
                             text=True, timeout=3, encoding="utf-8", errors="replace")
        name = out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        name = ""
    name = name or "default"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")[:80] or "default", name


def ledger_dir(root: Path) -> Path:
    return root / ".claude" / "kit" / "ledger"


def ledger_path(root: Path, slug: str | None = None) -> Path:
    return ledger_dir(root) / f"{slug or branch_slug(root)[0]}.json"


def brief_path(root: Path, slug: str | None = None) -> Path:
    return root / ".claude" / "kit" / "briefs" / f"{slug or branch_slug(root)[0]}.md"


def empty_ledger(branch: str) -> dict:
    return {
        "branch": branch, "created": now_iso(), "updated": now_iso(),
        "goal": None, "goal_history": [], "decisions": [], "dead_ends": [],
        "questions": [], "next": None, "files": [], "sessions": [],
    }


def load(root: Path) -> dict:
    slug, branch = branch_slug(root)
    path = ledger_path(root, slug)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for k, v in empty_ledger(branch).items():
                data.setdefault(k, v)
            return data
    except (OSError, ValueError):
        pass
    return empty_ledger(branch)


def save(root: Path, ledger: dict) -> Path:
    slug, _ = branch_slug(root)
    ledger["updated"] = now_iso()
    path = ledger_path(root, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    path.with_suffix(".md").write_text(render(ledger), encoding="utf-8")
    return path


def is_empty(ledger: dict) -> bool:
    return not (ledger.get("goal") or ledger.get("decisions") or ledger.get("dead_ends")
                or ledger.get("next") or ledger.get("questions"))


# --------------------------------------------------------------------- updates


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()[:90]


def split_reason(text: str) -> tuple:
    parts = BECAUSE_RE.split(text, maxsplit=1)
    if len(parts) == 2 and len(parts[0]) > 3:
        return parts[0].strip().rstrip(",;"), parts[1].strip().rstrip(".")
    return text.strip().rstrip("."), ""


def add_decision(ledger: dict, text: str, why: str = "", status: str = "proposed",
                 by: str = "claude", session: str = "") -> str:
    text = text.strip()[:300]
    key = _norm(text)
    for d in ledger["decisions"]:
        if _norm(d["text"]) == key and d["status"] not in ("rejected", "superseded"):
            if status == "approved" and d["status"] == "proposed":
                d["status"], d["approved_by"], d["updated"] = "approved", by, now_iso()
            if why and not d.get("why"):
                d["why"] = why[:300]
            return d["id"]
    did = f"D{len(ledger['decisions']) + 1}"
    ledger["decisions"].append({
        "id": did, "text": text, "why": why.strip()[:300], "status": status, "by": by,
        "ts": now_iso(), "session": session[:12], "superseded_by": None, "promoted": None,
    })
    return did


def set_status(ledger: dict, did: str, status: str, new_id: str | None = None, by: str = "user") -> bool:
    if status not in DECISION_STATUSES:
        raise ValueError(f"status must be one of {sorted(DECISION_STATUSES)}")
    for d in ledger["decisions"]:
        if d["id"].lower() == did.lower():
            d["status"], d["updated"] = status, now_iso()
            if status == "approved":
                d["approved_by"] = by
            if status == "superseded":
                d["superseded_by"] = new_id
            return True
    return False


def set_goal(ledger: dict, text: str, source: str) -> None:
    text = text.strip()[:600]
    if not text:
        return
    if ledger.get("goal") and ledger["goal"]["text"] != text:
        ledger["goal_history"].append(ledger["goal"])
        ledger["goal_history"] = ledger["goal_history"][-5:]
    ledger["goal"] = {"text": text, "source": source, "ts": now_iso()}


def add_dead_end(ledger: dict, text: str, why: str = "") -> None:
    key = _norm(text)
    if any(_norm(x["text"]) == key for x in ledger["dead_ends"]):
        return
    ledger["dead_ends"].append({"text": text.strip()[:300], "why": why.strip()[:300], "ts": now_iso()})
    ledger["dead_ends"] = ledger["dead_ends"][-15:]


def add_question(ledger: dict, text: str) -> str:
    key = _norm(text)
    for q in ledger["questions"]:
        if _norm(q["text"]) == key:
            return q["id"]
    qid = f"Q{len(ledger['questions']) + 1}"
    ledger["questions"].append({"id": qid, "text": text.strip()[:300], "status": "open", "answer": None, "ts": now_iso()})
    return qid


def answer_question(ledger: dict, qid: str, answer: str) -> bool:
    for q in ledger["questions"]:
        if q["id"].lower() == qid.lower():
            q["status"], q["answer"], q["answered"] = "answered", answer.strip()[:300], now_iso()
            return True
    return False


def apply_markers(ledger: dict, text: str, session: str = "", by: str = "claude") -> list:
    """Record `Decision:`, `Dead end:`, `Next:`, `Goal:` and `Question:` lines from a message."""
    changes = []
    in_code = False
    for line in (text or "").splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = MARKER_RE.match(line)
        if not m:
            continue
        kind, body = m.group(1).lower().replace(" ", "").replace("-", ""), m.group(2).strip().strip("*_`")
        if len(body) < 4:
            continue
        if kind == "decision":
            what, why = split_reason(body)
            changes.append(("decision", add_decision(ledger, what, why, "proposed", by, session)))
        elif kind == "deadend":
            what, why = split_reason(body)
            add_dead_end(ledger, what, why)
            changes.append(("dead_end", what))
        elif kind in ("next", "nextstep"):
            ledger["next"] = {"text": body[:300], "ts": now_iso()}
            changes.append(("next", body))
        elif kind == "goal":
            set_goal(ledger, body, by)
            changes.append(("goal", body))
        elif kind in ("question", "openquestion"):
            changes.append(("question", add_question(ledger, body)))
    return changes


def user_decisions(prompt: str) -> list:
    out = []
    for m in USER_DECISION_RE.finditer(prompt or ""):
        sentence = m.group(1).strip().rstrip(",;:")
        if len(sentence.split()) >= 3:
            out.append(sentence[:240])
    return out[:3]


def record_answers(ledger: dict, tool_input: dict, tool_response, session: str = "") -> list:
    """Turn AskUserQuestion answers into approved decisions."""
    answers = {}
    if isinstance(tool_response, dict):
        answers = tool_response.get("answers") or {}
    if not isinstance(answers, dict) or not answers:
        return []
    headers = {}
    for q in (tool_input or {}).get("questions") or []:
        if isinstance(q, dict):
            headers[q.get("question", "")] = q.get("header", "")
    ids = []
    for question, answer in answers.items():
        answer = ", ".join(answer) if isinstance(answer, list) else str(answer)
        label = headers.get(question) or question
        label = re.sub(r"\s+", " ", label).strip()[:120]
        ids.append(add_decision(ledger, f"{label}: {answer}", f"user answered: {question[:160]}", "approved", "user", session))
    return ids


# ------------------------------------------------------------------ transcript


def _clean_user_text(content) -> str:
    if isinstance(content, str):
        texts = [content]
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return ""
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    else:
        return ""
    keep = []
    for t in texts:
        if not t:
            continue
        cmd = re.search(r"<command-name>\s*(/[\w:.-]+)\s*</command-name>", t)
        if cmd:
            args = re.search(r"<command-args>(.*?)</command-args>", t, re.S)
            keep.append(f"(ran {cmd.group(1)}{(' ' + args.group(1).strip()) if args and args.group(1).strip() else ''})")
            continue
        if t.lstrip().startswith("[Image"):
            keep.append("[image]")
            continue
        if t.lstrip().startswith(SKIP_USER_PREFIXES):
            continue
        t = re.sub(r"<system-reminder>.*?</system-reminder>", "", t, flags=re.S)
        keep.append(t.strip())
    return "\n".join(k for k in keep if k).strip()


def _tool_summary(block: dict, cwd: str) -> tuple:
    name = block.get("name", "?")
    inp = block.get("input") or {}
    path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""
    if path and cwd:
        try:
            path = os.path.relpath(path, cwd).replace("\\", "/")
        except ValueError:
            pass
    detail = path or str(inp.get("command") or inp.get("pattern") or inp.get("url") or inp.get("description") or "")
    detail = re.sub(r"\s+", " ", detail)[:80]
    return name, detail, (path if name in FILE_TOOLS and path else "")


def parse_transcript(path: str | Path) -> dict:
    turns: list = []
    files: list = []
    cwd = ""
    session = ""
    summary = ""
    p = Path(path)
    if not p.exists():
        return {"turns": [], "files": [], "cwd": "", "session": "", "summary": ""}
    with p.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"user"' not in line and '"assistant"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            kind = o.get("type")
            if kind not in ("user", "assistant") or o.get("isSidechain"):
                continue
            cwd = o.get("cwd") or cwd
            session = o.get("sessionId") or session
            msg = o.get("message") or {}
            content = msg.get("content")
            ts = str(o.get("timestamp") or "")[:19]
            if kind == "user":
                if o.get("isCompactSummary"):
                    text = _clean_user_text(content) or (content if isinstance(content, str) else "")
                    summary = str(text)[:2000]
                    continue
                if o.get("isMeta"):
                    continue
                text = _clean_user_text(content)
                if text:
                    turns.append({"role": "user", "text": text, "ts": ts, "tools": []})
                continue
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                # One assistant turn per text message; tool calls attach to the message before them.
                if b.get("type") == "text" and b.get("text", "").strip():
                    turns.append({"role": "assistant", "text": b["text"].strip(), "ts": ts, "tools": []})
                elif b.get("type") == "tool_use":
                    if not turns or turns[-1]["role"] != "assistant":
                        turns.append({"role": "assistant", "text": "", "ts": ts, "tools": []})
                    cur = turns[-1]
                    name, detail, fpath = _tool_summary(b, cwd)
                    cur["tools"].append(f"{name} {detail}".strip())
                    if fpath:
                        if fpath in files:
                            files.remove(fpath)
                        files.append(fpath)
    return {"turns": turns, "files": files, "cwd": cwd, "session": session, "summary": summary}


# ----------------------------------------------------------------------- render


def render(ledger: dict, include_closed: bool = True) -> str:
    lines = [f"# Task ledger: {ledger.get('branch', 'default')}", "", f"Updated {ledger.get('updated', '')}", ""]
    if ledger.get("goal"):
        g = ledger["goal"]
        lines += ["## Goal", "", f"{g['text']}  _(from {g['source']}, {g['ts'][:16]})_", ""]
    decisions = ledger.get("decisions", [])
    if decisions:
        lines += ["## Decisions", ""]
        order = {"approved": 0, "proposed": 1, "superseded": 2, "rejected": 3}
        for d in sorted(decisions, key=lambda d: (order.get(d["status"], 9), d["id"])):
            if not include_closed and d["status"] in ("superseded", "rejected"):
                continue
            tag = {"approved": "approved", "proposed": "PROPOSED, not yet approved", "superseded": f"superseded by {d.get('superseded_by') or '?'}", "rejected": "rejected"}[d["status"]]
            why = f", because {d['why']}" if d.get("why") else ""
            lines.append(f"- {d['id']} [{tag}] {d['text']}{why}")
        lines.append("")
    if ledger.get("dead_ends"):
        lines += ["## Dead ends (do not retry without a new reason)", ""]
        for x in ledger["dead_ends"]:
            lines.append(f"- {x['text']}" + (f", because {x['why']}" if x.get("why") else ""))
        lines.append("")
    open_q = [q for q in ledger.get("questions", []) if q["status"] == "open"]
    if open_q:
        lines += ["## Open questions for the user", ""] + [f"- {q['id']} {q['text']}" for q in open_q] + [""]
    if ledger.get("next"):
        lines += ["## Next step", "", ledger["next"]["text"], ""]
    if ledger.get("files"):
        lines += ["## Files in progress", ""] + [f"- {f}" for f in ledger["files"][-20:]] + [""]
    return "\n".join(lines).rstrip() + "\n"


def compact_context(ledger: dict, max_chars: int = 3000) -> str:
    """Ledger text for re-injection after compaction: open items only."""
    text = render(ledger, include_closed=False)
    text = text.split("\n", 3)[-1] if text.startswith("# ") else text
    if len(text) > max_chars:
        text = text[: max_chars - 40].rsplit("\n", 1)[0] + "\n[... ledger truncated ...]\n"
    return text


def build_brief(parsed: dict, ledger: dict, max_chars: int = 8000) -> str:
    turns = parsed.get("turns", [])
    user_turns = [t for t in turns if t["role"] == "user" and not t["text"].startswith("(ran /")]
    first = user_turns[0]["text"] if user_turns else ""
    latest = user_turns[-1]["text"] if user_turns else ""
    goal_cap = min(1500, max_chars // 8)

    def cap(s: str, n: int) -> str:
        s = s.strip()
        return s if len(s) <= n else s[: n - 3].rstrip() + "..."

    head = [f"Resume brief for branch {ledger.get('branch', 'default')}"
            + (f", session {parsed.get('session', '')[:8]}" if parsed.get("session") else "")
            + f", built {now_iso()[:16]}. This is history: check the files on disk and `git status` before relying on it."]
    if ledger.get("goal"):
        head += ["## Current goal (ledger)", cap(ledger["goal"]["text"], goal_cap)]
    if first:
        head += ["## Original request", cap(first, goal_cap)]
    if latest and latest != first:
        head += ["## Latest request", cap(latest, goal_cap)]
    ledger_text = compact_context(ledger, max_chars // 4).strip()
    if ledger_text and not is_empty(ledger):
        head += [ledger_text]
    files = parsed.get("files", [])[-30:]

    def head_text(n_files: int) -> str:
        parts = list(head)
        if files:
            shown = files[-n_files:] if n_files else []
            more = len(files) - len(shown)
            parts += ["## Files touched this session"] + [f"- {f}" for f in shown] + ([f"- (+{more} more)"] if more else [])
        return "\n\n".join(parts)

    n = len(files)
    text = head_text(n)
    while len(text) > max_chars // 2 and n > 0:
        n -= 1
        text = head_text(n)
    if len(text) > max_chars // 2:
        text = text[: max_chars // 2]

    budget = max_chars - len(text) - 120
    picked = []
    for t in reversed(turns):
        body = f"### {t['role']}" + (f"  ({t['ts']})" if t["ts"] else "") + "\n" + t["text"].strip()
        if t["tools"]:
            body += "\n> tools: " + "; ".join(t["tools"][-12:]) + (f" (+{len(t['tools']) - 12} more)" if len(t["tools"]) > 12 else "")
        if len(body) + 2 > budget:
            if not picked and budget > 300:
                body = body[:200] + "\n[... turn truncated ...]\n" + body[-(budget - 260):]
                picked.append(body)
            break
        picked.append(body)
        budget -= len(body) + 2
    omitted = len(turns) - len(picked)
    tail = ["## Recent turns"] + ([f"[... {omitted} earlier turns omitted ...]"] if omitted > 0 else []) + list(reversed(picked))
    out = text + "\n\n" + "\n\n".join(tail) + "\n"
    return out[:max_chars]


def write_brief(root: Path, transcript: str, max_chars: int = 8000, session: str = "") -> Path | None:
    parsed = parse_transcript(transcript)
    if not parsed["turns"]:
        return None
    ledger = load(root)
    ledger["files"] = parsed["files"][-30:]
    if not ledger.get("goal"):
        firsts = [t["text"] for t in parsed["turns"] if t["role"] == "user" and not t["text"].startswith("(ran /")]
        if firsts:
            set_goal(ledger, firsts[0], "first request")
    sid = (session or parsed.get("session", ""))[:12]
    if sid and sid not in ledger["sessions"]:
        ledger["sessions"] = (ledger["sessions"] + [sid])[-20:]
    save(root, ledger)
    path = brief_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_brief(parsed, ledger, max_chars), encoding="utf-8")
    return path


# -------------------------------------------------------------------------- cli


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ledger.py", description="Task ledger and resume brief")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("--json", action="store_true")
    r = sub.add_parser("review")
    r.add_argument("--json", action="store_true")
    d = sub.add_parser("decide")
    d.add_argument("text", nargs="+")
    d.add_argument("--why", default="")
    d.add_argument("--status", default="proposed", choices=sorted(DECISION_STATUSES))
    d.add_argument("--by", default="claude")
    st = sub.add_parser("status")
    st.add_argument("id")
    st.add_argument("status", choices=sorted(DECISION_STATUSES))
    st.add_argument("--by", dest="new_id", default=None, help="successor id when superseding")
    pr = sub.add_parser("promoted")
    pr.add_argument("id")
    pr.add_argument("path")
    for name in ("goal", "next", "question"):
        x = sub.add_parser(name)
        x.add_argument("text", nargs="+")
    de = sub.add_parser("deadend")
    de.add_argument("text", nargs="+")
    de.add_argument("--why", default="")
    an = sub.add_parser("answer")
    an.add_argument("id")
    an.add_argument("text", nargs="+")
    b = sub.add_parser("brief")
    b.add_argument("--transcript", default="")
    b.add_argument("--max-chars", type=int, default=8000)
    sub.add_parser("archive")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    root = find_root()
    ledger = load(root)

    if args.cmd == "show":
        print(json.dumps(ledger, indent=1, ensure_ascii=False) if args.json else render(ledger))
        return 0
    if args.cmd == "review":
        data = {
            "goal": ledger.get("goal"),
            "proposed": [d for d in ledger["decisions"] if d["status"] == "proposed"],
            "approved": [d for d in ledger["decisions"] if d["status"] == "approved"],
            "open_questions": [q for q in ledger["questions"] if q["status"] == "open"],
            "dead_ends": ledger["dead_ends"],
            "next": ledger.get("next"),
        }
        if args.json:
            print(json.dumps(data, indent=1, ensure_ascii=False))
        else:
            print(f"goal: {(data['goal'] or {}).get('text', '(none)')}")
            print(f"{len(data['proposed'])} proposed, {len(data['approved'])} approved decisions, {len(data['open_questions'])} open questions")
            for x in data["proposed"]:
                print(f"  {x['id']} PROPOSED {x['text']}" + (f" (because {x['why']})" if x.get("why") else ""))
            for q in data["open_questions"]:
                print(f"  {q['id']} QUESTION {q['text']}")
        return 0
    if args.cmd == "decide":
        did = add_decision(ledger, " ".join(args.text), args.why, args.status, args.by)
        save(root, ledger)
        print(did)
        return 0
    if args.cmd == "status":
        if not set_status(ledger, args.id, args.status, args.new_id):
            print(f"no decision {args.id}")
            return 1
        save(root, ledger)
        print(f"{args.id} -> {args.status}")
        return 0
    if args.cmd == "promoted":
        for x in ledger["decisions"]:
            if x["id"].lower() == args.id.lower():
                x["promoted"] = args.path
                save(root, ledger)
                print(f"{args.id} promoted to {args.path}")
                return 0
        print(f"no decision {args.id}")
        return 1
    if args.cmd == "goal":
        set_goal(ledger, " ".join(args.text), "user")
    elif args.cmd == "next":
        ledger["next"] = {"text": " ".join(args.text)[:300], "ts": now_iso()}
    elif args.cmd == "question":
        print(add_question(ledger, " ".join(args.text)))
    elif args.cmd == "deadend":
        add_dead_end(ledger, " ".join(args.text), args.why)
    elif args.cmd == "answer":
        if not answer_question(ledger, args.id, " ".join(args.text)):
            print(f"no question {args.id}")
            return 1
    elif args.cmd == "brief":
        if args.transcript:
            path = write_brief(root, args.transcript, args.max_chars)
            if path is None:
                print("transcript has no turns")
                return 1
            print(path.read_text(encoding="utf-8"))
        else:
            path = brief_path(root)
            print(path.read_text(encoding="utf-8") if path.exists() else render(ledger))
        return 0
    elif args.cmd == "archive":
        slug, _ = branch_slug(root)
        src = ledger_path(root, slug)
        if not src.exists():
            print("no ledger for this branch")
            return 0
        dest = ledger_dir(root) / "archive" / f"{slug}-{dt.date.today()}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dest)
        md = src.with_suffix(".md")
        if md.exists():
            md.unlink()
        print(f"archived to {dest.relative_to(root).as_posix()}")
        return 0
    save(root, ledger)
    print("ledger updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
