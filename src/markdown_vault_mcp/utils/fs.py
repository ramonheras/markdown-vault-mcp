"""Filesystem traversal helpers."""

from __future__ import annotations

import sys
from typing import Any

# pathlib's Path.glob / Path.rglob do not recurse into symlinked
# subdirectories by default — the behavior was unspecified pre-3.13 and an
# explicit recurse_symlinks=False default in 3.13+. Pass recurse_symlinks=True
# on 3.13+ to enable symlink-farm vault layouts (issue #508). The kwarg does
# not exist on 3.11/3.12 where pathlib's symlink behavior is buggy and
# inconsistent; users with symlink farms on those versions need to upgrade.
#
# Warning: vault symlinks must not form cycles. A self-referential link
# (e.g. ``vault/loop -> vault/``) hangs the scan with no cycle detection.
GLOB_SYMLINK_KWARGS: dict[str, Any] = (
    {"recurse_symlinks": True} if sys.version_info >= (3, 13) else {}
)
