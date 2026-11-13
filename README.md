# profiler-loc

Lines of code for a list of git repos, measured the way
[codebase-profiler](https://github.com/lh2-tech/codebase-profiler) measures them.
Companion to [repo-metrics](https://github.com/lh2-tech/repo-metrics): that tool
produces a due-diligence scorecard; this one produces just the profiler's LOC
figure, so the two numbers can be compared or reproduced.

## The rule

1. Full clone.
2. Check out the remote branch whose newest commit is most recent (tie goes to the default branch).
3. Run `scc --format json`; `loc` is the sum of the **Code** column over all languages.
   Nothing is excluded: vendored, generated and data files count. `scc` itself skips `.git` and honours `.gitignore`.
4. `primary_language` and `languages_breakdown` come from the same scc figures.

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

- `profiler_loc.csv` / `.jsonl`: `repo, platform, measured_branch, default_branch, loc, files, primary_language, languages_breakdown, status, error, seconds`
- `scc/<repo>.json`: the raw scc rows for each repo

Re-runs skip repos already measured (`--force` to redo). A failing repo is recorded with `status=error` and never stops the batch.
