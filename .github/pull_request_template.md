## What and why

<!-- What does this change, and what problem does it solve? Link the issue if there is one. -->

## How it was tested

- [ ] `python -m pytest tests/pure`
- [ ] Blender tests for the affected area (`tests/run_tests.py -- -k ...`) or the full suite
- [ ] Tried in Blender by hand (describe what you checked)

## Checklist

- [ ] Setup followed by Remove still restores the original material exactly
- [ ] Painted masks are never lost or overwritten without a user action
- [ ] Tests added or updated
- [ ] CHANGELOG.md updated for user-visible changes
