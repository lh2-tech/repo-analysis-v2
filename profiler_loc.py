#!/usr/bin/env python3
"""LOC for a list of git repos, measured the way codebase-profiler does it.

Measured the way codebase-profiler does it (full clone, newest-commit remote
branch with ties going to the default branch, scc on the checkout), then
cleaned so that only authored source code is counted:

  * comments and blank lines: never counted (scc's Code column excludes them)
  * vendored directories: vendor, node_modules, dist, build, generated,
    migrations are skipped (--exclude-dir)
  * generated and minified files: skipped (--no-gen --no-min-gen)
  * data / markup languages: JSON, XML, YAML, TOML, CSV, Markdown, Plain Text,
    HTML, CSS, SCSS/Sass/LESS, SVG, properties files, WSDL are dropped

`loc` is that cleaned figure. `raw_loc` is the untouched profiler figure (sum
of scc's Code column over everything) so the two can be compared.
primary_language and languages_breakdown describe the cleaned code.
Local-path repos are measured as checked out; --local-latest-branch moves their
HEAD to the newest branch like the profiler does (this edits the checkout).

Output (under --out): profiler_loc.csv, profiler_loc.jsonl, and
scc/<repo>.json (per-language code lines, raw and cleaned) for every repo. A failing repo gets
status=error and never stops the batch. Existing results are skipped unless
--force.

Input: one entry per line (blank lines and # comments ignored):
    owner/repo | https://github.com/owner/repo | git@host:owner/repo.git |
    https://gitlab.com/group/sub/repo | /path/to/local/clone
`.csv` (column full_name / url / repo_url / path), `.json` and `.jsonl` lists
are accepted too. Bare `owner/repo` is GitHub unless --default-platform gitlab.

Tokens for private repos, from the environment: GH_TOKEN / GITHUB_TOKEN,
GITLAB_TOKEN, BITBUCKET_TOKEN. They are passed to git through GIT_ASKPASS,
never written to the clone's .git/config or to any output file.

    python3 profiler_loc.py --repos repos.txt --out out/ --workers 4
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

FIELDS = [
    "repo", "platform", "measured_branch", "default_branch", "loc", "raw_loc", "files",
    "primary_language", "languages_breakdown", "status", "error", "seconds",
]
HOSTS = {"github": "github.com", "gitlab": "gitlab.com", "bitbucket": "bitbucket.org"}
EXCLUDE_DIRS = ["vendor", "node_modules", "dist", "build", "generated", "migrations"]
DATA_LANGUAGES = {
    "JSON", "Plain Text", "XML", "Markdown", "CSV", "Text", "Properties File",
    "SVG", "HTML", "CSS", "LESS", "Sass", "SCSS", "YAML", "TOML",
    "Web Services Description Language",
}
_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, file=sys.stderr, flush=True)


# ── input ────────────────────────────────────────────────────────────────────

def _entry_to_spec(raw: str, default_platform: str) -> dict:
    raw = re.sub(r"\s+\[.*\]\s*$", "", raw.strip())  # drop "  [private]" annotations
    if not raw:
        return {}
    if os.path.isdir(raw):
        return {"name": Path(raw).resolve().name, "platform": "local", "path": str(Path(raw).resolve())}
    m = re.match(r"^git@([^:]+):(.+?)(?:\.git)?$", raw)
    if m:
        host, path = m.groups()
    elif "://" in raw:
        m = re.match(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", raw)
        if not m:
            return {}
        host, path = m.groups()
        path = re.sub(r"/(-/)?(tree|blob|src)/.*$", "", path)
    else:
        host, path = HOSTS.get(default_platform, "github.com"), raw.strip("/")
    platform = next((p for p, h in HOSTS.items() if host.lower() == h), "git")
    if platform == "git":
        platform = "gitlab" if "gitlab" in host.lower() else "bitbucket" if "bitbucket" in host.lower() else "git"
    return {"name": path, "platform": platform, "url": f"https://{host}/{path}.git", "host": host}


def read_specs(path: Path, default_platform: str) -> list[dict]:
    entries: list[str] = []
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                for key in ("full_name", "url", "repo_url", "path"):
                    if row.get(key):
                        entries.append(row[key])
                        break
    elif suffix in (".json", ".jsonl"):
        text = path.read_text(encoding="utf-8")
        items = ([json.loads(l) for l in text.splitlines() if l.strip()] if suffix == ".jsonl"
                 else json.loads(text))
        for item in items:
            if isinstance(item, str):
                entries.append(item)
            elif isinstance(item, dict):
                for key in ("full_name", "url", "repo_url", "path"):
                    if item.get(key):
                        entries.append(item[key])
                        break
    else:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split(" #")[0].strip()
            if line and not line.startswith("#"):
                entries.append(line)
    specs, seen = [], set()
    for e in entries:
        spec = _entry_to_spec(e, default_platform)
        if spec and spec["name"] not in seen:
            seen.add(spec["name"])
            specs.append(spec)
    return specs


# ── git ──────────────────────────────────────────────────────────────────────

def _askpass_script(tmp: Path, token: str, user: str) -> dict:
    """GIT_ASKPASS helper so the token never lands in a URL or .git/config."""
    script = tmp / "askpass.sh"
    script.write_text('#!/bin/sh\ncase "$1" in\n  Username*) printf %s "$GIT_USER_NAME";;\n  *) printf %s "$GIT_TOKEN_VALUE";;\nesac\n')
    script.chmod(stat.S_IRWXU)
    return {"GIT_ASKPASS": str(script), "GIT_USER_NAME": user, "GIT_TOKEN_VALUE": token,
            "GIT_TERMINAL_PROMPT": "0"}


def token_for(platform: str) -> tuple[str, str]:
    env = os.environ
    if platform == "github":
        return (env.get("GH_TOKEN") or env.get("GITHUB_TOKEN") or "", "x-access-token")
    if platform == "gitlab":
        return (env.get("GITLAB_TOKEN") or "", "oauth2")
    if platform == "bitbucket":
        return (env.get("BITBUCKET_TOKEN") or "", "x-token-auth")
    return ("", "")


def git(repo: Optional[Path], *args: str, env: Optional[dict] = None, timeout: int = 3600) -> str:
    cmd = ["git"] + (["-C", str(repo)] if repo else []) + list(args)
    full_env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", **(env or {})}
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=full_env)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "git failed").strip()[-400:])
    return r.stdout


def select_latest_branch(repo: Path, default_branch: str, local: bool) -> str:
    """Check out the remote branch with the newest commit (tie -> default). Same rule as the profiler."""
    prefix = "refs/remotes/origin/"
    fmt = "--format=%(refname)\t%(committerdate:unix)"
    out = git(repo, "for-each-ref", "--sort=-committerdate", fmt, prefix)
    if local and not out.strip():
        prefix = "refs/heads/"
        out = git(repo, "for-each-ref", "--sort=-committerdate", fmt, prefix)
    cands: list[tuple[int, str]] = []
    for line in out.splitlines():
        ref, _, ts = line.partition("\t")
        name = ref[len(prefix):] if ref.startswith(prefix) else ""
        if name and name != "HEAD" and ts.strip().isdigit():
            cands.append((int(ts), name))
    if not cands:
        return ""
    newest = max(t for t, _ in cands)
    tied = [n for t, n in cands if t == newest]
    chosen = default_branch if default_branch in tied else tied[0]
    try:
        current = git(repo, "symbolic-ref", "--short", "HEAD").strip()
    except RuntimeError:
        current = ""
    if chosen != current:
        if prefix.startswith("refs/remotes/"):
            git(repo, "checkout", "-q", "-f", "-B", chosen, f"origin/{chosen}")
        else:
            git(repo, "checkout", "-q", "-f", chosen)
    return chosen


def default_branch_of(repo: Path) -> str:
    try:
        ref = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
        return ref.split("/", 1)[1] if "/" in ref else ref
    except RuntimeError:
        try:
            return git(repo, "symbolic-ref", "--short", "HEAD").strip()
        except RuntimeError:
            return ""


# ── scc ──────────────────────────────────────────────────────────────────────

def run_scc(scc_bin: str, repo: Path, timeout: int, extra: tuple = ()) -> tuple[dict[str, int], dict[str, int]]:
    """Return ({language: code lines}, {language: file count})."""
    r = subprocess.run([scc_bin, "--format", "json", *extra, str(repo)],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "scc failed")[-400:])
    data = json.loads(r.stdout or "[]")
    by_lang: dict[str, int] = {}
    files_by_lang: dict[str, int] = {}
    for row in data if isinstance(data, list) else []:
        name = row.get("Name") or row.get("name") or "Unknown"
        by_lang[name] = by_lang.get(name, 0) + int(row.get("Code") or row.get("code") or 0)
        files_by_lang[name] = files_by_lang.get(name, 0) + int(row.get("Count") or 0)
    return by_lang, files_by_lang


def clean_scc(scc_bin: str, repo: Path, timeout: int) -> tuple[dict[str, int], int]:
    """Authored source only: no vendored dirs, generated/minified files or data languages."""
    extra = ["--no-gen", "--no-min-gen"]
    for d in EXCLUDE_DIRS:
        extra += ["--exclude-dir", d]
    by_lang, files_by_lang = run_scc(scc_bin, repo, timeout, tuple(extra))
    code = {k: v for k, v in by_lang.items() if k not in DATA_LANGUAGES and v > 0}
    return code, sum(files_by_lang.get(k, 0) for k in code)


def languages_breakdown(by_language: dict[str, int]) -> tuple[str, str]:
    langs = {k: v for k, v in by_language.items() if v > 0}
    total = sum(langs.values())
    if not total:
        return "", ""
    ordered = sorted(langs.items(), key=lambda kv: (-kv[1], kv[0]))
    return ordered[0][0], "; ".join(f"{n}:{100 * c / total:.1f}%" for n, c in ordered)


def find_scc() -> Optional[str]:
    explicit = os.environ.get("SCC_BIN")
    if explicit and Path(explicit).is_file():
        return explicit
    return shutil.which("scc")


# ── per repo ─────────────────────────────────────────────────────────────────

def safe_name(name: str) -> str:
    return re.sub(r"[^\w.-]+", "__", name)


def measure(spec: dict, scc_bin: str, out: Path, args: argparse.Namespace) -> dict:
    t0 = time.time()
    row = {k: "" for k in FIELDS}
    row.update(repo=spec["name"], platform=spec["platform"], status="ok")
    work: Optional[Path] = None
    try:
        if spec["platform"] == "local":
            repo = Path(spec["path"])
            local = True
        else:
            local = False
            work = Path(tempfile.mkdtemp(prefix="profiler-loc-", dir=args.tmp_dir or None))
            repo = work / "repo"
            env: dict = {}
            token, user = token_for(spec["platform"])
            if token:
                env = _askpass_script(work, token, user)
            git(None, "clone", "-q", spec["url"], str(repo), env=env, timeout=args.clone_timeout)
            # Don't leave a way to re-fetch with credentials, and keep the URL token-free.
            git(repo, "remote", "set-url", "origin", spec["url"])
        row["default_branch"] = default_branch_of(repo)
        # Like the profiler, a local checkout is measured as it stands unless asked: moving HEAD edits the user's repo.
        if args.branch_mode == "latest" and (not local or args.local_latest_branch):
            row["measured_branch"] = select_latest_branch(repo, row["default_branch"], local)
        if not row["measured_branch"]:
            row["measured_branch"] = row["default_branch"]
        raw_by_lang, _ = run_scc(scc_bin, repo, args.scc_timeout)
        clean_by_lang, clean_files = clean_scc(scc_bin, repo, args.scc_timeout)
        (out / "scc").mkdir(parents=True, exist_ok=True)
        (out / "scc" / f"{safe_name(spec['name'])}.json").write_text(
            json.dumps({"raw_by_language": raw_by_lang, "clean_by_language": clean_by_lang}), encoding="utf-8")
        row["raw_loc"] = sum(raw_by_lang.values())
        row["loc"], row["files"] = sum(clean_by_lang.values()), clean_files
        row["primary_language"], row["languages_breakdown"] = languages_breakdown(clean_by_lang)
    except Exception as exc:  # noqa: BLE001 - a bad repo is recorded, never fatal
        row["status"], row["error"] = "error", " ".join(str(exc).split())[-300:]
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
        row["seconds"] = round(time.time() - t0, 1)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="LOC measured the way codebase-profiler does it.")
    ap.add_argument("--repos", required=True, help="repo list (txt/csv/json/jsonl)")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--default-platform", choices=list(HOSTS), default="github")
    ap.add_argument("--branch-mode", choices=["latest", "default"], default="latest",
                    help="latest (profiler default): newest-commit branch; default: the platform default branch")
    ap.add_argument("--local-latest-branch", action="store_true",
                    help="also move HEAD of local-path repos to the newest-commit branch (edits that checkout)")
    ap.add_argument("--scc-timeout", type=int, default=600)
    ap.add_argument("--clone-timeout", type=int, default=3600)
    ap.add_argument("--tmp-dir", default="", help="where temporary clones go (default: system temp)")
    ap.add_argument("--force", action="store_true", help="re-measure repos already in the output")
    args = ap.parse_args()

    scc_bin = find_scc()
    if not scc_bin:
        print("ERROR: scc not found. Install it (https://github.com/boyter/scc) or set SCC_BIN.", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    jsonl = out / "profiler_loc.jsonl"
    done: dict[str, dict] = {}
    if jsonl.exists() and not args.force:
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("status") == "ok":
                    done[r["repo"]] = r
    specs = read_specs(Path(args.repos), args.default_platform)
    todo = [s for s in specs if s["name"] not in done]
    log(f"{len(specs)} repos, {len(done)} already done, {len(todo)} to measure; scc={scc_bin}")

    rows = dict(done)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(measure, s, scc_bin, out, args): s for s in todo}
        for fut in as_completed(futs):
            r = fut.result()
            rows[r["repo"]] = r
            log(f"{r['status'].upper():5} {r['repo']} loc={r['loc']} branch={r['measured_branch']} ({r['seconds']}s) {r['error']}")
            with jsonl.open("w", encoding="utf-8") as fh:  # rewrite so a rerun never duplicates rows
                for v in rows.values():
                    fh.write(json.dumps(v) + "\n")

    ordered = [rows[s["name"]] for s in specs if s["name"] in rows]
    with (out / "profiler_loc.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(ordered)
    bad = sum(1 for r in ordered if r["status"] != "ok")
    log(f"done: {len(ordered) - bad} ok, {bad} failed -> {out / 'profiler_loc.csv'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
