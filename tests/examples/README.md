# Example Tests (Reference Only)

This folder holds demonstration tests that show how to extend the template's testing stack (fixtures, factories, async DB helpers, etc.). They are intentionally **not** run in CI:

- Pytest is configured with `--ignore=**/examples/*` in `pyproject.toml`, so these files are skipped by default.
- Keep them as living documentation and templates for new feature tests; copy patterns from here into your actual test modules.
- If you need to run them locally for reference, invoke `pytest tests/examples` explicitly.
