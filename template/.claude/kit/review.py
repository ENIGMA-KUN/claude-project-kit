#!/usr/bin/env python3
"""Second-opinion review of the current change by a different model.

The kit's verifier agent runs on the same model that did the work, so it can
share that model's blind spots. This tool sends a compact review packet to a
command-line tool you configure (Codex CLI, Gemini CLI, Claude with another
model, a local model) and records its verdict.

Off by default. Enable in .claude/kit/config.json:

  "second_opinion": {"enabled": true, "command": "codex exec -", "timeout_s": 900}

The packet goes to stdin, or to a file when the command contains {prompt_file}.
Before anything is sent, files that usually hold secrets are left out of the
diff and the whole packet is scanned; any hit stops the review.

    review.py --requirement "what the change must do" [--base REV] [--dry-run]

Exit codes: 0 ACCEPT, 1 REJECT, 2 ESCALATE or no verdict, 3 not enabled,
4 refused (secret found), 5 the command failed or timed out.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def find_root() -> Path:
    here = Path(__file__).resolve()
    if here.parent.name == "kit" and here.parent.parent.name == ".claude":
        return here.parents[2]
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env).resolve() if env else Path.cwd().resolve()


ROOT = find_root()
KIT = ROOT / ".claude" / "kit"
REVIEWS = KIT / "reviews"
sys.path.insert(0, str(KIT))

EXCLUDES = [":(exclude,glob)**/.env", ":(exclude,glob)**/.env.*", ":(exclude,glob)**/*.pem", ":(exclude,glob)**/*.key",
            ":(exclude,glob)**/id_rsa*", ":(exclude,glob)**/id_ed25519*", ":(exclude,glob)**/credentials*",
            ":(exclude,glob)**/secrets/**", ":(exclude,glob)**/*.p12", ":(exclude,glob)**/*.pfx"]
VERDICT = re.compile(r"VERDICT\s*[:=]\s*\**\s*(ACCEPT|REJECT|ESCALATE)", re.I)

INSTRUCTIONS = """You are an independent reviewer. A different AI model wrote the change below; your job is to check it,
not to trust it. Judge only from the evidence in this packet. Do not edit files.

Check, in order:
1. Does the change do what the requirement asks, fully and nothing more?
2. Were tests, assertions, tolerances or checks weakened, skipped or deleted to make things pass?
3. If evaluation data, metric code or baselines are listed as protected, did any of them change? Are the reported
   results traceable to logged runs, with the same seeds and data, failed runs included?
4. Does the change contradict an approved decision, or retry a recorded dead end?
5. Anything risky: data loss, security, silent behaviour changes, unrelated edits.

