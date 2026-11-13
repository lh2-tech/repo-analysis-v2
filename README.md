# repo-analysis-v2

One row of metrics per git repository.

## Requirements

- Python 3.9+ and `git`
- [`jscpd`](https://github.com/kucherenko/jscpd) with Node, for the duplication ratio (a built-in estimate is used without it)
- Private repos: set `GH_TOKEN` / `GITHUB_TOKEN`, `GITLAB_TOKEN` or `BITBUCKET_TOKEN`

## Run

```bash
python3 repo_analysis_v2.py --repos repos.txt --out out/ --workers 4
```

`repos.txt` takes one entry per line: `owner/repo`, a GitHub/GitLab/Bitbucket URL, an SSH URL or a local path.
`.csv`, `.json` and `.jsonl` lists also work. Use `--default-platform gitlab` for bare `group/repo` lines.

`--workers N` measures N repos at the same time (default 4); the measurements inside each repo also run side by side.

Re-running the same command skips repos already measured; add `--force` to measure them again.
A failing repo is recorded and never stops the batch.

## Output

`out/repo_analysis_v2.csv`, one row per repo:

| Repo | Logical LOC (excludes blanks & comments) | Non-Authored LOC (auto-gen + vendored + deps) | Duplication Ratio (0.00-1.00) | Non-Merge Commit Count | Builds & Tests |
|---|---|---|---|---|---|
| lh2-tech/codebase-profiler | 12245 | 0 | 0.0188 | 69 | Build + Tests |
| lh2-tech/repo-metrics | 2454 | 0 | 0.0074 | 8 | Build |
| octocat/Hello-World | 0 | 0 | 0.0 | 3 | Not available |
| owner/missing-repo | | | | | FAILED: repository not found |

`Builds & Tests` reads `Build` when the repo has a Dockerfile, `Build + Tests` when it also has test files, and `Not available` otherwise.

The LOC columns count code files only (not Markdown, CSV, JSON and other data files), the same way codebase-profiler counts source lines. Test files are left out; add `--include-tests` to count them.

`out/repo_analysis_v2.jsonl` has the same rows plus `status`, `error` and `seconds`.
