# profiler-loc

Lines of code for a list of git repos, measured the way
[codebase-profiler](https://github.com/lh2-tech/codebase-profiler) measures them.
Unlike the profiler, `loc` here excludes vendored, generated and data files. Companion to [repo-metrics](https://github.com/lh2-tech/repo-metrics): that tool
produces a due-diligence scorecard; this one produces a single LOC figure on the profiler's branch rule, with `raw_loc` alongside.

## The rule

1. Full clone.
2. Check out the remote branch whose newest commit is most recent (tie goes to the default branch), as the profiler does.
3. Run `scc --format json` and count **authored source code only**:
   - comments and blank lines are never counted (scc's Code column excludes them);
   - vendored directories are skipped: `vendor`, `node_modules`, `dist`, `build`, `generated`, `migrations`;
   - generated and minified files are skipped (`--no-gen --no-min-gen`);
   - data / markup languages are dropped: JSON, XML, YAML, TOML, CSV, Markdown, Plain Text, HTML, CSS, SCSS/Sass/LESS, SVG, properties files, WSDL.
4. `loc` is that cleaned figure. `raw_loc` is the untouched profiler figure (sum of the Code column over everything), kept so the two can be compared.
   `primary_language` and `languages_breakdown` describe the cleaned code.

`--branch-mode default` measures the platform default branch instead.
Local-path repos are measured as checked out; `--local-latest-branch` moves their HEAD to the newest branch (this edits the checkout).

## Requirements

Python 3.9+ (standard library only), `git`, and [`scc`](https://github.com/boyter/scc) on `PATH` (or `SCC_BIN`).

## Usage

```bash
python3 profiler_loc.py --repos repos.txt --out out/ --workers 4
```

`repos.txt`: one entry per line: `owner/repo`, a GitHub/GitLab/Bitbucket URL, an SSH URL or a local path
(`.csv`, `.json`, `.jsonl` lists also work). Private repos: set `GH_TOKEN`/`GITHUB_TOKEN`, `GITLAB_TOKEN` or
`BITBUCKET_TOKEN`; the token is handed to git through `GIT_ASKPASS` and is never written to a URL, `.git/config` or output.

## Output

- `profiler_loc.csv` / `.jsonl`: `repo, platform, measured_branch, default_branch, loc, raw_loc, files, primary_language, languages_breakdown, status, error, seconds`
- `scc/<repo>.json`: per-language code lines (raw and cleaned) for each repo

Re-runs skip repos already measured (`--force` to redo). A failing repo is recorded with `status=error` and never stops the batch.
