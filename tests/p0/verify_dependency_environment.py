"""Verify an installed P0 dependency subset against the repository lock."""

from __future__ import annotations

import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tests.p0.unit.test_dependency_declaration import (
    MANIFEST_PATH,
    _dependency_fingerprint,
    _installed_dependency_fingerprint,
    _read_locked_distributions,
)


def main() -> int:
    locked = _read_locked_distributions()
    declared_fingerprint = _dependency_fingerprint(locked)
    installed_fingerprint = _installed_dependency_fingerprint(locked)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    result = {
        "declared_fingerprint": declared_fingerprint,
        "installed_fingerprint": installed_fingerprint,
        "versions": {
            name: version for name, (version, _) in sorted(locked.items())
        },
    }
    print(json.dumps(result, sort_keys=True))
    return int(
        installed_fingerprint != declared_fingerprint
        or manifest["dependency_fingerprint"] != declared_fingerprint
    )


if __name__ == "__main__":
    raise SystemExit(main())
