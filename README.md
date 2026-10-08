# tidy-lean

Checker implementation, Lean extractor, and regression tests. Project receipts
and retention exceptions remain in `proofs/check/` of the checked repository.
The checker currently uses this project's paper conventions and Lean library.

The source lives in the `kojah/tidy-lean` repository. A consuming project can
use a local `tidy-lean/` symlink to this checkout; edits take effect immediately
through the project path. CI should check out a pinned revision into that path.
Project-specific statement/review receipts remain in the consuming repository.

To invoke the scratch copy directly, select the checked repository explicitly:

```sh
python /home/james/scratch/tidy-lean/check_paper.py \
  --project-root /home/james/scratch/gohawk-experimental
```

Set `TIDYLEAN_PROJECT_ROOT` to the same repository when importing the checker or
running tests from the scratch copy. `make proofs-check` sets the project path
for tests and the CLI automatically.

## Paper and proof correspondence checker

`check_paper.py` checks the included sources of both manuscripts, their explicit
Lean links and evidence classifications, and the existing review/statement
receipts. It also audits every authored project declaration's reachability from
those links: theorems, definitions, structures, inductives and instances.

The orphan check reads Lean's elaborated declarations, following constants in
both declaration types and values (including theorem proof bodies). Definitions,
private declarations and generated helpers participate in the dependency graph.
Lean's `.ilean` source indexes identify authored declarations and add resolved
source references, including explicit tactic arguments that disappear from
compiled proof terms. Generated projections, constructors and extensionality
lemmas remain graph intermediates, rather than separate pruning units. Explicit
mutual inductives are also recognized from Lean declaration ranges, since the
source-index declaration table may omit secondary members of a mutual group.
`Orphans.lean` owns mark-and-sweep, orphan classification, incoming-dependent
counts and retention diagnostics. Python supplies compiled/source-index metadata
and manuscript roots, invokes Lean with JSON, and renders the resulting report;
there is no Python graph-traversal fallback.

Authored declarations outside the resulting closure are errors. Importing a
module alone does not connect its declarations to either paper. Missing, stale
or unsupported source indexes fail the audit; rebuild with `lake build`.
Project source modules not imported by `DeadlockProofs` are reported separately:
the checker cannot certify their proof inventory from the imported environment.
External library declarations are not orphan candidates.

Run the normal `make proofs-check` after building the proofs. When Python lacks
the parser dependency, use the repository's requirements:

```sh
uv run --with-requirements tidy-lean/requirements.txt python tidy-lean/check_paper.py \
  --orphan-report /tmp/paper-orphans.json
```

The optional JSON report includes the full authored declaration/proof inventory,
declaration kinds and dependency graph, every orphan name and source location, the connected
declarations, unimported modules, exceptions and errors. `orphan_dependents`
lists direct project users of each orphan; `unused_orphaned_proofs` identifies
orphaned proofs with no other project declaration depending on them;
`unused_orphaned_declarations` includes unused definitions and structures too.
Helpers in a disconnected proof chain are still orphans even when another orphan
uses them. A check that finds existing orphans exits unsuccessfully; it does not delete proofs, add
paper citations, stamp correspondence receipts or exempt existing debt.

Paper reachability is the default retention rule. A declaration's possible
usefulness alone does not justify retention. Only with a specific, compelling
reason to retain a declaration independently of either paper, record its fully
qualified name and justification in `proofs/check/orphan-roots.json`:

```json
{
  "roots": {"Example.semantic_control": "Negative control for a reproduced unsound pruning bug at an implementation boundary intentionally outside the papers."}
}
```

A standalone root retains its dependency closure but those declarations still
appear in `orphaned_declarations` and `retained_orphans`. Module exclusions apply only
to unimported source modules. Missing names, empty reasons and exceptions that
become redundant fail the check. No exception file is needed when there are no
intentional standalone roots or excluded modules. Excluded modules remain
listed as unimported, so the report does not imply their declarations were audited.

Orphan means eligible for review and pruning, not certified safe to delete.
Implicit automation dependencies (for example, global simp lemmas used without
an explicit tactic argument) are not recorded in source indexes and may vanish
from final proof terms. Removing an orphan must be tested by rebuilding its
module and consumers; a zero-dependent count alone is insufficient.

Normal `proofs-check` runs both the Python regression suite and the Lean
dependency extractor with a temporary compiled fixture, including helpers
used only in declaration types or proof bodies and an unused private theorem.
To run these tests directly without rebuilding the project, use:

```sh
PAPER_CHECK_LEAN_TESTS=1 bash /home/james/.local/bin/agent-test \
  uv run --with-requirements tidy-lean/requirements.txt \
  python -m unittest discover -s tidy-lean -p 'test_*.py'
```

Reachability shows that a declaration supports a retained root. It does not
prove that a paper claim is complete, correctly stated, or faithfully connected
to the native analyzer.

The graph fixtures run through the same native Lean pass as production. Enable
`PAPER_CHECK_LEAN_TESTS=1` and set `TIDYLEAN_PROJECT_ROOT` to a built consuming
project when running the full suite. The default Python-only suite checks
parsing, source-index enrichment and subprocess transport without requiring Lean.
A process failure or malformed native result fails the audit; it cannot silently
produce an empty orphan list.
