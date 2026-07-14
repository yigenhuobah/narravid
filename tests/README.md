# narravid tests (long-term / max)

Stdlib-only suite — **no pytest**. Entry point: repo-root `run_tests.py`.

## Quick start

```bash
# Default gate (unit + security + cancel + live API)
python run_tests.py

# Pre-commit fast path
python run_tests.py --fast

# Full max (includes ffmpeg pipeline smoke + legacy scripts)
python run_tests.py --max

# One or more layers
python run_tests.py --layer unit,security
python run_tests.py --list
```

## Layers

| Layer | Module(s) | Needs | Purpose |
|-------|-----------|-------|---------|
| `unit` | `test_unit_helpers`, `test_platform` | nothing | atempo, SRT, CancelToken, path helpers, **cross-platform** (fonts/TTS/kill/ffmpeg names) |
| `security` | `test_security_http` | nothing | `/rendered`, upload, render_id, export/import, zip slip, late-cancel, srt backfill |
| `cancel` | `test_cancel_concurrency` | nothing | fail-fast labeling, kill-on-cancel, active render, frontend UX markers |
| `live` | `test_live_api` | free port | real `ThreadingHTTPServer` ops (render mocked; no Edge TTS) |
| `pipeline` | `test_pipeline_ffmpeg` | ffmpeg | `process_audio`, hold-only CLI smoke |
| `legacy` | `test_regressions.py`, `_verify_fix.py` | — | older ad-hoc checks kept for continuity |

### What `live` covers (mocked render)

Uses `tests.support.fake_video_auto_main` so lifecycle is fast/offline:

- upload (incl. Chinese filename ASCII), BGM list, thumb allow/deny
- fake render → status `video`/`srt` → download
- mid-render cancel, **late cancel keeps video**
- serial `RENDER_LOCK` (two jobs)
- export/import roundtrip, bad zip 400
- templates CRUD with `bgm` / card durations, clean API

## Full product E2E

Still use the existing heavy script (Edge TTS + real render):

```bash
python test_e2e.py
python test_e2e.py --port 5001 --workers 2 --keep
```

`test_e2e.py` also covers templates, export/import, late-cancel, clean (in addition to full TTS render).

`run_tests.py --max` does **not** replace `test_e2e.py`; it is the fast/medium gate for day-to-day development. Run e2e before release.

Local scratch scripts (`_ux_ops_test.py`, `_ux_fix_verify.py`, `_test_*.py`) are optional/manual and not part of the suite.

## Layout

```
tests/
  support.py              # assets, HTTP helpers, live_webui()
  test_unit_helpers.py
  test_security_http.py
  test_cancel_concurrency.py
  test_live_api.py
  test_pipeline_ffmpeg.py
  README.md
run_tests.py              # suite entry
test_regressions.py       # focused post-audit regressions (legacy layer)
test_e2e.py               # full WebUI e2e
```

## Conventions for new tests

1. Prefer `unittest.TestCase` in `tests/test_*.py`.
2. Put shared fixtures in `tests/support.py` (do not depend on pytest fixtures).
3. Mark ffmpeg-only tests with `@unittest.skipUnless(has_ffmpeg(), ...)`.
4. Never start real Edge TTS in unit/security/cancel layers — mock or use empty-text hold scenes.
5. Clean up files under `rendered/webui/` that tests create (`project_*`, temp uploads).
6. Security tests must include at least one **negative** case (reject path / zip slip / bad id).

## Suggested workflow

| When | Command |
|------|---------|
| Every edit | `python run_tests.py --fast` |
| Before push | `python run_tests.py` |
| Before release / tag | `python run_tests.py --max` then `python test_e2e.py` |

## Platform notes

| Layer | Windows | Linux |
|-------|---------|-------|
| `--fast` / default | ✅ | ✅ (no system TTS required) |
| `pipeline` | needs ffmpeg | `apt install ffmpeg` |
| `test_e2e.py` | Edge + ffmpeg | Edge + ffmpeg; **do not** use `--engine system` |
| System TTS | PowerShell | unsupported by design |

Linux CI: `.github/workflows/test-linux.yml` installs `ffmpeg` + `fonts-noto-cjk` and runs `run_tests.py`.
