#!/usr/bin/env python3
"""Confirm the sources stay Python 3.9 compatible (Catalina builds).

Catalina's newest practical Python is 3.9, so every source file must
parse with 3.9 syntax. Runtime type hints all rely on `from __future__
import annotations`, which this also verifies is present.

Run on every build — it costs nothing and it is the only thing standing
between a 3.13-only idiom and a build that fails on the Catalina machine.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SOURCES = ("aliasx.py", "renamer.py", "database.py", "prefs.py",
           "selftest.py", "compat_check.py", "assets/make_icon.py")


def main() -> int:
    ok = True
    here = Path(__file__).resolve().parent
    for name in SOURCES:
        path = here / name
        if not path.exists():
            print("FAIL %s: missing" % name)
            ok = False
            continue
        src = path.read_text(encoding="utf-8")
        try:
            ast.parse(src, filename=name, feature_version=(3, 9))
        except SyntaxError as err:
            print("FAIL %s: not Python 3.9 syntax: %s" % (name, err))
            ok = False
            continue
        if "from __future__ import annotations" not in src:
            print("FAIL %s: missing 'from __future__ import annotations' "
                  "(needed for 3.9 type hints)" % name)
            ok = False
    print("Python 3.9 (Catalina) compatibility OK" if ok
          else "Catalina compatibility check FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
