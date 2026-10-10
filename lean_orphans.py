"""I/O bridge to the native Lean orphan audit; graph policy lives in Orphans.lean."""
# JSON is exchanged with a foreign toolchain; retain its existing error vocabulary.
import json
import os
import subprocess
import tempfile
from pathlib import Path

AUDIT_MARKER = '@@ORPHAN_AUDIT '


def audit(nodes, modules, paper_roots, source_modules, exceptions=None, *, proofs=None, lake=None):
    """Run Lean's mark-and-sweep and return the unchanged report schema.

    Callers provide compiled/source-enriched metadata. No Python reachability
    fallback is used: a failed Lean process must fail the audit.
    """
    if proofs is None:
        root = Path(os.environ.get('TIDYLEAN_PROJECT_ROOT', Path(__file__).resolve().parent.parent))
        proofs = root / 'proofs'
    lake = lake or os.environ.get('LAKE', str(Path.home() / '.elan/bin/lake'))
    payload = dict(nodes=[dict(node, source_dependencies=node.get('source_dependencies', []))
                          for node in nodes.values()], modules=sorted(modules),
                   paper_roots=sorted(paper_roots), source_modules=sorted(source_modules),
                   exceptions={} if exceptions is None else exceptions)
    # The report is a function of the payload and the audit program, so a
    # repeated audit of the same inventory reads the previous report.
    import hashlib
    audit_source = Path(__file__).with_name('Orphans.lean').read_text()
    toolchain = Path(proofs, 'lean-toolchain').read_text() if Path(proofs, 'lean-toolchain').is_file() else ''
    key = hashlib.sha256((audit_source + toolchain + json.dumps(payload, sort_keys=True)).encode()).hexdigest()
    cache_dir = Path(proofs, '.lake', 'paper-check', 'orphans')
    cached = cache_dir / (key + '.json')
    if cached.is_file():
        return json.loads(cached.read_text())
    report = run_audit(payload, proofs, lake)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        for stale in cache_dir.glob('*.json'):
            stale.unlink()
        cached.write_text(json.dumps(report))
    except OSError:
        pass  # no proof workspace to cache in, as in the tests
    return report


def run_audit(payload, proofs, lake):
    with tempfile.TemporaryDirectory(prefix='tidylean-orphans-') as directory:
        source = Path(directory) / 'input.json'
        source.write_text(json.dumps(payload), encoding='utf-8')
        run = subprocess.run([lake, 'env', 'lean', '--run',
                              str(Path(__file__).with_name('Orphans.lean')), str(source)],
                             cwd=proofs, capture_output=True, text=True, timeout=180)
    records = [line[len(AUDIT_MARKER):] for line in run.stdout.splitlines()
               if line.startswith(AUDIT_MARKER)]
    if len(records) != 1:
        raise RuntimeError('Lean orphan audit failed:\n' + (run.stdout + run.stderr)[-4000:])
    result = json.loads(records[0])
    if 'error' in result:
        raise ValueError(result['error'])
    if run.returncode or not isinstance(result.get('report'), dict):
        raise RuntimeError('invalid Lean orphan audit response:\n' + (run.stdout + run.stderr)[-4000:])
    return result['report']


def reachable(nodes, roots):
    """Compatibility adapter for callers requesting only paper-root closure."""
    return set(audit(nodes, set(), roots, set())['paper_connected'])
