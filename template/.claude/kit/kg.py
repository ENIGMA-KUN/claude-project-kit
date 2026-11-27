#!/usr/bin/env python3
"""Knowledge graph tool for the project kit.

Nodes are Markdown files under knowledge/ with YAML frontmatter. A node's id is
its path relative to knowledge/, without the .md suffix (for example
"lessons/use-uv-not-pip"). Typed edges come from the `relations` frontmatter
map. Untyped edges come from Markdown links between nodes.

Standard library only, so it runs wherever Claude Code can run Python.

Commands:
  build                 regenerate knowledge/index.md and knowledge/_graph.json
  validate [--strict]   schema, edge, drift, staleness and secret checks
  query TEXT            BM25 search over active nodes, with 1-hop neighbours
  show ID               print one node with its edges
  new TYPE SLUG         scaffold a node with dated frontmatter
  stale                 nodes past review_by or whose paths no longer exist
  stats [--json]        counts used by hooks and self-consistency checks
  signals [--days N]    friction summary and lesson effectiveness
  codemap               regenerate .claude/kit/code-map.yaml from the file tree
  mermaid               print the graph as a Mermaid flowchart
  log MESSAGE           prepend an entry to knowledge/log.md
  doctor                installation health and context-maturity estimate
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

KIT_VERSION = "1.2.0"

TYPE_DIRS = {
    "architecture": "architecture",
    "decision": "decisions",
    "lesson": "lessons",
    "solution": "solutions",
    "concept": "concepts",
    "procedure": "procedures",
    "proposal": "_inbox",
}
CORE_TYPES = set(TYPE_DIRS)
NODE_STATUSES = {"candidate", "active", "superseded", "archived"}
PROPOSAL_STATUSES = {"proposed", "accepted", "rejected", "deferred"}
SERVED_STATUSES = {"active"}
STRONG_RELATIONS = {"depends_on", "supersedes", "superseded_by", "part_of", "implements"}
KNOWN_RELATIONS = STRONG_RELATIONS | {"related", "contradicts", "caused_by", "fixes", "example_of"}
RESERVED_FILES = {"index.md", "log.md", "readme.md"}
DEFAULT_REVIEW_DAYS = {
    "architecture": 60,
    "decision": 180,
    "lesson": 90,
    "solution": 120,
    "concept": 180,
    "procedure": 90,
    "proposal": 30,
}
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build",
    ".next", ".nuxt", "target", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    ".idea", ".vscode", "coverage", ".gradle", ".terraform", ".cache", "site-packages",
}

# Deterministic secret scan. A prompt line asking the model to skip secrets is
# not a control; this is. Values that look like placeholders are ignored.
SECRET_RULES = [
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("sk- style API key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("credential assignment", re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*['\"]?(?![$<{%(])(?!your)[^\s'\"]{12,}")),
]
SECRET_PATTERNS = [pat for _, pat in SECRET_RULES]

STOPWORDS = set(
    """a an and are as at be but by for from has have how i if in into is it its of on or our so
    that the their then there these this to was we what when where which who why will with you
    your do does did not can should would could just also any all more most some than too very
    about after before over under up out get got may might must me my please let lets ok okay
    here now want need like make sure""".split()
)

K1, B = 1.2, 0.75


# --------------------------------------------------------------------------- paths


def find_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    here = Path(__file__).resolve()
    if here.parent.name == "kit" and here.parent.parent.name == ".claude":
        return here.parents[2]
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and Path(env).is_dir():
        return Path(env).resolve()
    cwd = Path.cwd().resolve()
    for cand in [cwd, *cwd.parents]:
        if (cand / ".claude" / "kit").is_dir() or (cand / "knowledge").is_dir():
            return cand
    return cwd


def today() -> dt.date:
    return dt.date.today()


def parse_date(value) -> dt.date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def load_config(root: Path) -> dict:
    path = root / ".claude" / "kit" / "config.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(root: Path, cfg: dict) -> None:
    path = root / ".claude" / "kit" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------- frontmatter


def _split_inline_list(s: str) -> list:
    items, buf, quote = [], [], None
    for ch in s:
        if quote:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
        elif ch in "\"'" and not "".join(buf).strip():
            quote = ch
        elif ch == ",":
            items.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    last = "".join(buf).strip()
    if last:
        items.append(last)
    return [i for i in items if i]


def _parse_value(raw: str):
    v = raw.strip()
    if not v:
        return ""
    if v[0] in "\"'":
        end = v.find(v[0], 1)
        return v[1:end] if end != -1 else v[1:]
    if v[0] == "[":
        depth, quote = 0, None
        for i, ch in enumerate(v):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return _split_inline_list(v[1:i])
        return _split_inline_list(v[1:])
    v = re.split(r"\s+#", v, maxsplit=1)[0].strip()
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    if v.lower() in ("null", "~"):
        return None
    return v


def parse_frontmatter(text: str):
    """Parse the YAML subset the kit uses. Returns (meta, body, error)."""
    text = text.lstrip("﻿")
    if not text.startswith("---"):
        return {}, text, "missing frontmatter"
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text, "unterminated frontmatter"
    body = "\n".join(lines[end + 1:])
    meta: dict = {}
    key = None
    sub = None
    sub_indent = 0
    for n, raw in enumerate(lines[1:end], start=2):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if indent == 0:
            k, sep, v = line.partition(":")
            if not sep:
                return meta, body, f"frontmatter line {n}: expected 'key: value'"
            key, sub = k.strip(), None
            meta[key] = _parse_value(v) if v.strip() else None
            continue
        if key is None:
            return meta, body, f"frontmatter line {n}: indented line without a parent key"
        if line.startswith("- ") or line == "-":
            item = _parse_value(line[1:].strip())
            if sub is not None and indent > sub_indent and isinstance(meta.get(key), dict):
                meta[key].setdefault(sub, [])
                if not isinstance(meta[key][sub], list):
                    meta[key][sub] = [meta[key][sub]] if meta[key][sub] else []
                meta[key][sub].append(item)
            else:
                if not isinstance(meta.get(key), list):
                    meta[key] = []
                meta[key].append(item)
            continue
        k2, sep, v2 = line.partition(":")
        if not sep:
            return meta, body, f"frontmatter line {n}: expected 'key: value'"
        if not isinstance(meta.get(key), dict):
            meta[key] = {}
        k2 = k2.strip()
        if v2.strip():
            meta[key][k2] = _parse_value(v2)
            sub = None
        else:
            meta[key][k2] = []
            sub, sub_indent = k2, indent
    return meta, body, None


def as_list(value) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [str(value)]


# --------------------------------------------------------------------------- nodes


def normalize_id(ref: str, base_dir: str = "") -> str:
    ref = ref.strip().replace("\\", "/")
    ref = ref.split("#", 1)[0]
    if ref.startswith("./") or ref.startswith("../"):
        parts = [p for p in base_dir.split("/") if p]
        for seg in ref.split("/"):
            if seg == "..":
                if parts:
                    parts.pop()
            elif seg not in (".", ""):
                parts.append(seg)
        ref = "/".join(parts)
    ref = ref.lstrip("/")
    if ref.startswith("knowledge/"):
        ref = ref[len("knowledge/"):]
    if ref.endswith(".md"):
        ref = ref[:-3]
    return ref


LINK_RE = re.compile(r"\]\(([^)\s]+?\.md)(?:#[^)]*)?\)")


def load_nodes(root: Path) -> tuple[dict, list]:
    kdir = root / "knowledge"
    nodes: dict = {}
    problems: list = []
    if not kdir.is_dir():
        return nodes, problems
    for path in sorted(kdir.rglob("*.md")):
        rel = path.relative_to(kdir)
        parts = rel.parts
        if any(p.startswith(".") for p in parts):
            continue
        if path.name.lower() in RESERVED_FILES or path.name.startswith("_"):
            continue
        if any(p.startswith("_") and p != "_inbox" for p in parts[:-1]):
            continue
        node_id = rel.as_posix()[:-3]
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(("error", node_id, f"unreadable: {exc}"))
            continue
        meta, body, err = parse_frontmatter(text)
        if err:
            problems.append(("error", node_id, err))
        ntype = str(meta.get("type") or "").strip()
        default_status = "proposed" if ntype == "proposal" else "active"
        status = str(meta.get("status") or default_status).strip()
        base_dir = rel.parent.as_posix() if rel.parent.as_posix() != "." else ""
        relations: dict = {}
        rel_meta = meta.get("relations")
        if isinstance(rel_meta, dict):
            for rname, targets in rel_meta.items():
                ids = [normalize_id(t, base_dir) for t in as_list(targets)]
                if ids:
                    relations[rname] = ids
        links = []
        for m in LINK_RE.finditer(body):
            target = m.group(1)
            if target.startswith("http"):
                continue
            links.append(normalize_id(target if target.startswith(("./", "../", "/")) else "./" + target, base_dir))
        title = str(meta.get("title") or "").strip()
        if not title:
            h1 = re.search(r"^#\s+(.+)$", body, re.M)
            title = h1.group(1).strip() if h1 else path.stem.replace("-", " ")
        nodes[node_id] = {
            "id": node_id,
            "file": "knowledge/" + rel.as_posix(),
            "type": ntype,
            "status": status,
            "title": title,
            "description": str(meta.get("description") or "").strip(),
            "tags": as_list(meta.get("tags")),
            "rule": str(meta.get("rule") or "").strip(),
            "trigger": as_list(meta.get("trigger")),
            "paths": as_list(meta.get("paths")),
            "created": str(meta.get("created") or ""),
            "updated": str(meta.get("updated") or ""),
            "review_by": str(meta.get("review_by") or ""),
            "severity": str(meta.get("severity") or ""),
            "confidence": str(meta.get("confidence") or ""),
            "source": str(meta.get("source") or ""),
            "relations": relations,
            "links": sorted(set(links)),
            "meta": meta,
            "body": body,
        }
    return nodes, problems


def edges_of(nodes: dict) -> list:
    out = []
    for n in nodes.values():
        for rname, targets in n["relations"].items():
            for t in targets:
                out.append((n["id"], rname, t))
        typed = {t for ts in n["relations"].values() for t in ts}
        for t in n["links"]:
            if t not in typed and t != n["id"]:
                out.append((n["id"], "links", t))
    return out


def neighbours(nodes: dict, node_id: str) -> list:
    res = []
    for src, rel, dst in edges_of(nodes):
        if src == node_id and dst in nodes:
            res.append((rel, dst))
        elif dst == node_id and src in nodes:
            res.append((f"<-{rel}", src))
    return res


# -------------------------------------------------------------------------- search


def _stem(tok: str) -> str:
    if len(tok) > 5 and tok.endswith("ing"):
        return tok[:-3]
    if len(tok) > 4 and tok.endswith("ed"):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def tokenize(text: str) -> list:
    out = []
    for tok in re.findall(r"[a-z0-9_]+", text.lower()):
        pieces = [tok] + ([p for p in tok.split("_") if p] if "_" in tok else [])
        for p in pieces:
            if len(p) < 2 or p in STOPWORDS or p.isdigit():
                continue
            out.append(_stem(p))
    return out


def doc_tokens(node: dict) -> list:
    return (
        tokenize(node["title"]) * 3
        + tokenize(" ".join(node["tags"])) * 2
        + tokenize(node["description"]) * 2
        + tokenize(node["rule"]) * 2
        + tokenize(" ".join(node["trigger"])) * 3
        + tokenize(" ".join(node["paths"]))
        + tokenize(node["body"])
    )


class Index:
    def __init__(self, nodes: dict, statuses: set | None = None):
        self.docs = []
        for n in nodes.values():
            if statuses is not None and n["status"] not in statuses:
                continue
            toks = doc_tokens(n)
            self.docs.append((n, Counter(toks), max(len(toks), 1)))
        self.n = len(self.docs)
        self.avgdl = (sum(d[2] for d in self.docs) / self.n) if self.n else 1.0
        self.df: Counter = Counter()
        for _, counts, _ in self.docs:
            self.df.update(counts.keys())

    def search(self, query: str, k: int = 5, min_terms: int = 1, types: set | None = None) -> list:
        terms = list(dict.fromkeys(tokenize(query)))
        results = []
        for node, counts, dl in self.docs:
            if types and node["type"] not in types:
                continue
            score, matched = 0.0, 0
            for t in terms:
                f = counts.get(t)
                if not f:
                    continue
                matched += 1
                idf = math.log(1 + (self.n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                score += idf * f * (K1 + 1) / (f + K1 * (1 - B + B * dl / self.avgdl))
            if matched >= min_terms and score > 0:
                results.append((round(score, 3), matched, node))
        results.sort(key=lambda r: (-r[0], r[2]["id"]))
        return results[:k]


# ---------------------------------------------------------------------- validation


def path_exists(root: Path, pattern: str) -> bool:
    pattern = pattern.strip()
    while pattern.startswith("./"):
        pattern = pattern[2:]
    if not pattern:
        return True
    if not any(ch in pattern for ch in "*?["):
        return (root / pattern).exists()
    try:
        return next(iter(root.glob(pattern)), None) is not None
    except (ValueError, OSError):
        return True


def find_secrets(text: str) -> list:
    """Return the kinds of secret found. Never echo the matched value itself."""
    return [label for label, pat in SECRET_RULES if pat.search(text)]


def validate(root: Path, nodes: dict, problems: list) -> tuple[list, list]:
    errors = [f"{nid}: {msg}" for lvl, nid, msg in problems if lvl == "error"]
    warnings = []
    titles = defaultdict(list)
    superseded_targets = {t for n in nodes.values() for t in n["relations"].get("supersedes", [])}
    for n in nodes.values():
        nid = n["id"]
        if not n["type"]:
            errors.append(f"{nid}: missing required 'type'")
        elif n["type"] not in CORE_TYPES:
            warnings.append(f"{nid}: unknown type '{n['type']}' (allowed, but not one of {sorted(CORE_TYPES)})")
        allowed = PROPOSAL_STATUSES if n["type"] == "proposal" else NODE_STATUSES
        if n["status"] not in allowed:
            errors.append(f"{nid}: status '{n['status']}' not in {sorted(allowed)}")
        if not n["description"] and n["type"] != "proposal":
            warnings.append(f"{nid}: no description (retrieval and the index rely on it)")
        if n["type"] == "lesson" and not n["rule"]:
            warnings.append(f"{nid}: lesson without a one-line 'rule'")
        if n["status"] == "superseded" and nid not in superseded_targets and not n["relations"].get("superseded_by"):
            warnings.append(f"{nid}: superseded but nothing points to its successor")
        for rname, targets in n["relations"].items():
            if rname not in KNOWN_RELATIONS:
                warnings.append(f"{nid}: unknown relation '{rname}'")
            for t in targets:
                if t not in nodes:
                    msg = f"{nid}: {rname} -> '{t}' does not exist"
                    (errors if rname in STRONG_RELATIONS else warnings).append(msg)
                elif rname == "contradicts" and n["status"] == "active" and nodes[t]["status"] == "active":
                    warnings.append(f"{nid}: unresolved contradiction with active node '{t}'")
        for t in n["links"]:
            if t not in nodes and not (root / "knowledge" / (t + ".md")).exists():
                warnings.append(f"{nid}: broken link to '{t}'")
        review = parse_date(n["review_by"])
        if review and review < today() and n["status"] in ("active", "candidate"):
            warnings.append(f"{nid}: stale, review_by {review} has passed")
        if n["status"] == "active":
            for pat in n["paths"]:
                if not path_exists(root, pat):
                    warnings.append(f"{nid}: drift, path '{pat}' matches nothing in the repo")
        secrets = find_secrets(n["body"] + "\n" + json.dumps(n["meta"], default=str))
        if secrets:
            errors.append(f"{nid}: possible secret in node ({', '.join(secrets)}); remove it")
        if n["status"] == "active":
            titles[n["title"].lower()].append(nid)
    for title, ids in titles.items():
        if len(ids) > 1:
            warnings.append(f"duplicate active title '{title}': {', '.join(ids)}")
    return errors, warnings


def stale_report(root: Path, nodes: dict) -> list:
    out = []
    for n in nodes.values():
        if n["status"] not in ("active", "candidate"):
            continue
        reasons = []
        review = parse_date(n["review_by"])
        if review and review < today():
            reasons.append(f"review_by {review} passed")
        missing = [p for p in n["paths"] if not path_exists(root, p)]
        if missing:
            reasons.append("paths gone: " + ", ".join(missing))
        if reasons:
            out.append((n["id"], n["title"], "; ".join(reasons)))
    return out


# --------------------------------------------------------------------------- build


def render_index(nodes: dict) -> str:
    by_type = defaultdict(list)
    counts = Counter(n["status"] for n in nodes.values() if n["type"] != "proposal")
    proposals = [n for n in nodes.values() if n["type"] == "proposal" and n["status"] == "proposed"]
    candidates = [n for n in nodes.values() if n["status"] == "candidate"]
    for n in nodes.values():
        if n["status"] == "active":
            by_type[n["type"] or "untyped"].append(n)
    lines = [
        "# Knowledge index",
        "",
        "Generated by `python .claude/kit/kg.py build`. Edit the nodes, not this file.",
        "",
        "Status: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) + f". Built {today()}.",
        "",
    ]
    order = ["architecture", "decision", "concept", "procedure", "solution", "lesson"]
    for t in order + sorted(set(by_type) - set(order)):
        items = sorted(by_type.get(t, []), key=lambda n: n["title"].lower())
        if not items:
            continue
        lines.append(f"## {t.capitalize()} ({len(items)})")
        lines.append("")
        for n in items:
            rel = n["file"][len("knowledge/"):]
            desc = n["rule"] if t == "lesson" and n["rule"] else n["description"]
            lines.append(f"- [{n['title']}]({rel})" + (f": {desc}" if desc else ""))
        lines.append("")
    if candidates:
        lines += [f"## Candidates, not served to sessions ({len(candidates)})", ""]
        for n in sorted(candidates, key=lambda n: n["id"]):
            lines.append(f"- [{n['title']}]({n['file'][len('knowledge/'):]})")
        lines.append("")
    if proposals:
        lines += [f"## Pending proposals ({len(proposals)}), review with /curate", ""]
        for n in sorted(proposals, key=lambda n: n["id"]):
            lines.append(f"- [{n['title']}]({n['file'][len('knowledge/'):]})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build(root: Path, quiet: bool = False) -> dict:
    nodes, problems = load_nodes(root)
    kdir = root / "knowledge"
    kdir.mkdir(parents=True, exist_ok=True)
    (kdir / "index.md").write_text(render_index(nodes), encoding="utf-8")
    graph = {
        "version": KIT_VERSION,
        "built": dt.datetime.now().isoformat(timespec="seconds"),
        "nodes": [
            {k: n[k] for k in ("id", "file", "type", "status", "title", "description", "tags", "rule", "paths", "review_by")}
            for n in nodes.values()
        ],
        "edges": [{"from": s, "rel": r, "to": d} for s, r, d in edges_of(nodes)],
    }
    (kdir / "_graph.json").write_text(json.dumps(graph, indent=1) + "\n", encoding="utf-8")
    if not quiet:
        print(f"built knowledge/index.md and knowledge/_graph.json: {len(nodes)} nodes, {len(graph['edges'])} edges")
    return graph


# -------------------------------------------------------------------------- signals


def signals_path(root: Path) -> Path:
    return root / ".claude" / "kit" / "signals" / "events.jsonl"


def read_events(root: Path, days: int | None = None) -> list:
    path = signals_path(root)
    if not path.exists():
        return []
    cutoff = dt.datetime.now() - dt.timedelta(days=days) if days else None
    events = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if cutoff:
                try:
                    if dt.datetime.fromisoformat(ev.get("ts", "")[:19]) < cutoff:
                        continue
                except ValueError:
                    continue
            events.append(ev)
    return events


def signals_summary(root: Path, nodes: dict, days: int) -> dict:
    events = read_events(root, days)
    by_event = Counter(e.get("event") for e in events)
    by_category = Counter(e.get("category") for e in events if e.get("category"))
    patterns: dict = defaultdict(lambda: {"count": 0, "sessions": set(), "example": ""})
    for e in events:
        if e.get("event") == "tool_failure":
            p = patterns[e.get("key", "?")]
            p["count"] += 1
            p["sessions"].add(e.get("session", "?"))
            p["example"] = p["example"] or e.get("text", "")
    top = sorted(patterns.items(), key=lambda kv: -kv[1]["count"])[:12]
    corrections = [e for e in events if e.get("event") == "correction"][-10:]
    injected = Counter()
    for e in events:
        if e.get("event") == "injected":
            injected.update(e.get("nodes", []))
    lesson_report = []
    all_events = read_events(root)
    for n in nodes.values():
        if n["type"] != "lesson" or n["status"] != "active":
            continue
        created = parse_date(n["created"])
        triggers = [t.lower() for t in n["trigger"]]
        recurrences = 0
        if triggers and created:
            for e in all_events:
                if e.get("event") not in ("tool_failure", "correction"):
                    continue
                if (parse_date(e.get("ts", "")) or dt.date.min) <= created:
                    continue
                text = (e.get("text", "") + " " + e.get("key", "")).lower()
                if any(t in text for t in triggers):
                    recurrences += 1
        lesson_report.append({
            "id": n["id"],
            "injected": injected.get(n["id"], 0),
            "recurrences_since_created": recurrences,
            "has_trigger": bool(triggers),
        })
    sessions = {e.get("session") for e in events if e.get("session")}
    return {
        "days": days,
        "sessions": len(sessions),
        "events": dict(by_event),
        "categories": dict(by_category),
        "top_failure_patterns": [
            {"key": k, "count": v["count"], "sessions": len(v["sessions"]), "example": v["example"][:160]}
            for k, v in top
        ],
        "recent_corrections": [{"ts": e.get("ts", "")[:16], "text": e.get("text", "")[:200]} for e in corrections],
        "injected": dict(injected.most_common(20)),
        "lessons": lesson_report,
    }


# ------------------------------------------------------------------------- codemap


MANIFESTS = [
    "package.json", "pnpm-workspace.yaml", "tsconfig.json", "pyproject.toml", "setup.py", "setup.cfg",
    "requirements.txt", "requirements-dev.txt", "environment.yml", "Pipfile", "poetry.lock", "uv.lock",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "Gemfile", "composer.json",
    "Makefile", "justfile", "Taskfile.yml", "Dockerfile", "docker-compose.yml", "compose.yaml",
    "CMakeLists.txt", "tox.ini", "noxfile.py", "pytest.ini", ".pre-commit-config.yaml", "mkdocs.yml",
    "dvc.yaml", "params.yaml", "MLproject", "Snakefile", "deno.json", "bun.lockb", "turbo.json", "nx.json",
]
LANG_BY_EXT = {
    ".py": "python", ".ipynb": "notebook", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
    ".jsx": "javascript", ".mjs": "javascript", ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin",
    ".rb": "ruby", ".php": "php", ".cs": "csharp", ".cpp": "cpp", ".cc": "cpp", ".c": "c", ".h": "c",
    ".swift": "swift", ".scala": "scala", ".r": "r", ".jl": "julia", ".sql": "sql", ".sh": "shell",
    ".ps1": "powershell", ".vue": "vue", ".svelte": "svelte", ".dart": "dart", ".lua": "lua", ".tf": "terraform",
}
TEST_RE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+\.py$|_test\.(py|go)$|\.(test|spec)\.[a-z]+$")


def list_files(root: Path) -> list:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"], cwd=root,
            capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace",
        )
        if out.returncode == 0 and out.stdout.strip():
            return [line for line in out.stdout.splitlines() if line]
    except (OSError, subprocess.SubprocessError):
        pass
    files = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
        for f in fns:
            files.append(os.path.relpath(os.path.join(dp, f), root).replace(os.sep, "/"))
        if len(files) > 50000:
            break
    return files


def yq(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def codemap(root: Path) -> str:
    files = [f for f in list_files(root) if not f.startswith((".claude/kit/", "knowledge/_graph"))]
    top: dict = defaultdict(lambda: {"count": 0, "ext": Counter()})
    langs: Counter = Counter()
    tests = 0
    manifests = []
    instructions = []
    for f in files:
        parts = f.split("/")
        ext = os.path.splitext(f)[1].lower()
        if ext in LANG_BY_EXT:
            langs[LANG_BY_EXT[ext]] += 1
        if TEST_RE.search(f):
            tests += 1
        if len(parts) <= 3 and parts[-1] in MANIFESTS:
            manifests.append(f)
        if f.startswith(".github/workflows/"):
            manifests.append(f)
        if parts[-1] in ("CLAUDE.md", "AGENTS.md", "CLAUDE.local.md", "GEMINI.md"):
            try:
                text = (root / f).read_text(encoding="utf-8", errors="replace")
                h1 = re.search(r"^#\s+(.+)$", text, re.M)
                instructions.append((f, text.count("\n") + 1, h1.group(1).strip() if h1 else ""))
            except OSError:
                pass
        key = parts[0] + "/" if len(parts) > 1 else "(root files)"
        top[key]["count"] += 1
        if ext:
            top[key]["ext"][ext] += 1
    lines = [
        "# Generated by `python .claude/kit/kg.py codemap`. Do not edit by hand.",
        "# Shape of the repository, for orientation before creating files or modules.",
        f"generated: {yq(dt.datetime.now().isoformat(timespec='seconds'))}",
        f"total_files: {len(files)}",
        f"test_files: {tests}",
        "languages:",
    ]
    for lang, c in langs.most_common(8):
        lines.append(f"  {lang}: {c}")
    lines.append("top_level:")
    for key, info in sorted(top.items(), key=lambda kv: -kv[1]["count"])[:25]:
        exts = ", ".join(e for e, _ in info["ext"].most_common(3))
        lines.append(f"  - {{path: {yq(key)}, files: {info['count']}, main_ext: {yq(exts)}}}")
    lines.append("manifests:")
    for m in sorted(set(manifests))[:30]:
        lines.append(f"  - {yq(m)}")
    lines.append("instruction_files:")
    for f, n, h1 in instructions[:20]:
        lines.append(f"  - {{path: {yq(f)}, lines: {n}, title: {yq(h1)}}}")
    text = "\n".join(lines) + "\n"
    out = root / ".claude" / "kit" / "code-map.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return text


# -------------------------------------------------------------------------- doctor


def rule_frontmatter_has_paths(path: Path) -> bool:
    try:
        meta, _, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False
    return bool(meta.get("paths"))


def doctor(root: Path) -> dict:
    report: dict = {"root": str(root), "python": sys.version.split()[0], "checks": [], "warnings": []}
    cfg = load_config(root)
    claude_md = root / "CLAUDE.md"
    cm_lines = cm_tokens = 0
    sections = 0
    if claude_md.exists():
        text = claude_md.read_text(encoding="utf-8", errors="replace")
        cm_lines = text.count("\n") + 1
        cm_tokens = len(text) // 4
        sections = len(re.findall(r"^## ", text, re.M))
        report["checks"].append(f"CLAUDE.md: {cm_lines} lines, about {cm_tokens} tokens, {sections} sections")
        if cm_lines > 200:
            report["warnings"].append("CLAUDE.md is over 200 lines; move subsystem rules to .claude/rules/ with paths, procedures to skills")
        if "{{" in text:
            report["warnings"].append("CLAUDE.md still has {{placeholders}}; run /kit-init")
    else:
        report["warnings"].append("no CLAUDE.md at the project root")
    rules_dir = root / ".claude" / "rules"
    always_on = scoped = 0
    always_tokens = 0
    if rules_dir.is_dir():
        for p in rules_dir.rglob("*.md"):
            if rule_frontmatter_has_paths(p):
                scoped += 1
            else:
                always_on += 1
                always_tokens += len(p.read_text(encoding="utf-8", errors="replace")) // 4
    report["checks"].append(f"rules: {always_on} always-on (about {always_tokens} tokens), {scoped} path-scoped")
    report["always_on_tokens"] = cm_tokens + always_tokens
    settings = root / ".claude" / "settings.json"
    hooks_ok = False
    if settings.exists():
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
            blob = json.dumps(data.get("hooks", {}))
            hooks_ok = "kit_hook.py" in blob
            report["checks"].append("settings.json: kit hooks " + ("registered" if hooks_ok else "NOT registered"))
        except ValueError as exc:
            report["warnings"].append(f"settings.json is not valid JSON: {exc}")
    else:
        report["warnings"].append("no .claude/settings.json; hooks are not active")
    if not (root / ".claude" / "hooks" / "kit_hook.py").exists():
        report["warnings"].append(".claude/hooks/kit_hook.py is missing")
    incoming = root / ".claude" / "kit" / "incoming"
    if incoming.is_dir() and any(incoming.iterdir()):
        report["warnings"].append("files waiting in .claude/kit/incoming/ to be merged (run /kit-init --refresh)")
    nodes, _ = load_nodes(root)
    active = sum(1 for n in nodes.values() if n["status"] == "active")
    report["checks"].append(f"knowledge: {len(nodes)} nodes, {active} active")
    gi = root / ".gitignore"
    if gi.exists() and ".claude/kit/signals/" not in gi.read_text(encoding="utf-8", errors="replace"):
        report["warnings"].append(".gitignore does not exclude .claude/kit/signals/ (local friction data)")
    canaries = root / ".claude" / "kit" / "canaries.md"
    n_canaries = len(re.findall(r"^### ", canaries.read_text(encoding="utf-8"), re.M)) if canaries.exists() else 0
    events = read_events(root, 30)
    last_curate = parse_date(cfg.get("last_curate"))
    audits = list((root / ".claude" / "kit" / "reports").glob("audit-*.md")) if (root / ".claude" / "kit" / "reports").is_dir() else []
    level = 0
    if claude_md.exists():
        level = 1
        if sections >= 3 and cm_lines <= 200:
            level = 2
            if scoped >= 1 or active >= 5:
                level = 3
                if n_canaries >= 3 and events:
                    level = 4
                    if last_curate and (today() - last_curate).days <= 30 and audits:
                        level = 5
    report["maturity_level"] = level
    report["initialized"] = bool(cfg.get("initialized"))
    report["hooks_registered"] = hooks_ok
    report["last_curate"] = cfg.get("last_curate")
    protected = cfg.get("research", {}).get("protected_paths", [])
    baseline = root / ".claude" / "kit" / "research-baseline.json"
    if protected:
        report["checks"].append(f"research guard: {len(protected)} protected paths, baseline {'present' if baseline.exists() else 'missing'}")
        if not baseline.exists():
            report["warnings"].append("research paths are protected but no baseline exists; run `python .claude/kit/runlog.py baseline`")
    so = cfg.get("second_opinion", {})
    if so.get("enabled"):
        cmd = str(so.get("command") or "").split()
        import shutil  # noqa: PLC0415

        found = bool(cmd) and shutil.which(cmd[0]) is not None
        report["checks"].append(f"second opinion: on, command {cmd[0] if cmd else '(none)'} {'found' if found else 'NOT found on PATH'}")
        if not found:
            report["warnings"].append("second_opinion is enabled but its command was not found on PATH")
    report["research_protected_paths"] = len(protected)
    report["second_opinion"] = bool(so.get("enabled"))
    return report


# ------------------------------------------------------------------------ scaffold

BODIES = {
    "lesson": "## What happened\n\n\n## Root cause\n\n\n## Prevention\n\n\n## Evidence\n\n",
    "decision": "## Context\n\n\n## Decision\n\n\n## Alternatives rejected\n\n\n## Consequences\n\n",
    "architecture": "## Responsibility\n\n\n## Boundaries\n\n\n## Key paths\n\n\n## Gotchas\n\n",
    "solution": "## Problem\n\n\n## Solution\n\n\n## Why it works\n\n\n## Edge cases\n\n",
    "concept": "## Definition\n\n\n## Where it appears\n\n",
    "procedure": "## When to use\n\n\n## Steps\n\n\n## Verification\n\n",
    "proposal": "## Change\n\n\n## Evidence\n\n\n## Diagnosis\n\n\n## Constitution check\n\n\n## Decision\n\n",
}


def scaffold(root: Path, ntype: str, slug: str, title: str, description: str, rule: str, source: str, status: str) -> Path:
    if ntype not in TYPE_DIRS:
        raise SystemExit(f"unknown type '{ntype}'; use one of {sorted(TYPE_DIRS)}")
    slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")
    folder = root / "knowledge" / TYPE_DIRS[ntype]
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{today()}-{slug}" if ntype == "proposal" else slug
    path = folder / f"{name}.md"
    if path.exists():
        raise SystemExit(f"{path.relative_to(root)} already exists; update it instead")
    review_days = load_config(root).get("review_days", {}).get(ntype, DEFAULT_REVIEW_DAYS[ntype])
    review = today() + dt.timedelta(days=int(review_days))
    fm = [
        "---",
        f"type: {ntype}",
        f"title: {yq(title or slug.replace('-', ' '))}",
        f"description: {yq(description)}",
        "tags: []",
        f"status: {status or ('proposed' if ntype == 'proposal' else 'active')}",
        "confidence: medium",
        f"source: {yq(source)}",
        f"created: {today()}",
        f"updated: {today()}",
        f"review_by: {review}",
    ]
    if ntype == "lesson":
        fm += [f"rule: {yq(rule)}", "trigger: []", "severity: medium", "paths: []"]
    elif ntype in ("architecture", "procedure"):
        fm += ["paths: []"]
    elif ntype == "proposal":
        fm += ["target: \"\"", "control: knowledge", "scope: project", "times_proposed: 1", "evidence: []"]
    fm += ["relations:", "  depends_on: []", "  related: []", "---", ""]
    path.write_text("\n".join(fm) + "\n" + BODIES[ntype], encoding="utf-8")
    return path


def append_log(root: Path, message: str) -> None:
    path = root / "knowledge" / "log.md"
    header = "# Knowledge log\n\nNewest first. One line per change to the graph or to always-on instructions.\n\n"
    existing = path.read_text(encoding="utf-8") if path.exists() else header
    if not existing.startswith("# Knowledge log"):
        existing = header + existing
    head, _, rest = existing.partition("\n\n- ")
    if not rest:
        new = existing.rstrip() + f"\n\n- {today()}: {message}\n"
    else:
        new = head + f"\n\n- {today()}: {message}\n- " + rest
    path.write_text(new, encoding="utf-8")


def mermaid(nodes: dict, limit: int = 150) -> str:
    ids = {nid: f"n{i}" for i, nid in enumerate(sorted(nodes)[:limit])}
    lines = ["flowchart LR"]
    for nid, alias in ids.items():
        label = nodes[nid]["title"].replace('"', "'")
        lines.append(f'  {alias}["{label}"]:::{nodes[nid]["type"] or "untyped"}')
    for src, rel, dst in edges_of(nodes):
        if src in ids and dst in ids:
            lines.append(f"  {ids[src]} -->|{rel}| {ids[dst]}")
    lines += [
        "  classDef lesson fill:#fde2e1,stroke:#c0392b,color:#1f1f1f",
        "  classDef decision fill:#e1ecfd,stroke:#2c5aa0,color:#1f1f1f",
        "  classDef architecture fill:#e6f4ea,stroke:#2e7d32,color:#1f1f1f",
        "  classDef solution fill:#fff4d6,stroke:#b7791f,color:#1f1f1f",
        "  classDef concept fill:#f3e8fd,stroke:#7b3fb5,color:#1f1f1f",
        "  classDef procedure fill:#e0f4f4,stroke:#1f7a7a,color:#1f1f1f",
        "  classDef proposal fill:#eeeeee,stroke:#777777,stroke-dasharray:4 3,color:#1f1f1f",
    ]
    return "\n".join(lines)


# ----------------------------------------------------------------------------- cli


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kg.py", description="Project knowledge graph tool")
    ap.add_argument("--root", help="project root (defaults to the folder holding .claude/kit)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    v = sub.add_parser("validate")
    v.add_argument("--strict", action="store_true", help="treat warnings as failures")
    q = sub.add_parser("query")
    q.add_argument("text", nargs="+")
    q.add_argument("-k", type=int, default=5)
    q.add_argument("--type", action="append", help="limit to a node type (repeatable)")
    q.add_argument("--all", action="store_true", help="include candidate, superseded and archived nodes")
    q.add_argument("--json", action="store_true")
    s = sub.add_parser("show")
    s.add_argument("id")
    n = sub.add_parser("new")
    n.add_argument("type", choices=sorted(TYPE_DIRS))
    n.add_argument("slug")
    n.add_argument("--title", default="")
    n.add_argument("--description", default="")
    n.add_argument("--rule", default="")
    n.add_argument("--source", default="")
    n.add_argument("--status", default="")
    sub.add_parser("stale")
    st = sub.add_parser("stats")
    st.add_argument("--json", action="store_true")
    sg = sub.add_parser("signals")
    sg.add_argument("--days", type=int, default=14)
    sg.add_argument("--json", action="store_true")
    sub.add_parser("codemap")
    sub.add_parser("mermaid")
    lg = sub.add_parser("log")
    lg.add_argument("message", nargs="+")
    dr = sub.add_parser("doctor")
    dr.add_argument("--json", action="store_true")
    mc = sub.add_parser("mark-curated", help="record today as the last /curate run")
    mc.add_argument("--date", default="")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

    root = find_root(args.root)

    if args.cmd == "build":
        build(root)
        return 0

    if args.cmd == "validate":
        nodes, problems = load_nodes(root)
        errors, warnings = validate(root, nodes, problems)
        for e in errors:
            print(f"ERROR   {e}")
        for w in warnings:
            print(f"WARN    {w}")
        print(f"{len(nodes)} nodes, {len(errors)} errors, {len(warnings)} warnings")
        return 1 if errors or (args.strict and warnings) else 0

    if args.cmd == "query":
        nodes, _ = load_nodes(root)
        idx = Index(nodes, None if args.all else SERVED_STATUSES)
        hits = idx.search(" ".join(args.text), k=args.k, types=set(args.type) if args.type else None)
        if args.json:
            print(json.dumps([
                {"score": sc, "matched": m, "id": nd["id"], "type": nd["type"], "title": nd["title"],
                 "file": nd["file"], "description": nd["description"], "rule": nd["rule"],
                 "neighbours": neighbours(nodes, nd["id"])}
                for sc, m, nd in hits
            ], indent=1))
            return 0
        if not hits:
            print("no matching nodes")
            return 0
        for sc, m, nd in hits:
            print(f"{sc:6.2f}  [{nd['type']}] {nd['title']}  ({nd['file']})")
            line = nd["rule"] or nd["description"]
            if line:
                print(f"        {line}")
            nb = neighbours(nodes, nd["id"])
            if nb:
                print("        edges: " + ", ".join(f"{r} {t}" for r, t in nb[:6]))
        return 0

    if args.cmd == "show":
        nodes, _ = load_nodes(root)
        nid = normalize_id(args.id)
        if nid not in nodes:
            print(f"no node '{nid}'")
            return 1
        nd = nodes[nid]
        print(f"{nd['file']}  [{nd['type']}, {nd['status']}]")
        print(nd["title"])
        if nd["description"]:
            print(nd["description"])
        for r, t in neighbours(nodes, nid):
            print(f"  {r} -> {t}")
        print()
        print(nd["body"].strip())
        return 0

    if args.cmd == "new":
        path = scaffold(root, args.type, args.slug, args.title, args.description, args.rule, args.source, args.status)
        print(path.relative_to(root).as_posix())
        return 0

    if args.cmd == "stale":
        rows = stale_report(root, load_nodes(root)[0])
        for nid, title, why in rows:
            print(f"{nid}: {why}")
        print(f"{len(rows)} stale or drifted nodes")
        return 0

    if args.cmd == "stats":
        nodes, _ = load_nodes(root)
        cfg = load_config(root)
        data = {
            "nodes": len(nodes),
            "by_type": dict(Counter(n["type"] for n in nodes.values() if n["status"] == "active")),
            "by_status": dict(Counter(n["status"] for n in nodes.values())),
            "stale": len(stale_report(root, nodes)),
            "pending_proposals": sum(1 for n in nodes.values() if n["type"] == "proposal" and n["status"] == "proposed"),
            "events_7d": len(read_events(root, 7)),
            "last_curate": cfg.get("last_curate"),
            "initialized": bool(cfg.get("initialized")),
        }
        print(json.dumps(data, indent=1) if args.json else "\n".join(f"{k}: {v}" for k, v in data.items()))
        return 0

    if args.cmd == "signals":
        nodes, _ = load_nodes(root)
        data = signals_summary(root, nodes, args.days)
        if args.json:
            print(json.dumps(data, indent=1))
            return 0
        print(f"Last {data['days']} days: {data['sessions']} sessions, events {data['events']}")
        print(f"Categories: {data['categories']}")
        print("Top failure patterns:")
        for p in data["top_failure_patterns"]:
            print(f"  {p['count']:3d}x in {p['sessions']} sessions  {p['key']}")
            if p["example"]:
                print(f"        e.g. {p['example'][:140]}")
        print("Recent corrections:")
        for c in data["recent_corrections"]:
            print(f"  {c['ts']}  {c['text'][:140]}")
        print("Lessons (injected in window / recurrences since created):")
        for row in data["lessons"]:
            flag = "  no trigger" if not row["has_trigger"] else ""
            print(f"  {row['id']}: {row['injected']} / {row['recurrences_since_created']}{flag}")
        return 0

    if args.cmd == "codemap":
        codemap(root)
        print(".claude/kit/code-map.yaml written")
        return 0

    if args.cmd == "mermaid":
        print(mermaid(load_nodes(root)[0]))
        return 0

    if args.cmd == "log":
        append_log(root, " ".join(args.message))
        print("knowledge/log.md updated")
        return 0

    if args.cmd == "doctor":
        rep = doctor(root)
        if args.json:
            print(json.dumps(rep, indent=1))
        else:
            print(f"root: {rep['root']}  python {rep['python']}")
            for c in rep["checks"]:
                print(f"  ok    {c}")
            for w in rep["warnings"]:
                print(f"  warn  {w}")
            print(f"  always-on instruction budget: about {rep['always_on_tokens']} tokens")
            print(f"  context maturity level (0-5): {rep['maturity_level']}")
        return 0

    if args.cmd == "mark-curated":
        cfg = load_config(root)
        cfg["last_curate"] = args.date or str(today())
        save_config(root, cfg)
        print(f"last_curate = {cfg['last_curate']}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
