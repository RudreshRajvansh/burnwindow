"""Replay a sealed evidence study in a new directory and compare its full result.

The original result, frozen models and app files are never overwritten. Only the
execution timestamp is excluded from comparison. Install requirements-validation
and retrieve the corresponding raw-source group before running this command.
"""
from pathlib import Path
import argparse, json, shutil, subprocess, sys

BASE = Path(__file__).resolve().parent
V = BASE / 'data/validation'
JOBS = {
    'geographic': ('validate_evidence.py', ['geographic'], 'geographic.json'),
    'independent': ('validate_evidence.py', ['independent'], 'independent.json'),
    'noaa': ('coverage.py', [], 'coverage.json'),
    'aqua': ('aqua_coverage.py', ['--result-name', 'aqua-coverage-v3.json'], 'aqua-coverage-v3.json'),
    'nasa-viirs': ('viirs_coverage.py', [], 'nasa-viirs-coverage.json'),
}
INPUTS = [
    'protocol.json', 'protocol.sha256', 'download-manifest.json',
    'mtbs-reference.geojson', 'mtbs-manifest.json', 'coverage-amendment.json',
    'coverage-selection.json', 'coverage-sources.json', 'aqua-download-plan.json',
    'nasa-viirs-download-plan.json',
]

def replay(kind, cache, run_directory):
    cache = cache.resolve()
    if not cache.is_dir():
        raise ValueError('Raw-source cache directory does not exist.')
    run_directory = run_directory.resolve()
    # Fail before changing anything if the caller selects an existing location.
    run_directory.mkdir(parents=True, exist_ok=False)
    evidence = run_directory / 'data/validation'
    evidence.mkdir(parents=True)
    for name in {'validate_evidence.py', 'coverage.py', 'aqua_coverage.py', 'viirs_coverage.py'}:
        shutil.copyfile(BASE / name, run_directory / name)
    for name in INPUTS:
        shutil.copyfile(V / name, evidence / name)
    shutil.copytree(V / 'frozen_code', evidence / 'frozen_code', ignore=shutil.ignore_patterns('__pycache__'))
    script, arguments, result_name = JOBS[kind]
    subprocess.run([sys.executable, str(run_directory / script), *arguments,
                    '--cache', str(cache)], cwd=run_directory, check=True)
    expected = json.loads((V / result_name).read_text(encoding='utf-8'))
    actual = json.loads((evidence / result_name).read_text(encoding='utf-8'))
    for document in (expected, actual):
        document.pop('processed_at_utc', None)
        document.pop('scored_at_utc', None)
    if actual != expected:
        raise ValueError('Replayed result differs from the sealed evidence. Both results are preserved for inspection.')
    print('PASS:', kind, 'matches the sealed result, excluding only execution time.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=JOBS)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--run-directory', type=Path, required=True)
    args = parser.parse_args()
    replay(args.kind, args.cache, args.run_directory)
