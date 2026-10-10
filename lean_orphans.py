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
    return run_audit(payload, proofs, lake)


def compiled_audit(proofs, lake):
    """The audit program compiled once per toolchain and program text, with
    the Lean binary and search path to run it: `lean --run` elaborates its
    source on every run otherwise, which cost more than the audit itself.
    Returns None when it cannot be built, and the source is run instead."""
    program = Path(__file__).with_name('Orphans.lean')
    toolchain = Path(proofs, 'lean-toolchain')
    try:
        key = __import__('hashlib').sha256((program.read_text() + toolchain.read_text()).encode()).hexdigest()[:16]
        build = Path(proofs, '.lake', 'paper-check', 'orphans-build', key)
        settings = build / 'lean.json'
        if not settings.is_file():
            source = build / 'src' / 'TidyLean' / 'Orphans.lean'
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(program.read_text())
            (build / 'TidyLean').mkdir(exist_ok=True)
            compile_run = subprocess.run([lake, 'env', 'lean', '--root', str(build / 'src'),
                                          '-o', str(build / 'TidyLean' / 'Orphans.olean'), str(source)],
                                         cwd=proofs, capture_output=True, text=True, timeout=300)
            if compile_run.returncode:
                return None
            environment = subprocess.run([lake, 'env', 'sh', '-c', 'command -v lean; printenv LEAN_PATH'],
                                         cwd=proofs, capture_output=True, text=True, timeout=120)
            if environment.returncode:
                return None
            lean, lean_path = environment.stdout.splitlines()[:2]
            (build / 'driver.lean').write_text('import TidyLean.Orphans\n')
            settings.write_text(json.dumps({'lean': lean, 'lean_path': str(build) + ':' + lean_path}))
        return json.loads(settings.read_text()), build / 'driver.lean'
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def run_audit(payload, proofs, lake):
    compiled = compiled_audit(proofs, lake)
    with tempfile.TemporaryDirectory(prefix='tidylean-orphans-') as directory:
        source = Path(directory) / 'input.json'
        source.write_text(json.dumps(payload), encoding='utf-8')
        if compiled is not None:
            settings, driver = compiled
            run = subprocess.run([settings['lean'], '--run', str(driver), str(source)], cwd=proofs,
                                 capture_output=True, text=True, timeout=180,
                                 env=dict(os.environ, LEAN_PATH=settings['lean_path']))
        else:
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
