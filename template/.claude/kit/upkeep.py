#!/usr/bin/env python3
"""Keep the kit, and the outside tools a project relies on, up to date.

Kit updates
    The installed kit is compared with the latest release of its source repository
    (ENIGMA-KUN/claude-project-kit, or a fork set in config). `update` downloads that
    release and runs its installer, which upgrades kit-managed files with a backup and
    never overwrites files you own.

Tool watchlist
    .claude/kit/watchlist.json lists outside tools the project depends on (crawlers,
    parsers, model runtimes, SDKs). `check` looks at each one upstream: new release,
    archived or deprecated, renamed, no commits for a long time, license changed.
    A flagged tool is listed with its alternatives, and each alternative is checked
    too, so a dead project is never offered as the replacement.

    upkeep.py check [--json] [--kit-only]      kit version and watchlist report (network)
    upkeep.py report [--json]                  the last report again, no network
    upkeep.py update [--ref TAG] [--from DIR] [--yes] [--dry-run]
    upkeep.py watch list
    upkeep.py watch add NAME [--github OWNER/REPO] [--pypi PKG] [--npm PKG] [--hf MODEL]
                        [--role TEXT] [--alt OWNER/REPO ...] [--pinned VERSION] [--license SPDX]
    upkeep.py watch remove NAME | pin NAME VERSION | ack NAME
    upkeep.py watch preset research            add a maintained research-agent stack
    upkeep.py probe OWNER/REPO ... [--preset NAME] [--strict] [--json]
    upkeep.py auto                             background check started by the session-start hook

Settings live under "upkeep" in .claude/kit/config.json:
    mode           off | notify (default) | auto
    interval_days  how often the background check runs (default 7)
    source         GitHub repository the kit updates from
    stale_days     no commits for this many days counts as inactive (default 270)

notify checks in the background at most once per interval and reports at the next
session start. auto also installs new minor and patch kit releases; a new major
version always waits for you. off stops the background check; the commands above
still work when you run them. The background check is also skipped when
CLAUDE_KIT_UPKEEP=off or CI is set.

Network use: GET requests to api.github.com and codeload.github.com, plus pypi.org,
registry.npmjs.org or huggingface.co for watched packages. Nothing from the project
is sent. GITHUB_TOKEN or GH_TOKEN, when set, goes to api.github.com only, to raise
the rate limit.

Exit codes: 0 ok, 1 something needs attention (check, probe --strict), 2 waiting for
confirmation, 3 network, download or install error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


def find_root() -> Path:
    here = Path(__file__).resolve()
    if here.parent.name == "kit" and here.parent.parent.name == ".claude":
        return here.parents[2]
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env).resolve() if env else Path.cwd().resolve()


ROOT = find_root()
KIT = ROOT / ".claude" / "kit"
STATE = KIT / "state" / "upkeep" / "state.json"
WATCHLIST = KIT / "watchlist.json"
sys.dont_write_bytecode = True
sys.path.insert(0, str(KIT))

API = "https://api.github.com"
DEFAULTS = {"mode": "notify", "interval_days": 7, "source": "ENIGMA-KUN/claude-project-kit", "stale_days": 270}
SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NAME = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9_.@/-]*$")
SEMVER_TAG = re.compile(r"^v?\d+\.\d+\.\d+$")
MAX_DOWNLOAD = 100 * 1024 * 1024
MAX_UNPACKED = 200 * 1024 * 1024

ACT = {"archived", "deprecated", "license", "moved"}
LEVEL_ORDER = {"ACT": 0, "REVIEW": 1, "UPDATE": 2, "ERROR": 3, "ok": 4}

# Starting points, not endorsements: `check` re-verifies every entry and alternative.
PRESETS = {
    "research": [
        {"name": "searxng", "role": "self-hosted metasearch with a JSON API", "github": "searxng/searxng", "alternatives": []},
        {"name": "crawl4ai", "role": "web page to clean Markdown", "github": "unclecode/crawl4ai", "pypi": "crawl4ai",
         "alternatives": ["firecrawl/firecrawl", "apify/crawlee"]},
        {"name": "firecrawl", "role": "crawl and scrape service, self-hostable", "github": "firecrawl/firecrawl",
         "alternatives": ["unclecode/crawl4ai", "apify/crawlee"]},
        {"name": "browser-use", "role": "browser automation for pages that need clicks", "github": "browser-use/browser-use",
         "pypi": "browser-use", "alternatives": ["microsoft/playwright-python"]},
        {"name": "docling", "role": "PDF and document parsing", "github": "docling-project/docling", "pypi": "docling",
         "alternatives": ["datalab-to/marker", "grobidOrg/grobid"]},
        {"name": "marker", "role": "PDF to Markdown", "github": "datalab-to/marker", "pypi": "marker-pdf",
         "alternatives": ["docling-project/docling"]},
        {"name": "grobid", "role": "scholarly PDF metadata and references", "github": "grobidOrg/grobid",
         "alternatives": ["docling-project/docling"]},
        {"name": "gpt-researcher", "role": "deep-research agent loop", "github": "assafelovic/gpt-researcher",
         "pypi": "gpt-researcher", "alternatives": ["huggingface/smolagents", "dzhng/deep-research"]},
        {"name": "smolagents", "role": "agent framework for custom research loops", "github": "huggingface/smolagents",
         "pypi": "smolagents", "alternatives": ["assafelovic/gpt-researcher"]},
        {"name": "ollama", "role": "local model runtime", "github": "ollama/ollama",
         "alternatives": ["ggml-org/llama.cpp", "vllm-project/vllm"]},
        {"name": "vllm", "role": "model serving on GPU servers", "github": "vllm-project/vllm", "pypi": "vllm",
         "alternatives": ["sgl-project/sglang", "ggml-org/llama.cpp"]},
        {"name": "deep-research-bench", "role": "benchmark for comparing research agents",
         "github": "Ayanami0730/deep_research_bench", "alternatives": []},
    ],
}


# ------------------------------------------------------------------ basics


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def parse_iso(value) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def days_since(date_text: str) -> int | None:
    try:
        return (dt.date.today() - dt.date.fromisoformat(str(date_text)[:10])).days
    except ValueError:
        return None


def vtuple(version) -> tuple:
    m = re.match(r"^v?(\d+(?:\.\d+)*)", str(version or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def newer(a, b) -> bool:
    """True when version a is newer than b. Versions that do not parse count as newer when they differ."""
    ta, tb = vtuple(a), vtuple(b)
    if not ta or not tb:
        return bool(a) and bool(b) and str(a).strip().lstrip("v") != str(b).strip().lstrip("v")
    n = max(len(ta), len(tb))
    return ta + (0,) * (n - len(ta)) > tb + (0,) * (n - len(tb))


def load_config() -> dict:
    try:
        return json.loads((KIT / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    (KIT / "config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def settings(cfg: dict | None = None) -> dict:
    cfg = load_config() if cfg is None else cfg
    s = {**DEFAULTS, **(cfg.get("upkeep") or {})}
    for key in ("interval_days", "stale_days"):
        try:
            s[key] = float(s[key])
        except (TypeError, ValueError):
            s[key] = float(DEFAULTS[key])
    s["mode"] = str(s.get("mode") or "notify").lower()
    return s


def background_disabled(s: dict) -> str:
    if s["mode"] == "off":
        return "upkeep.mode is off"
    if os.environ.get("CLAUDE_KIT_UPKEEP", "").lower() in ("off", "0", "false", "no"):
        return "CLAUDE_KIT_UPKEEP=off"
    if os.environ.get("CI"):
        return "running in CI"
    return ""


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
        os.replace(tmp, STATE)
    except OSError:
        pass


def log_signal(event: dict) -> None:
    try:
        path = KIT / "signals" / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": now_iso(), "event": "upkeep", **event}) + "\n")
    except OSError:
        pass


def installed_version() -> str:
    try:
        text = (KIT / "kg.py").read_text(encoding="utf-8")
        m = re.search(r'^KIT_VERSION\s*=\s*"([^"]+)"', text, re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    return str(load_config().get("kit_version") or "0.0.0")


# ------------------------------------------------------------------ network


class FetchError(Exception):
    def __init__(self, url: str, status: int, message: str):
        super().__init__(message)
        self.url = url
        self.status = status


def _fixtures() -> dict | None:
    """Offline answers for tests: CLAUDE_KIT_UPKEEP_FIXTURES names a JSON file mapping URL to response."""
    path = os.environ.get("CLAUDE_KIT_UPKEEP_FIXTURES")
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fetch(url: str, limit: int = 5_000_000, timeout: int = 20) -> bytes:
    fixtures = _fixtures()
    if fixtures is not None:
        if url not in fixtures:
            raise FetchError(url, 0, f"network error: no fixture for {url}")
        fx = fixtures[url]
        if isinstance(fx, dict) and "__status" in fx:
            raise FetchError(url, int(fx["__status"]), fx.get("message", f"HTTP {fx['__status']}"))
        if isinstance(fx, dict) and "__file" in fx:
            return Path(fx["__file"]).read_bytes()
        return json.dumps(fx).encode("utf-8")
    headers = {"User-Agent": "claude-project-kit-upkeep", "Accept": "application/json"}
    if url.startswith(API + "/"):
        headers["Accept"] = "application/vnd.github+json"
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:
            data = resp.read(limit + 1)
    except urllib.error.HTTPError as exc:
        message = f"HTTP {exc.code} from {urllib.parse.urlsplit(url).netloc}"
        if exc.code in (403, 429) and url.startswith(API):
            message = "GitHub rate limit reached; set GITHUB_TOKEN or try again later"
        raise FetchError(url, exc.code, message) from None
    except (urllib.error.URLError, OSError) as exc:
        raise FetchError(url, 0, f"network error: {getattr(exc, 'reason', exc)}") from None
    if len(data) > limit:
        raise FetchError(url, 0, "response too large")
    return data


def fetch_json(url: str):
    try:
        return json.loads(fetch(url).decode("utf-8"))
    except ValueError:
        raise FetchError(url, 0, "response is not JSON") from None


def gh_repo(slug: str) -> dict:
    d = fetch_json(f"{API}/repos/{slug}")
    return {
        "repo": d.get("full_name") or slug,
        "archived": bool(d.get("archived") or d.get("disabled")),
        "pushed": (d.get("pushed_at") or "")[:10],
        "license": ((d.get("license") or {}).get("spdx_id") or ""),
        "stars": int(d.get("stargazers_count") or 0),
        "url": d.get("html_url") or f"https://github.com/{slug}",
    }


def health(info: dict, stale_days: float) -> list:
    flags = []
    if info.get("archived"):
        flags.append(["archived", "repository is archived (read-only)"])
    age = days_since(info.get("pushed", ""))
    if age is not None and age > stale_days:
        flags.append(["stale", f"no commits for {age} days"])
    return flags


# ------------------------------------------------------------------ kit version


def kit_status(s: dict) -> dict:
    src = str(s["source"])
    installed = installed_version()
    out = {"source": src, "installed": installed, "latest": "", "tag": "", "newer": False, "major": False,
           "notes": "", "url": "", "published": "", "error": ""}
    if not SLUG.match(src):
        out["error"] = f"upkeep.source {src!r} is not OWNER/REPO"
        return out
    try:
        rel = fetch_json(f"{API}/repos/{src}/releases/latest")
        tag = str(rel.get("tag_name") or "")
        out.update(notes=(rel.get("body") or "")[:3000], url=rel.get("html_url") or "", published=(rel.get("published_at") or "")[:10])
    except FetchError as exc:
        if exc.status != 404:
            out["error"] = str(exc)
            return out
        try:
            tags = fetch_json(f"{API}/repos/{src}/tags?per_page=100")
        except FetchError as exc2:
            out["error"] = str(exc2)
            return out
        names = [str(t.get("name") or "") for t in tags if SEMVER_TAG.match(str(t.get("name") or ""))]
        if not names:
            out["error"] = "no releases published yet"
            return out
        tag = max(names, key=vtuple)
        out["url"] = f"https://github.com/{src}/releases/tag/{tag}"
    out["tag"] = tag
    out["latest"] = tag.lstrip("v")
    out["newer"] = newer(tag, installed)
    out["major"] = out["newer"] and vtuple(tag)[:1] != vtuple(installed)[:1]
    return out


def refresh_kit_view(kit: dict) -> dict:
    """The cached report may predate an update; compare its latest release with what is installed now."""
    kit = dict(kit or {})
    if kit.get("latest"):
        inst = installed_version()
        kit["installed"] = inst
        kit["newer"] = newer(kit.get("tag") or kit["latest"], inst)
        kit["major"] = kit["newer"] and vtuple(kit["latest"])[:1] != vtuple(inst)[:1]
    return kit


# ------------------------------------------------------------------ watchlist


def load_watchlist() -> dict:
    try:
        data = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"tools": []}
    except (OSError, ValueError) as exc:
        raise SystemExit(f"{WATCHLIST.relative_to(ROOT).as_posix()} is not valid JSON: {exc}") from None
    data.setdefault("tools", [])
    return data


def save_watchlist(wl: dict) -> None:
    WATCHLIST.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST.write_text(json.dumps(wl, indent=2) + "\n", encoding="utf-8")


def check_tool(entry: dict, s: dict, prev: dict) -> tuple:
    res = {"name": entry.get("name", "?"), "role": entry.get("role", ""), "flags": [], "latest": "", "info": {}, "alternatives": []}
    seen = dict(prev)
    gh = str(entry.get("github") or "")
    try:
        if gh:
            info = gh_repo(gh)
            res["info"] = info
            res["flags"] += health(info, s["stale_days"])
            if info["repo"].lower() != gh.lower():
                res["flags"].append(["moved", f"repository moved to {info['repo']}; run `upkeep.py watch ack {res['name']}`"])
            expected = entry.get("license") or prev.get("license")
            if info["license"] and expected and info["license"] != expected:
                res["flags"].append(["license", f"license changed: {expected} -> {info['license']}"])
            elif info["license"] and not expected:
                seen["license"] = info["license"]
        latest = ""
        if entry.get("pypi"):
            latest = str(fetch_json(f"https://pypi.org/pypi/{urllib.parse.quote(entry['pypi'])}/json")["info"]["version"])
        elif entry.get("npm"):
            d = fetch_json(f"https://registry.npmjs.org/{urllib.parse.quote(entry['npm'], safe='@')}/latest")
            latest = str(d.get("version") or "")
            if d.get("deprecated"):
                res["flags"].append(["deprecated", f"npm says: {str(d['deprecated'])[:160]}"])
        elif gh:
            try:
                latest = str(fetch_json(f"{API}/repos/{gh}/releases/latest").get("tag_name") or "")
            except FetchError as exc:
                if exc.status != 404:
                    raise
        if entry.get("hf"):
            d = fetch_json(f"https://huggingface.co/api/models/{entry['hf']}")
            modified = str(d.get("lastModified") or "")[:10]
            res["info"]["hf_modified"] = modified
            if d.get("disabled"):
                res["flags"].append(["archived", "model is disabled on Hugging Face"])
            if modified and prev.get("hf_modified") and modified != prev["hf_modified"]:
                res["flags"].append(["release", f"model files updated on {modified}"])
            if modified:
                seen["hf_modified"] = modified
        res["latest"] = latest
        pinned = str(entry.get("pinned") or "")
        if latest and pinned and newer(latest, pinned):
            res["flags"].append(["update", f"you pin {pinned}, latest is {latest}"])
        elif latest and not pinned and prev.get("latest") and newer(latest, prev["latest"]):
            res["flags"].append(["release", f"new release {latest} (was {prev['latest']})"])
        if latest:
            seen["latest"] = latest
    except (FetchError, KeyError, TypeError) as exc:
        res["flags"].append(["error", str(exc) if isinstance(exc, FetchError) else f"unexpected response: {exc}"])
    return res, seen


def level(res: dict) -> str:
    kinds = {k for k, _ in res.get("flags", [])}
    if kinds & ACT:
        return "ACT"
    if "stale" in kinds:
        return "REVIEW"
    if kinds & {"update", "release"}:
        return "UPDATE"
    if "error" in kinds:
        return "ERROR"
    return "ok"


def probe_one(slug: str, s: dict, cache: dict) -> dict:
    if not SLUG.match(slug):
        return {"name": slug, "ok": None, "note": "not a GitHub OWNER/REPO; check it by hand"}
    try:
        info = cache.get(slug) or gh_repo(slug)
        cache[slug] = info
    except FetchError as exc:
        return {"name": slug, "ok": None, "note": str(exc)}
    flags = health(info, s["stale_days"])
    if info["repo"].lower() != slug.lower():
        flags.append(["moved", f"moved to {info['repo']}"])
    return {"name": info["repo"], "ok": not flags, "stars": info["stars"], "pushed": info["pushed"],
            "license": info["license"], "note": "; ".join(t for _, t in flags)}


def run_check(s: dict, include_tools: bool = True) -> dict:
    st = load_state()
    seen = st.get("seen", {})
    report = {"checked_at": now_iso(), "kit": kit_status(s), "tools": []}
    if include_tools:
        cache: dict = {}
        for entry in load_watchlist()["tools"]:
            res, seen_entry = check_tool(entry, s, seen.get(entry.get("name", ""), {}))
            seen[res["name"]] = seen_entry
            if level(res) in ("ACT", "REVIEW"):
                res["alternatives"] = [probe_one(a, s, cache) for a in entry.get("alternatives", [])]
            report["tools"].append(res)
    st = load_state()  # re-read: a session may have written to it meanwhile
    st.update(seen=seen, last=report, checked_at=report["checked_at"])
    save_state(st)
    log_signal({"kit_newer": report["kit"]["newer"], "flagged": sum(1 for r in report["tools"] if level(r) != "ok")})
    return report


def render(report: dict) -> str:
    lines = []
    k = refresh_kit_view(report.get("kit", {}))
    if k.get("error"):
        lines.append(f"Kit {k.get('installed', '?')}: could not check {k.get('source', '?')} ({k['error']}).")
    elif k.get("newer"):
        lines.append(f"Kit {k['installed']} installed, {k['latest']} available"
                     + (" (major version: read the release notes first)" if k.get("major") else "")
                     + (f", released {k['published']}" if k.get("published") else "") + f": {k.get('url', '')}")
        lines.append("  Install with: python .claude/kit/upkeep.py update")
    elif k:
        lines.append(f"Kit {k.get('installed', '?')} is up to date ({k.get('source', '?')}).")
    tools = report.get("tools", [])
    if tools:
        lines.append("")
        lines.append(f"Watchlist, {len(tools)} tools (checked {str(report.get('checked_at', ''))[:16].replace('T', ' ')}):")
        width = max(len(r["name"]) for r in tools)
        for r in sorted(tools, key=lambda r: (LEVEL_ORDER[level(r)], r["name"])):
            lv = level(r)
            detail = "; ".join(t for _, t in r["flags"]) or (f"latest {r['latest']}" if r.get("latest") else "healthy")
            lines.append(f"  {lv:<6}  {r['name']:<{width}}  {detail}")
            for a in r.get("alternatives", []):
                if a.get("ok") is None:
                    state = a.get("note", "")
                elif a["ok"]:
                    state = f"healthy, {a['stars']} stars, last commit {a['pushed']}, {a['license'] or 'no license'}"
                else:
                    state = f"not a good replacement: {a['note']}"
                lines.append(f"  {'':<6}  {'':<{width}}  alternative {a['name']}: {state}")
            if lv in ("ACT", "REVIEW") and not r.get("alternatives"):
                lines.append(f"  {'':<6}  {'':<{width}}  no alternatives listed; /upkeep can search for some")
    elif "tools" in report:
        lines.append("")
        lines.append("Watchlist is empty. Add tools with `upkeep.py watch add` or `upkeep.py watch preset research`.")
    return "\n".join(lines)


def needs_attention(report: dict) -> bool:
    k = refresh_kit_view(report.get("kit", {}))
    return bool(k.get("newer")) or any(level(r) in ("ACT", "REVIEW") for r in report.get("tools", []))


# ------------------------------------------------------------------ session start


def notice(report: dict, st: dict) -> str:
    parts = []
    k = refresh_kit_view(report.get("kit", {}))
    applied = st.get("applied") or {}
    if applied and not applied.get("reported"):
        if applied.get("ok"):
            parts.append(f"kit updated {applied.get('from')} -> {applied.get('to')} in the background (restart to load new hooks)")
        else:
            parts.append(f"background kit update to {applied.get('to')} failed: {applied.get('error', '')[:120]}")
    if k.get("newer"):
        parts.append(f"kit {k['latest']} is available (installed {k['installed']}" + (", major version" if k.get("major") else "") + ")")
    groups: dict = {}
    for r in report.get("tools", []):
        groups.setdefault(level(r), []).append(r["name"])

    def names(xs: list) -> str:
        return ", ".join(xs[:4]) + (f" and {len(xs) - 4} more" if len(xs) > 4 else "")

    if groups.get("ACT"):
        parts.append(f"watched tools needing attention: {names(groups['ACT'])}")
    if groups.get("REVIEW"):
        parts.append(f"inactive upstream: {names(groups['REVIEW'])}")
    if groups.get("UPDATE"):
        parts.append(f"new releases: {names(groups['UPDATE'])}")
    return "; ".join(parts)


def maybe_spawn(s: dict, st: dict) -> bool:
    """Start the background check when it is due. Never blocks the session."""
    if background_disabled(s):
        return False
    last = parse_iso(st.get("attempted_at"))
    if last and (dt.datetime.now() - last).total_seconds() < s["interval_days"] * 86400:
        return False
    st["attempted_at"] = now_iso()
    save_state(st)
    kwargs: dict = {"cwd": str(ROOT), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL, "close_fds": True, "env": {**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)}}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "auto"], **kwargs)
        return True
    except OSError:
        return False


def session_start() -> tuple:
    """Called by the session-start hook. Returns (line for Claude, message for the user); both empty when nothing is new."""
    s = settings()
    st = load_state()
    ctx = msg = ""
    report = st.get("last")
    if report:
        text = notice(report, st)
        if text:
            key = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
            if st.get("notified") != key:
                st["notified"] = key
                msg = f"project-kit upkeep: {text}. Run /upkeep for details."
                ctx = (f"Upkeep: {text}. Mention it to the user once. Details: `python .claude/kit/upkeep.py report`; "
                       "the /upkeep skill installs kit updates (with the user's yes) and compares alternatives.")
        if st.get("applied") and not st["applied"].get("reported"):
            st["applied"]["reported"] = True
        save_state(st)
    maybe_spawn(s, st)
    return ctx, msg


# ------------------------------------------------------------------ kit update


def extract_kit(data: bytes) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="kit-update-"))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            wanted = []
            for info in zf.infolist():
                parts = info.filename.replace("\\", "/").split("/")[1:]  # drop the archive's top folder
                rel = "/".join(parts)
                if info.is_dir() or not parts or not parts[-1]:
                    continue
                if not (rel in ("install.py", "CHANGELOG.md") or rel.startswith("template/")):
                    continue
                if any(p in ("", ".", "..") for p in parts) or ":" in rel:
                    raise ValueError(f"unsafe path in the archive: {info.filename}")
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    continue  # symbolic link
                wanted.append((info, parts))
            if sum(i.file_size for i, _ in wanted) > MAX_UNPACKED:
                raise ValueError("archive unpacks to more than 200 MB")
            for info, parts in wanted:
                dest = tmp.joinpath(*parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(info))
    except (zipfile.BadZipFile, ValueError, OSError) as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise FetchError("", 0, f"bad kit archive: {exc}") from None
    if not (tmp / "install.py").is_file() or not (tmp / "template" / ".claude" / "kit" / "kg.py").is_file():
        shutil.rmtree(tmp, ignore_errors=True)
        raise FetchError("", 0, "the download does not look like the project kit (no install.py or template)")
    return tmp


def kit_version_in(kit_dir: Path) -> str:
    try:
        m = re.search(r'^KIT_VERSION\s*=\s*"([^"]+)"', (kit_dir / "template/.claude/kit/kg.py").read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else "?"
    except OSError:
        return "?"


def download_kit(src: str, ref: str) -> Path:
    path = f"refs/tags/{ref}" if SEMVER_TAG.match(ref) else urllib.parse.quote(ref, safe="")
    return extract_kit(fetch(f"https://codeload.github.com/{src}/zip/{path}", limit=MAX_DOWNLOAD, timeout=120))


def changelog_since(kit_dir: Path, installed: str) -> str:
    try:
        text = (kit_dir / "CHANGELOG.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    out, keep = [], False
    for line in text.splitlines():
        m = re.match(r"^## \[?v?(\d+\.\d+\.\d+)", line)
        if m:
            keep = newer(m.group(1), installed)
        if keep:
            out.append(line)
    return "\n".join(out).strip()


def run_installer(kit_dir: Path, downloaded: bool) -> tuple:
    cfg = load_config()
    old_home = str(cfg.get("kit_home") or "")
    py_cmd = str(cfg.get("python") or ("python" if os.name == "nt" else "python3"))
    try:
        res = subprocess.run([sys.executable, "-I", str(kit_dir / "install.py"), str(ROOT), "--python-cmd", py_cmd],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not run the installer: {exc}"
    if downloaded:
        # The download sits in a temp folder that is about to go; keep kit_home on a real checkout, if there was one.
        cfg2 = load_config()
        cfg2["kit_home"] = old_home if old_home and (Path(old_home) / "install.py").is_file() else ""
        save_config(cfg2)
    return res.returncode == 0, ((res.stdout or "") + (res.stderr or "")).strip()


def do_update(s: dict, ref: str = "", from_dir: str = "", yes: bool = False, dry_run: bool = False, quiet: bool = False) -> int:
    say = (lambda *a: None) if quiet else print
    installed = installed_version()
    if from_dir:
        kit_dir = Path(from_dir).resolve()
        if not (kit_dir / "install.py").is_file() or not (kit_dir / "template").is_dir():
            say(f"{kit_dir} is not a project kit checkout (no install.py and template/)")
            return 3
        downloaded = False
        origin = str(kit_dir)
    else:
        src = str(s["source"])
        if not ref:
            k = kit_status(s)
            if k["error"]:
                say(f"could not check for updates: {k['error']}")
                return 3
            if not k["newer"]:
                say(f"kit {installed} is up to date ({src})")
                return 0
            ref = k["tag"]
        try:
            kit_dir = download_kit(src, ref)
        except FetchError as exc:
            say(f"download failed: {exc}")
            return 3
        downloaded = True
        origin = f"{src}@{ref}"
    try:
        target = kit_version_in(kit_dir)
        say(f"Kit {installed} -> {target} from {origin}")
        if vtuple(target)[:1] and vtuple(target)[:1] != vtuple(installed)[:1]:
            say("This is a new major version. Read the changes below before installing.")
        notes = changelog_since(kit_dir, installed)
        if notes:
            say("\n" + notes[:4000] + ("\n[...]" if len(notes) > 4000 else "") + "\n")
        if dry_run:
            say("dry run: nothing installed")
            return 0
        if not yes:
            if sys.stdin and sys.stdin.isatty():
                if input("Install it? Kit files are backed up first. [y/N] ").strip().lower() not in ("y", "yes"):
                    say("not installed")
                    return 2
            else:
                say("Not installed. Re-run with --yes to install.")
                return 2
        ok, output = run_installer(kit_dir, downloaded)
        say(output)
        log_signal({"update": "applied" if ok else "failed", "from": installed, "to": target})
        if ok:
            say("\nRestart Claude Code in this folder so the new hooks and skills load. "
                "If files were saved to .claude/kit/incoming/, run /kit-init --refresh to merge them.")
        return 0 if ok else 3
    finally:
        if downloaded:
            shutil.rmtree(kit_dir, ignore_errors=True)


# ------------------------------------------------------------------ commands


def cmd_auto() -> int:
    s = settings()
    if background_disabled(s):
        return 0
    lock = STATE.parent / "auto.lock"
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        if lock.exists() and time.time() - lock.stat().st_mtime > 3600:
            lock.unlink()
        os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except OSError:
        return 0
    try:
        report = run_check(s)
        k = report["kit"]
        if s["mode"] == "auto" and k["newer"] and not k["major"] and not k["error"]:
            code = do_update(s, ref=k["tag"], yes=True, quiet=True)
            st = load_state()
            st["applied"] = {"from": k["installed"], "to": k["latest"], "ok": code == 0, "at": now_iso(),
                             "error": "" if code == 0 else "installer or download failed; run upkeep.py update", "reported": False}
            st.pop("notified", None)
            save_state(st)
    except Exception as exc:  # noqa: BLE001  the background job must never surface a traceback
        st = load_state()
        st["last_error"] = f"{now_iso()} {type(exc).__name__}: {exc}"
        save_state(st)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
    return 0


def cmd_watch(args) -> int:
    wl = load_watchlist()
    tools = wl["tools"]
    by_name = {t.get("name"): t for t in tools}
    if args.action == "list":
        if not tools:
            print("watchlist is empty")
        for t in tools:
            src = ", ".join(f"{k} {t[k]}" for k in ("github", "pypi", "npm", "hf") if t.get(k))
            print(f"{t['name']}: {t.get('role') or '(no role)'} [{src}]" + (f" pinned {t['pinned']}" if t.get("pinned") else ""))
            if t.get("alternatives"):
                print(f"    alternatives: {', '.join(t['alternatives'])}")
        return 0
    if args.action == "preset":
        preset = PRESETS.get(args.name)
        if not preset:
            print(f"unknown preset {args.name!r}; available: {', '.join(sorted(PRESETS))}")
            return 1
        added = []
        for entry in preset:
            if entry["name"] not in by_name:
                tools.append(dict(entry, added=str(dt.date.today())))
                added.append(entry["name"])
        save_watchlist(wl)
        print(f"added {len(added)} tools from preset {args.name}" + (f": {', '.join(added)}" if added else " (all were already watched)"))
        print("Remove what this project does not use with `upkeep.py watch remove NAME`, then run `upkeep.py check`.")
        return 0
    name = args.name
    if args.action == "add":
        if not NAME.match(name):
            print(f"invalid name {name!r}")
            return 1
        if args.github and not SLUG.match(args.github):
            print(f"--github must be OWNER/REPO, got {args.github!r}")
            return 1
        entry = by_name.get(name)
        if entry is None:
            if not (args.github or args.pypi or args.npm or args.hf):
                print("give at least one of --github, --pypi, --npm, --hf")
                return 1
            entry = {"name": name, "added": str(dt.date.today())}
            tools.append(entry)
        for key in ("github", "pypi", "npm", "hf", "role", "pinned", "license"):
            value = getattr(args, key)
            if value is not None:
                entry[key] = value
        if args.alt is not None:
            entry["alternatives"] = [a.strip() for chunk in args.alt for a in chunk.split(",") if a.strip()]
        entry.setdefault("alternatives", [])
        save_watchlist(wl)
        print(f"watching {name}")
        return 0
    entry = by_name.get(name)
    if entry is None:
        print(f"{name} is not on the watchlist")
        return 1
    if args.action == "remove":
        wl["tools"] = [t for t in tools if t.get("name") != name]
        save_watchlist(wl)
        print(f"stopped watching {name}")
    elif args.action == "pin":
        if args.version.lower() in ("", "none", "-"):
            entry.pop("pinned", None)
        else:
            entry["pinned"] = args.version
        save_watchlist(wl)
        print(f"{name}: pinned {entry.get('pinned', 'nothing')}")
    elif args.action == "ack":
        # Accept the current upstream state: a new license becomes the expected one, a moved repo its new name.
        last = next((r for r in (load_state().get("last") or {}).get("tools", []) if r["name"] == name), None)
        info = (last or {}).get("info") or {}
        if not info and entry.get("github"):
            try:
                info = gh_repo(entry["github"])
            except FetchError as exc:
                print(f"could not reach GitHub: {exc}")
                return 3
        if info.get("repo") and entry.get("github") and info["repo"].lower() != entry["github"].lower():
            entry["github"] = info["repo"]
        if info.get("license"):
            if entry.get("license"):
                entry["license"] = info["license"]
            st = load_state()
            st.setdefault("seen", {}).setdefault(name, {})["license"] = info["license"]
            save_state(st)
        save_watchlist(wl)
        print(f"{name}: accepted {info.get('repo', entry.get('github', ''))} with license {info.get('license') or 'unknown'}")
    return 0


def cmd_probe(args) -> int:
    s = settings()
    slugs = list(args.repos)
    if args.preset:
        preset = PRESETS.get(args.preset)
        if not preset:
            print(f"unknown preset {args.preset!r}; available: {', '.join(sorted(PRESETS))}")
            return 1
        for entry in preset:
            slugs += [entry["github"]] if entry.get("github") else []
            slugs += entry.get("alternatives", [])
    slugs = list(dict.fromkeys(slugs))
    if not slugs:
        print("give OWNER/REPO names or --preset")
        return 1
    cache: dict = {}
    rows = [probe_one(slug, s, cache) for slug in slugs]
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        width = max(len(r["name"]) for r in rows)
        for r in rows:
            if r.get("ok") is None:
                print(f"?     {r['name']:<{width}}  {r['note']}")
            else:
                print(f"{'ok' if r['ok'] else 'WARN':<5} {r['name']:<{width}}  {r['stars']:>7} stars  last commit {r['pushed'] or '?'}  "
                      f"{r['license'] or 'no license'}" + (f"  {r['note']}" if r["note"] else ""))
    bad = [r for r in rows if r.get("ok") is False]
    unknown = [r for r in rows if r.get("ok") is None]
    if args.strict and (bad or unknown):
        print(f"\n{len(bad)} unhealthy, {len(unknown)} could not be checked")
        return 1
    return 0


def main(argv: list | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(prog="upkeep.py", description="Kit updates and the health of watched tools")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check the kit version and the watchlist (network)")
    c.add_argument("--json", action="store_true")
    c.add_argument("--kit-only", action="store_true")
    r = sub.add_parser("report", help="print the last report, no network")
    r.add_argument("--json", action="store_true")
    u = sub.add_parser("update", help="install the latest kit release")
    u.add_argument("--ref", default="", help="tag, branch or commit to install instead of the latest release")
    u.add_argument("--from", dest="from_dir", default="", help="install from a local kit checkout instead of downloading")
    u.add_argument("--yes", action="store_true", help="install without asking")
    u.add_argument("--dry-run", action="store_true", help="download and show the changes, install nothing")
    w = sub.add_parser("watch", help="manage the tool watchlist")
    wsub = w.add_subparsers(dest="action", required=True)
    wsub.add_parser("list")
    wa = wsub.add_parser("add")
    wa.add_argument("name")
    wa.add_argument("--github")
    wa.add_argument("--pypi")
    wa.add_argument("--npm")
    wa.add_argument("--hf")
    wa.add_argument("--role")
    wa.add_argument("--pinned")
    wa.add_argument("--license", help="expected SPDX license id; a change is flagged")
    wa.add_argument("--alt", action="append", help="alternative as OWNER/REPO; repeat or separate with commas")
    wr = wsub.add_parser("remove")
    wr.add_argument("name")
    wp = wsub.add_parser("pin")
    wp.add_argument("name")
    wp.add_argument("version", help="the version you use; 'none' clears it")
    wk = wsub.add_parser("ack")
    wk.add_argument("name")
    wpr = wsub.add_parser("preset")
    wpr.add_argument("name", help=", ".join(sorted(PRESETS)))
    p = sub.add_parser("probe", help="health of GitHub repositories, for comparing alternatives")
    p.add_argument("repos", nargs="*")
    p.add_argument("--preset", default="")
    p.add_argument("--strict", action="store_true", help="exit 1 if any repository is archived, inactive, moved or unreachable")
    p.add_argument("--json", action="store_true")
    sub.add_parser("auto", help="background check (started by the session-start hook)")
    args = ap.parse_args(argv)

    if args.cmd == "check":
        report = run_check(settings(), include_tools=not args.kit_only)
        print(json.dumps(report, indent=2) if args.json else render(report))
        return 1 if needs_attention(report) else 0
    if args.cmd == "report":
        report = load_state().get("last")
        if not report:
            print("no check has run yet; run `python .claude/kit/upkeep.py check`")
            return 0
        print(json.dumps(report, indent=2) if args.json else render(report))
        return 0
    if args.cmd == "update":
        return do_update(settings(), ref=args.ref, from_dir=args.from_dir, yes=args.yes, dry_run=args.dry_run)
    if args.cmd == "watch":
        return cmd_watch(args)
    if args.cmd == "probe":
        return cmd_probe(args)
    if args.cmd == "auto":
        return cmd_auto()
    return 1


if __name__ == "__main__":
    sys.exit(main())
