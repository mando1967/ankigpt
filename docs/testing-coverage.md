# Testing and Coverage

CI runs Rust, Python, and TypeScript tests plus lint/type checks. Coverage is
orchestrated in `justfile` with direct CLI calls, using ninja only to prepare
generated build artifacts that the test commands need.

## Quick reference

```sh
just test                        # run all tests (no coverage)
just test --coverage             # run all tests + enforce coverage thresholds
just test --coverage --html      # same + generate HTML reports under out/coverage/

just test-rust                   # Rust only
just test-rust --coverage
just test-rust --coverage --html

just test-py                     # Python (pylib + qt) only
just test-py --coverage
just test-py --coverage --html

just test-ts                     # TypeScript/Svelte Vitest only
just test-ts --coverage
just test-ts --coverage --html
```

HTML reports are written under `out/coverage/` (gitignored).

## Coverage tools and thresholds

| Stack               | Test runner                          | Coverage tool    | Minimum |
| ------------------- | ------------------------------------ | ---------------- | ------: |
| Rust workspace      | `cargo nextest` via `cargo-llvm-cov` | `cargo-llvm-cov` |     60% |
| Python `pylib/anki` | `pytest pylib/tests`                 | `coverage.py`    |     65% |
| Python `qt/aqt`     | `pytest qt/tests`                    | `coverage.py`    |     20% |
| TypeScript/Svelte   | `vitest run`                         | Vitest V8        |      5% |

Linux pull requests run `just test --coverage` in CI. macOS and Windows
jobs run `just test` (no coverage enforcement) for now.

## Notes

- **Rust** — `cargo-llvm-cov` is installed on demand into `out/bin/` to avoid
  polluting the global cargo install. Coverage runs rebuild the workspace with
  instrumentation, so they are slower than plain `just test-rust`.
  **Windows ARM64 (`aarch64-pc-windows-msvc`) is not supported**: the Rust
  compiler produces malformed `.profraw` files on that target
  ([rust-lang/rust#150123](https://github.com/rust-lang/rust/issues/150123),
  [cargo-llvm-cov#436](https://github.com/taiki-e/cargo-llvm-cov/issues/436)).
  `just test-rust --coverage` exits with a clear message on ARM64 Windows;
  use `just test-rust` (no coverage) or rely on CI (Linux) for enforcement.
- **Python** — coverage is split across two suites (`pylib` and `qt`) because
  they have different `PYTHONPATH` setups and test folders.
- **TypeScript** — coverage is measured only over code reachable through
  Vitest's module graph. Svelte component rendering behavior is not covered.

## Gaps and future improvements

- Raise thresholds gradually as the test suite grows and CI timings stabilise.
- Exclude generated files from coverage denominators where appropriate.
- Publish `out/coverage/` as a CI artifact so reviewers can browse HTML
  reports directly from a PR.
- Consider diff/changed-file coverage once baselines are stable — it is a
  better enforcement mechanism for incremental improvement than whole-repo
  thresholds.
- Add component or browser tests for Svelte UI surfaces if Svelte coverage
  is intended to cover rendered component behaviour.

## Windows test permissions and temporary paths

If pytest cannot access an old `pytest-of-<user>` directory, run checks with a
fresh temporary root. Keep it short: installer tests create deeply nested
paths that can exceed Windows path limits inside a long checkout directory.
From the repository root, in PowerShell:

```powershell
$checkTemp = Join-Path $env:TEMP ('agpt-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $checkTemp | Out-Null
$env:PYTEST_DEBUG_TEMPROOT = $checkTemp
$env:DPRINT_CACHE_DIR = Join-Path (Get-Location) 'out/dprint-cache'
just --shell powershell --shell-arg=-NoProfile --shell-arg=-Command check
```

This uses pytest's normal numbered temporary directories without deleting or
changing permissions on existing folders. The dprint cache is kept in the
workspace; its first use may need internet access to download formatting
plugins. These environment settings last for the current PowerShell session.

The upstream contributor-license check is separate from code validation.
AnkiGPT fork maintainers who are not submitting contributions to upstream Anki
can use the existing `CONTRIBUTORS_BYPASS_EMAILS` allowlist for approved author
emails (comma-separated). Set it before running `just check`; CI reads the
repository variable with the same name. This affects only contributor metadata,
not tests, linting, or type checks. Do not add a name to upstream `CONTRIBUTORS`
merely to pass a check: that file includes an explicit licensing declaration.
