"""OS event collectors — auto-discovered by platform.

Each collector module defines a COLLECTORS list of (platform, class) tuples.
Supported platforms: "darwin", "win32", "all".
To add a new collector, just create a module and add COLLECTORS.
"""

import importlib
import logging
import pkgutil
import sys

from capture.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

# Registry: populated by _discover()
_registry: list[type[BaseCollector]] = []
_discovered = False


def _discover():
    """Scan collector modules for COLLECTORS declarations."""
    global _discovered
    if _discovered:
        return
    _discovered = True

    package = importlib.import_module("capture.collectors")
    for info in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
        if info.name.endswith(".base"):
            continue
        try:
            mod = importlib.import_module(info.name)
        except Exception:
            logger.debug("skipped module %s (import failed)", info.name)
            continue

        collectors_decl = getattr(mod, "COLLECTORS", None)
        if not collectors_decl:
            continue

        for platform, cls in collectors_decl:
            if platform == "all" or platform == sys.platform:
                _registry.append(cls)


def get_all_collectors() -> list[BaseCollector]:
    _discover()
    return [cls() for cls in _registry]
