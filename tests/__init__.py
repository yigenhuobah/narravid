"""narravid long-term test package (stdlib unittest)."""

import os
import tempfile

# Every unittest process gets its own data root. This keeps concurrent local
# runs from deleting each other's jobs or a developer's real rendered files.
_TEST_DATA_DIR = tempfile.TemporaryDirectory(prefix='narravid-tests-')
os.environ['NARRAVID_DATA_DIR'] = _TEST_DATA_DIR.name
