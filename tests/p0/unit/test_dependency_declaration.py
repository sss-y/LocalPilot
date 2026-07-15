from __future__ import annotations

import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = REPOSITORY_ROOT / "requirements-p0.lock"
MANIFEST_PATH = REPOSITORY_ROOT / "p0_baseline" / "manifest.json"
EXPECTED_DISTRIBUTIONS = {
    "certifi",
    "charset-normalizer",
    "idna",
    "requests",
    "urllib3",
}
PIN_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)\s*\\$")
HASH_PATTERN = re.compile(r"^\s+--hash=sha256:([0-9a-f]{64})(?:\s*\\)?$")


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _read_locked_distributions() -> dict[str, tuple[str, tuple[str, ...]]]:
    lines = LOCK_PATH.read_text(encoding="utf-8").splitlines()
    locked: dict[str, tuple[str, tuple[str, ...]]] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line or line.startswith("#"):
            index += 1
            continue

        pin = PIN_PATTERN.fullmatch(line)
        if pin is None:
            raise AssertionError(f"non-exact requirement in P0 lock: {line!r}")
        name = _canonical_name(pin.group(1))
        hashes: list[str] = []
        index += 1
        while index < len(lines):
            hash_match = HASH_PATTERN.fullmatch(lines[index])
            if hash_match is None:
                break
            hashes.append(hash_match.group(1))
            index += 1
        if not hashes:
            raise AssertionError(f"missing sha256 install hash for {name}")
        if name in locked:
            raise AssertionError(f"duplicate locked distribution: {name}")
        locked[name] = (pin.group(2), tuple(hashes))
    return locked


def _dependency_fingerprint(locked: dict[str, tuple[str, tuple[str, ...]]]) -> str:
    declaration = "".join(
        f"{name}=={locked[name][0]}\n" for name in sorted(locked)
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(declaration).hexdigest()}"


def _installed_dependency_fingerprint(
    locked: dict[str, tuple[str, tuple[str, ...]]],
) -> str:
    installed = {
        name: (metadata.version(name), hashes)
        for name, (_, hashes) in locked.items()
    }
    return _dependency_fingerprint(installed)


class DependencyDeclarationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.locked = _read_locked_distributions()

    def test_lock_contains_only_the_complete_p0_dependency_closure(self) -> None:
        self.assertEqual(set(self.locked), EXPECTED_DISTRIBUTIONS)

    def test_manifest_fingerprint_is_recomputable_from_exact_lock_pins(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        self.assertEqual(manifest["dependency_lock"], "requirements-p0.lock")
        self.assertEqual(
            manifest["dependency_fingerprint"],
            _dependency_fingerprint(self.locked),
        )

    def test_installed_dependency_fingerprint_uses_exact_declared_versions(self) -> None:
        declared_versions = {
            name: version for name, (version, _) in self.locked.items()
        }

        with mock.patch.object(
            metadata,
            "version",
            side_effect=lambda name: declared_versions[name],
        ):
            self.assertEqual(
                _installed_dependency_fingerprint(self.locked),
                _dependency_fingerprint(self.locked),
            )


if __name__ == "__main__":
    unittest.main()
