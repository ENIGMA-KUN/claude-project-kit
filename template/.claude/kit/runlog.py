#!/usr/bin/env python3
"""Experiment run log and evaluation fingerprints for the project kit.

Research results are only as good as the evaluation behind them. This tool
makes two things checkable without trusting anyone's summary:

1. The evaluation did not move. Paths listed in research.protected_paths
   (evaluation data, metric code, baseline configs) are fingerprinted into a
   baseline; `check` reports every file that changed since.
2. Reported numbers come from real runs. Experiments run through `run`, which
   records the command, commit, seed, exit code, protected fingerprints and the
   metrics printed by the run. `find` traces a number back to a run.

Commands:
  baseline                          fingerprint protected paths as the reference
  check [--json]                    list protected files changed since the baseline (exit 1 if any)
  run [--name N] [--seed S] [--metrics-file F] -- COMMAND...
  list [--last N] [--name N]
  report [--name N]                 Markdown table of every run, failed ones included
  find --metric M --value V [--tol T]
  compare RUN_A RUN_B
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BIG_FILE = 64 * 1024 * 1024
MAX_FILES = 20000
METRIC_LINE = re.compile(r"^\s*([A-Za-z][\w./@-]*)\s*[:=]\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*%?\s*$")
SEED_ARG = re.compile(r"(?:--seed[= ]|seed=)(\d+)")


def find_root() -> Path:
    here = Path(__file__).resolve()
    if here.parent.name == "kit" and here.parent.parent.name == ".claude":
        return here.parents[2]
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env).resolve() if env else Path.cwd().resolve()


ROOT = find_root()
KIT = ROOT / ".claude" / "kit"
RUNS = KIT / "runs.jsonl"
BASELINE = KIT / "research-baseline.json"


def config() -> dict:
    try:
        return json.loads((KIT / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def globs() -> list:
    out = []
    for g in config().get("research", {}).get("protected_paths", []):
        g = str(g).strip().replace("\\", "/")
        while g.startswith("./"):
            g = g[2:]
        if g:
            out.append(g.rstrip("/"))
    return out


def git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10,
                             encoding="utf-8", errors="replace")
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def redact(text: str) -> str:
    sys.path.insert(0, str(KIT))
    try:
        import kg  # noqa: PLC0415

        for pat in kg.SECRET_PATTERNS:
            text = pat.sub("[REDACTED]", text)
    except Exception:  # noqa: BLE001
        pass
    return text


# ------------------------------------------------------------- fingerprints


def files_for(glob: str) -> list:
    skip = {".git", "node_modules", ".venv", "venv", "__pycache__"}
    if not any(ch in glob for ch in "*?["):
        p = ROOT / glob
        if p.is_file():
            return [glob]
        if p.is_dir():
            out = []
            for dp, dns, fns in os.walk(p):
                dns[:] = [d for d in dns if d not in skip]
                for f in fns:
                    out.append(os.path.relpath(os.path.join(dp, f), ROOT).replace(os.sep, "/"))
                    if len(out) >= MAX_FILES:
                        return sorted(out)
            return sorted(out)
        return []
    base = glob.split("*", 1)[0].split("?", 1)[0].split("[", 1)[0]
    base_dir = ROOT / (base.rsplit("/", 1)[0] if "/" in base else "")
    out = []
    if base_dir.is_dir():
        for dp, dns, fns in os.walk(base_dir):
            dns[:] = [d for d in dns if d not in skip]
            for f in fns:
                rel = os.path.relpath(os.path.join(dp, f), ROOT).replace(os.sep, "/")
                if fnmatch.fnmatch(rel, glob) or fnmatch.fnmatch(rel, glob.replace("/**", "")):
                    out.append(rel)
                    if len(out) >= MAX_FILES:
                        break
    return sorted(out)


def file_digest(rel: str) -> str:
    p = ROOT / rel
    try:
        st = p.stat()
        if st.st_size > BIG_FILE:
            return f"size:{st.st_size}:mtime:{int(st.st_mtime)}"
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()[:16]
    except OSError:
        return "unreadable"


def fingerprint() -> dict:
    result = {}
    for g in globs():
        files = {rel: file_digest(rel) for rel in files_for(g)}
        combined = hashlib.sha256("\n".join(f"{k}={v}" for k, v in sorted(files.items())).encode()).hexdigest()[:16]
        result[g] = {"digest": combined, "count": len(files), "files": files}
    return result


def diff_fingerprints(old: dict, new: dict) -> dict:
    changes = {}
    for g in sorted(set(old) | set(new)):
        a, b = old.get(g, {}).get("files", {}), new.get(g, {}).get("files", {})
        changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
        added = sorted(set(b) - set(a))
        removed = sorted(set(a) - set(b))
        if changed or added or removed or g not in old or g not in new:
            changes[g] = {"changed": changed, "added": added, "removed": removed,
                          "note": "new protected path, not in baseline" if g not in old else ("no longer protected" if g not in new else "")}
    return changes


# --------------------------------------------------------------------- runs


def read_runs() -> list:
    if not RUNS.exists():
        return []
    out = []
    for line in RUNS.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def parse_metrics(lines: list) -> dict:
    metrics = {}
    for line in lines:
        s = line.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                obj = json.loads(s)
                metrics.update({k: v for k, v in obj.items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
                continue
            except ValueError:
                pass
        m = METRIC_LINE.match(line)
        if m:
            metrics[m.group(1)] = float(m.group(2))
    return metrics


def cmd_run(args) -> int:
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("give the command after --, for example: runlog.py run --name baseline -- python train.py --seed 1")
        return 2
    shell = len(command) == 1 and " " in command[0]
    text_cmd = command[0] if shell else " ".join(command)
    seed = args.seed or (SEED_ARG.search(text_cmd).group(1) if SEED_ARG.search(text_cmd) else "")
    before = fingerprint()
    base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else None
    start = time.time()
    lines = []
    proc = subprocess.Popen(command[0] if shell else command, shell=shell, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for line in proc.stdout:
        sys.stdout.write(line)
        lines.append(line.rstrip("\n"))
    code = proc.wait()
    duration = round(time.time() - start, 2)
    metrics = parse_metrics(lines[-200:])
    if args.metrics_file:
        try:
            data = json.loads((ROOT / args.metrics_file).read_text(encoding="utf-8"))
            metrics.update({k: v for k, v in data.items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
        except (OSError, ValueError) as exc:
            print(f"warning: could not read metrics file: {exc}")
    after = fingerprint()
    runs = read_runs()
    record = {
        "id": f"r{len(runs) + 1:04d}",
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "name": args.name or "",
        "command": redact(text_cmd)[:500],
        "commit": git("rev-parse", "--short", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "seed": str(seed),
        "exit": code,
        "duration_s": duration,
        "protected": {g: v["digest"] for g, v in after.items()},
        "protected_changed_since_baseline": sorted(diff_fingerprints(base["globs"], after)) if base else None,
        "protected_changed_during_run": sorted(diff_fingerprints(before, after)),
        "metrics": metrics,
        "tail": redact("\n".join(lines[-30:]))[-3000:],
    }
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    with RUNS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    flag = ""
    if record["protected_changed_during_run"]:
        flag = "  WARNING: the run itself changed protected files"
    elif record["protected_changed_since_baseline"]:
        flag = "  WARNING: protected files differ from the baseline"
    print(f"\n[runlog] {record['id']} exit {code} in {duration}s, metrics {metrics or 'none parsed'}{flag}")
    return code


def cmd_list(args) -> int:
    runs = [r for r in read_runs() if not args.name or r.get("name") == args.name][-args.last:]
    for r in runs:
        status = "ok" if r["exit"] == 0 else f"exit {r['exit']}"
        warn = " protected-changed" if r.get("protected_changed_during_run") or r.get("protected_changed_since_baseline") else ""
        print(f"{r['id']} {r['ts'][:16]} {r.get('name') or '-':12} seed={r.get('seed') or '-':6} {status:8} {r.get('commit') or '-'}{'*' if r.get('dirty') else ''}{warn}  {json.dumps(r.get('metrics', {}))[:120]}")
    print(f"{len(runs)} runs")
    return 0


def cmd_report(args) -> int:
    runs = [r for r in read_runs() if not args.name or r.get("name") == args.name]
    keys = sorted({k for r in runs for k in r.get("metrics", {})})
    head = ["run", "time", "name", "seed", "commit", "exit", "eval unchanged"] + keys
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for r in runs:
        unchanged = "yes" if not (r.get("protected_changed_during_run") or r.get("protected_changed_since_baseline")) else "NO"
        if r.get("protected_changed_since_baseline") is None and not r.get("protected_changed_during_run"):
            unchanged = "no baseline"
        row = [r["id"], r["ts"][:16], r.get("name") or "", r.get("seed") or "", (r.get("commit") or "") + ("*" if r.get("dirty") else ""),
               str(r["exit"]), unchanged] + [f"{r['metrics'][k]:g}" if k in r.get("metrics", {}) else "" for k in keys]
        print("| " + " | ".join(row) + " |")
    print(f"\n{len(runs)} runs listed, including failed ones. `*` marks uncommitted changes at run time.")
    return 0


def cmd_find(args) -> int:
    hits = [r for r in read_runs() if args.metric in r.get("metrics", {}) and abs(r["metrics"][args.metric] - args.value) <= args.tol]
    for r in hits:
        print(f"{r['id']} {r['ts'][:16]} {r.get('name') or '-'} seed={r.get('seed') or '-'} exit={r['exit']} {args.metric}={r['metrics'][args.metric]:g}")
    if not hits:
        print(f"no logged run reports {args.metric}={args.value:g} (tolerance {args.tol:g})")
        return 1
    return 0


def cmd_compare(args) -> int:
    runs = {r["id"]: r for r in read_runs()}
    a, b = runs.get(args.a), runs.get(args.b)
    if not a or not b:
        print("unknown run id")
        return 2
    for field in ("name", "commit", "dirty", "seed", "command", "exit"):
        mark = "" if a.get(field) == b.get(field) else "   <- differs"
        print(f"{field:8} {str(a.get(field))[:60]:60} | {str(b.get(field))[:60]}{mark}")
    for g in sorted(set(a.get("protected", {})) | set(b.get("protected", {}))):
        same = a.get("protected", {}).get(g) == b.get("protected", {}).get(g)
        print(f"protected {g}: {'same' if same else 'DIFFERENT'}")
    for k in sorted(set(a.get("metrics", {})) | set(b.get("metrics", {}))):
        print(f"metric {k:20} {a.get('metrics', {}).get(k, '-')!s:>12} | {b.get('metrics', {}).get(k, '-')!s:>12}")
    return 0


def cmd_baseline(args) -> int:
    if not globs():
        print("research.protected_paths is empty in .claude/kit/config.json; nothing to fingerprint")
        return 2
    fp = fingerprint()
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps({"created": dt.datetime.now().isoformat(timespec="seconds"), "commit": git("rev-parse", "--short", "HEAD"),
                                    "globs": fp}, indent=1), encoding="utf-8")
    for g, v in fp.items():
        print(f"{g}: {v['count']} files, digest {v['digest']}")
    print(f"baseline written to {BASELINE.relative_to(ROOT).as_posix()}")
    return 0


def cmd_check(args) -> int:
    if not BASELINE.exists():
        print("no baseline yet; run `runlog.py baseline` once the evaluation setup is final")
        return 2
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    changes = diff_fingerprints(base["globs"], fingerprint())
    if args.json:
        print(json.dumps({"baseline": base.get("created"), "changes": changes}, indent=1))
    elif not changes:
        print(f"protected paths unchanged since baseline {base.get('created')}")
    else:
        for g, c in changes.items():
            print(f"{g}: {len(c['changed'])} changed, {len(c['added'])} added, {len(c['removed'])} removed {c['note']}".rstrip())
            for kind in ("changed", "added", "removed"):
                for f in c[kind][:20]:
                    print(f"  {kind}: {f}")
    return 1 if changes else 0


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="runlog.py", description="Experiment run log and evaluation fingerprints")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("baseline")
    c = sub.add_parser("check")
    c.add_argument("--json", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--name", default="")
    r.add_argument("--seed", default="")
    r.add_argument("--metrics-file", default="")
    r.add_argument("command", nargs=argparse.REMAINDER)
    ls = sub.add_parser("list")
    ls.add_argument("--last", type=int, default=20)
    ls.add_argument("--name", default="")
    rp = sub.add_parser("report")
    rp.add_argument("--name", default="")
    f = sub.add_parser("find")
    f.add_argument("--metric", required=True)
    f.add_argument("--value", type=float, required=True)
    f.add_argument("--tol", type=float, default=1e-6)
    cp = sub.add_parser("compare")
    cp.add_argument("a")
    cp.add_argument("b")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    return {"baseline": cmd_baseline, "check": cmd_check, "run": cmd_run, "list": cmd_list, "report": cmd_report,
            "find": cmd_find, "compare": cmd_compare}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
