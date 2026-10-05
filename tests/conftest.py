"""Suite-wide hooks.

Test files and prototypes insert the repository root, `prototypes/` and
`tests/` into `sys.path` on import, without a membership guard; after
collection the path holds about 130 entries but only 10 distinct ones. Every
failed import walks all of them: pyarrow's `pa.array` tries `import dateutil`,
which is not installed, about 140 times per call, so `ladder_fetch`'s parse
took 0.77 s on the long path and 0.07 s on the short one.

Dropping a later copy of an entry cannot change which entry resolves a module,
since the first occurrence always wins; it only removes repeated scans.
"""
import sys

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    sys.path[:] = list(dict.fromkeys(sys.path))
