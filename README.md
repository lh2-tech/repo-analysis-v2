# repo-analysis-v2

One row of metrics per git repository.

## Requirements

- Python 3.9+ and `git`
- [`scc`](https://github.com/boyter/scc) on `PATH` (or set `SCC_BIN`)
- [`jscpd`](https://github.com/kucherenko/jscpd) with Node, for the duplication ratio (a built-in estimate is used without it)
- Private repos: set `GH_TOKEN` / `GITHUB_TOKEN`, `GITLAB_TOKEN` or `BITBUCKET_TOKEN`

## Run

```bash
python3 repo_analysis_v2.py --repos repos.txt --out out/ --workers 4
```

`repos.txt` takes one entry per line: `owner/repo`, a GitHub/GitLab/Bitbucket URL, an SSH URL or a local path.
`.csv`, `.json` and `.jsonl` lists also work. Use `--default-platform gitlab` for bare `group/repo` lines.

Re-running the same command skips repos already measured; add `--force` to measure them again.
A failing repo is recorded and never stops the batch.

## Output

`out/repo_analysis_v2.csv`, one row per repo:

| Repo | Logical LOC (excludes blanks & comments) | Non-Authored LOC (auto-gen + vendored + deps) | Duplication Ratio (0.00-1.00) | Non-Merge Commit Count | Builds & Tests |
|---|---|---|---|---|---|
| lh2-tech/codebase-profiler | 14221 | 1 | 0.0188 | 69 | Build + Test present |
| lh2-tech/repo-metrics | 2240 | 0 | 0.0075 | 7 | Build + Test present |
| owner/missing-repo | | | | | FAILED: repository not found |

`Builds & Tests` reads `Build + Test present` when the repo has a Dockerfile and `Not verified` otherwise.

`out/repo_analysis_v2.jsonl` has the same rows plus `status`, `error` and `seconds`.
