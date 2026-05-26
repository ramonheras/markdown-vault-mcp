"""Filesystem traversal helpers."""

from __future__ import annotations

import sys
from typing import Any

# Python 3.13 changed Path.glob / Path.rglob to no longer follow symlinks by
# default, breaking symlink-farm vault layouts. Restore pre-3.13 behavior by
# passing recurse_symlinks=True on 3.13+; the kwarg does not exist on earlier
# versions, where symlinks were already followed.
#
# Warning: vault symlinks must not form cycles. A self-referential link
# (e.g. ``vault/loop -> vault/``) hangs the scan on all supported versions.
GLOB_SYMLINK_KWARGS: dict[str, Any] = (
    {"recurse_symlinks": True} if sys.version_info >= (3, 13) else {}
)