Answer in this format, nothing before it:
VERDICT: ACCEPT | REJECT | ESCALATE
- reason (cite file and line or the packet section)
- ...
Use REJECT for a concrete defect, ESCALATE when the packet is not enough to decide or a human judgement is needed.
"""


def config() -> dict:
    try:
        return json.loads((KIT / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30,
                             encoding="utf-8", errors="replace")
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def untracked_files() -> list:
    # The kit's own files are infrastructure, not part of the change under review.
    return [f for f in git("ls-files", "--others", "--exclude-standard", "--", ".", *EXCLUDES).splitlines()
            if f and not f.startswith((".claude/", "knowledge/"))]


def untracked_text(limit: int = 200_000) -> str:
    """New files are part of the change too; git diff does not show them until they are added."""
    out = []
    for rel in untracked_files():
        p = ROOT / rel
        try:
            if p.stat().st_size > limit:
                out.append(f"\n--- /dev/null\n+++ b/{rel}\n[new file, {p.stat().st_size} bytes, not included]\n")
                continue
            raw = p.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:4096]:
            out.append(f"\n--- /dev/null\n+++ b/{rel}\n[new binary file]\n")
            continue
        body = raw.decode("utf-8", errors="replace").splitlines()
        out.append(f"\n--- /dev/null\n+++ b/{rel}\n" + "\n".join("+" + line for line in body) + "\n")
    return "".join(out)


def diff_text(base: str) -> tuple:
    if base:
        committed = git("diff", f"{base}...HEAD", "--", ".", *EXCLUDES)
        label = f"{base}...HEAD plus uncommitted changes"
    else:
        committed = ""
        label = "uncommitted changes"
    work = git("diff", "HEAD", "--", ".", *EXCLUDES)
    text = committed + work + untracked_text()
    if not text.strip() and not base:
        text = git("diff", "HEAD~1", "HEAD", "--", ".", *EXCLUDES)
        label = "last commit (HEAD~1..HEAD)"
    return text, label


def ledger_text() -> str:
    try:
        import ledger  # noqa: PLC0415

        led = ledger.load(ROOT)
        return "" if ledger.is_empty(led) else ledger.compact_context(led, 4000)
    except Exception:  # noqa: BLE001
        return ""


def research_text() -> str:
    if not config().get("research", {}).get("protected_paths"):
        return ""
    py = sys.executable
    parts = []
    for args in (["check"], ["list", "--last", "15"]):
        try:
            out = subprocess.run([py, str(KIT / "runlog.py"), *args], cwd=ROOT, capture_output=True, text=True,
                                 timeout=300, encoding="utf-8", errors="replace")
            parts.append(f"$ runlog.py {' '.join(args)}\n{out.stdout.strip()}")
        except (OSError, subprocess.SubprocessError) as exc:
            parts.append(f"runlog.py {' '.join(args)} failed: {exc}")
    return "\n\n".join(parts)


def build_packet(requirement: str, base: str, evidence: str, max_chars: int) -> tuple:
    diff, label = diff_text(base)
    full_change = diff
    truncated = len(diff) > max_chars
    if truncated:
        diff = diff[:max_chars] + f"\n[... diff truncated at {max_chars} characters of {len(diff)} ...]\n"
    sections = [INSTRUCTIONS, "## Requirement\n\n" + (requirement.strip() or "(not given: judge from the diff and the ledger goal)")]
    led = ledger_text()
    if led:
        sections.append("## Task ledger (goal, approved and proposed decisions, dead ends)\n\n" + led)
    res = research_text()
    if res:
        sections.append("## Research integrity evidence\n\n" + res)
    if evidence.strip():
        sections.append("## Verification evidence supplied by the implementer\n\n" + evidence.strip())
    files = git("diff", "--name-only", f"{base}...HEAD" if base else "HEAD", "--", ".", *EXCLUDES).strip()
    new_files = untracked_files()
    if new_files:
        files = (files + "\n" if files else "") + "\n".join(f"{f} (new, untracked)" for f in new_files)
    sections.append(f"## Changed files ({label})\n\n{files or '(none listed)'}")
    sections.append(f"## Diff ({label})\n\n```diff\n{diff or '(empty diff)'}\n```")
    return "\n\n".join(sections) + "\n", truncated, full_change


def split_command(command: str) -> list:
    if os.name == "nt":
        parts = [p[1:-1] if len(p) > 1 and p[0] == p[-1] and p[0] in "\"'" else p for p in shlex.split(command, posix=False)]
    else:
        parts = shlex.split(command)
    if parts:
        resolved = shutil.which(parts[0])
        if resolved:
            parts[0] = resolved
    return parts


def log_signal(verdict: str) -> None:
    try:
        path = KIT / "signals" / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": dt.datetime.now().isoformat(timespec="seconds"), "event": "second_opinion", "verdict": verdict}) + "\n")
    except OSError:
        pass


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="review.py", description="Second-opinion review by a different model")
    ap.add_argument("--requirement", default="")
    ap.add_argument("--requirement-file", default="")
    ap.add_argument("--evidence-file", default="", help="test output or verifier table to include")
    ap.add_argument("--base", default="", help="base revision; default: uncommitted changes, else the last commit")
    ap.add_argument("--dry-run", action="store_true", help="write the packet and show what would be sent, send nothing")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

    so = config().get("second_opinion", {})
    command = str(so.get("command") or "").strip()
    if not args.dry_run and not (so.get("enabled") and command):
        print("second opinion is off. Set second_opinion.enabled to true and second_opinion.command in "
              ".claude/kit/config.json (see docs/how-it-works.md#second-opinion-review), or use --dry-run.")
        return 3

    requirement = args.requirement
    if args.requirement_file:
        requirement = (ROOT / args.requirement_file).read_text(encoding="utf-8", errors="replace")
    evidence = (ROOT / args.evidence_file).read_text(encoding="utf-8", errors="replace") if args.evidence_file else ""
    packet, truncated, full_change = build_packet(requirement, args.base, evidence, int(so.get("max_diff_chars", 60000)))

    import kg  # noqa: PLC0415

    # Scan the whole change, not only the part that fits in the packet.
    hits = sorted(set(kg.find_secrets(packet) + kg.find_secrets(full_change)))
    if hits:
        print(f"refused: the review packet contains what looks like a secret ({', '.join(hits)}). "
              "Remove it from the change or exclude that file, then run again. Nothing was sent.")
        log_signal("refused")
        return 4

    REVIEWS.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    packet_file = REVIEWS / f"{stamp}-packet.md"
    packet_file.write_text(packet, encoding="utf-8")

    if args.dry_run:
        print(f"dry run: packet of {len(packet)} characters written to {packet_file.relative_to(ROOT).as_posix()}"
              + (" (diff truncated)" if truncated else ""))
        print(f"would run: {command or '(no command configured)'}")
        return 0

    argv_cmd = split_command(command.replace("{prompt_file}", str(packet_file)))
    use_stdin = "{prompt_file}" not in command
    try:
        res = subprocess.run(argv_cmd, cwd=ROOT, input=packet if use_stdin else None, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=int(so.get("timeout_s", 900)))
    except FileNotFoundError:
        print(f"could not start {argv_cmd[0] if argv_cmd else command!r}; check second_opinion.command")
        return 5
    except subprocess.TimeoutExpired:
        print(f"the reviewer did not answer within {so.get('timeout_s', 900)} seconds")
        log_signal("timeout")
        return 5
    output = (res.stdout or "") + (("\n[stderr]\n" + res.stderr) if res.returncode != 0 and res.stderr else "")
    found = VERDICT.findall(output)
    verdict = found[-1].upper() if found else "NONE"
    report = REVIEWS / f"{stamp}-review.md"
    report.write_text(f"# Second opinion {stamp}\n\nCommand: `{command}`\nExit: {res.returncode}\nVerdict: {verdict}\n"
                      f"Packet: {packet_file.name} ({len(packet)} characters)\n\n## Reviewer output\n\n{output.strip()}\n", encoding="utf-8")
    log_signal(verdict)
    print(f"second opinion: {verdict} (report {report.relative_to(ROOT).as_posix()})")
    body = output.strip()
    print(body[:4000] + ("\n[...]" if len(body) > 4000 else ""))
    if res.returncode != 0 and verdict == "NONE":
        return 5
    return {"ACCEPT": 0, "REJECT": 1}.get(verdict, 2)


if __name__ == "__main__":
    sys.exit(main())
