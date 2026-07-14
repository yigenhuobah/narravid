#!/usr/bin/env python3
"""narravid max test runner (stdlib only — no pytest required).

Usage:
  python run_tests.py              # default: unit + security + cancel + live
  python run_tests.py --fast       # unit + security + cancel (no live server)
  python run_tests.py --max        # everything including ffmpeg pipeline smoke
  python run_tests.py --layer unit
  python run_tests.py --layer security,pipeline
  python run_tests.py --list

Layers:
  unit       pure helpers (always run)
  security   HTTP path / upload / export / import
  cancel     cancel token / fail-fast / active render
  live       ephemeral ThreadingHTTPServer API
  pipeline   ffmpeg process_audio + CLI smoke (needs ffmpeg)
  legacy     also run test_regressions.py + _verify_fix.py if present

Exit code 0 only if all selected layers pass.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

LAYERS = {
    'unit': ['tests.test_unit_helpers', 'tests.test_platform'],
    'security': ['tests.test_security_http'],
    'cancel': ['tests.test_cancel_concurrency'],
    'live': ['tests.test_live_api'],
    'pipeline': ['tests.test_pipeline_ffmpeg'],
}

DEFAULT = ['unit', 'security', 'cancel', 'live']
FAST = ['unit', 'security', 'cancel']
MAX = ['unit', 'security', 'cancel', 'live', 'pipeline', 'legacy']


def run_unittest_modules(modules: list[str], verbosity: int = 2) -> unittest.TestResult:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for mod in modules:
        try:
            suite.addTests(loader.loadTestsFromName(mod))
        except Exception as e:
            print(f'[ERROR] cannot load {mod}: {e}')
            # synthesize a failing test
            class LoadFail(unittest.TestCase):
                def test_load(self, _m=mod, _e=e):
                    self.fail(f'load {_m}: {_e}')
            suite.addTest(LoadFail('test_load'))
    runner = unittest.TextTestRunner(verbosity=verbosity)
    return runner.run(suite)


def run_legacy(verbosity: int = 1) -> bool:
    ok = True
    for script in ('test_regressions.py', '_verify_fix.py'):
        path = ROOT / script
        if not path.exists():
            print(f'[SKIP] legacy {script} not found')
            continue
        print(f'\n=== legacy: {script} ===')
        r = subprocess.run([sys.executable, str(path)], cwd=str(ROOT))
        if r.returncode != 0:
            ok = False
            print(f'[FAIL] {script} exit={r.returncode}')
        else:
            print(f'[PASS] {script}')
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description='narravid max test runner')
    ap.add_argument('--fast', action='store_true', help='unit+security+cancel only')
    ap.add_argument('--max', action='store_true', help='all layers including pipeline+legacy')
    ap.add_argument('--layer', type=str, default='',
                    help=f'comma list: {",".join(LAYERS)} ,legacy')
    ap.add_argument('--list', action='store_true', help='list layers and exit')
    ap.add_argument('-q', '--quiet', action='store_true')
    args = ap.parse_args(argv)

    if args.list:
        print('layers:')
        for k, mods in LAYERS.items():
            print(f'  {k:10} {", ".join(mods)}')
        print('  legacy     test_regressions.py + _verify_fix.py')
        print('presets: default=', DEFAULT, 'fast=', FAST, 'max=', MAX)
        return 0

    if args.max:
        selected = list(MAX)
    elif args.fast:
        selected = list(FAST)
    elif args.layer:
        selected = [x.strip() for x in args.layer.split(',') if x.strip()]
    else:
        selected = list(DEFAULT)

    unknown = [x for x in selected if x not in LAYERS and x != 'legacy']
    if unknown:
        print('unknown layers:', unknown)
        return 2

    verbosity = 1 if args.quiet else 2
    print('narravid max tests')
    print('  root:', ROOT)
    print('  layers:', ', '.join(selected))
    t0 = time.time()

    overall_ok = True
    total_run = total_fail = total_err = total_skip = 0

    for layer in selected:
        if layer == 'legacy':
            if not run_legacy(verbosity):
                overall_ok = False
            continue
        mods = LAYERS[layer]
        print(f'\n=== layer: {layer} ===')
        result = run_unittest_modules(mods, verbosity=verbosity)
        total_run += result.testsRun
        total_fail += len(result.failures)
        total_err += len(result.errors)
        total_skip += len(result.skipped)
        if not result.wasSuccessful():
            overall_ok = False

    dt = time.time() - t0
    print('\n' + '=' * 60)
    print(f'ran ~{total_run} unittest cases in {dt:.1f}s')
    print(f'  failures={total_fail} errors={total_err} skipped={total_skip}')
    if overall_ok:
        print('ALL SELECTED LAYERS PASSED')
        return 0
    print('SOME LAYERS FAILED')
    return 1


if __name__ == '__main__':
    sys.exit(main())
