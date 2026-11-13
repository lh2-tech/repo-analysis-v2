# repo-analysis-v2

Authored-source lines of code for a list of git repos. The branch rule is
[codebase-profiler](https://github.com/lh2-tech/codebase-profiler)'s; unlike the profiler, `loc` here excludes vendored, generated and data files. Companion to [repo-metrics](https://github.com/lh2-tech/repo-metrics): that tool
produces a due-diligence scorecard; this one produces the LOC figures and build/test status on the profiler's branch rule.

## The rule

1. Full clone.
2. Check out the remote branch whose newest commit is most recent (tie goes to the default branch), as the profiler does.
3. Run `scc --format json` and count **authored source code only**:
   - comments and blank lines are never counted (scc's Code column excludes them);
   - vendored directories are skipped: `vendor`, `node_modules`, `dist`, `build`, `generated`, `migrations`;
   - generated and minified files are skipped (`--no-gen --no-min-gen`);
   - data / markup languages are dropped: JSON, XML, YAML, TOML, CSV, Markdown, Plain Text, HTML, CSS, SCSS/Sass/LESS, SVG, properties files, WSDL.
4. The LOC columns:

   | Column | Meaning |
   |---|---|
   | `logical_loc` | untouched scc Code total (the profiler's own figure) |
   | `authored_loc` | `logical_loc` minus vendored dirs and generated/minified files |
   | `non_authored_loc` | `logical_loc - authored_loc` |

## Build and test

`build_test_status` uses the same detection as [repo-metrics](https://github.com/lh2-tech/repo-metrics).

- `--build-check detect` (default) identifies the build statically, so the status stays `Not verified`.
- `--build-check docker` really builds and runs the tests in a language-matched container (needs a Docker daemon; falls back to `detect` without one) and reports `Builds + test suite passes`, `Builds only` or `Not verified`.
- `--build-check none` skips it and leaves the column blank.

`--branch-mode default` measures the platform default branch instead.
Local-path repos are measured as checked out; `--local-latest-branch` moves their HEAD to the newest branch (this edits the checkout).

## Requirements

Python 3.9+ (standard library only), `git`, and [`scc`](https://github.com/boyter/scc) on `PATH` (or `SCC_BIN`).

## Usage

```bash
python3 repo_analysis_v2.py --repos repos.txt --out out/ --workers 4
```

`repos.txt`: one entry per line: `owner/repo`, a GitHub/GitLab/Bitbucket URL, an SSH URL or a local path
(`.csv`, `.json`, `.jsonl` lists also work). Private repos: set `GH_TOKEN`/`GITHUB_TOKEN`, `GITLAB_TOKEN` or
`BITBUCKET_TOKEN`; the token is handed to git through `GIT_ASKPASS` and is never written to a URL, `.git/config` or output.

## Output

- `repo_analysis_v2.csv` / `.jsonl`: `repo, logical_loc, non_authored_loc, authored_loc, build_test_status, status, error, seconds`
- `scc/<repo>.json`: per-language code lines (raw, authored and cleaned) for each repo

Re-runs skip repos already measured (`--force` to redo). A failing repo is recorded with `status=error` and never stops the batch.
