# Agent instructions

Use `.agents/skills/python-coding-conventions/SKILL.md` for Python changes.
Preserve the existing checker behavior and its correspondence receipt format.

Run the Python suite with:

```sh
uv run --with-requirements requirements.txt python -m unittest discover -s . -p 'test_*.py'
```

Native Lean tests require a built consuming project. Set `TIDYLEAN_PROJECT_ROOT`
to its repository root and `PAPER_CHECK_LEAN_TESTS=1` to enable them.

The current CLI expects the consuming project's `proofs/` and `paper/` layout.
Select that repository with `--project-root` or `TIDYLEAN_PROJECT_ROOT`.
