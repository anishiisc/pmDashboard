#!/usr/bin/env python
"""Test runner that fixes the pydantic-v1 / Python-3.12 incompatibility."""
import sys

# Fix pydantic v1's ForwardRef._evaluate() call for Python 3.12+
# (Python 3.12 made `recursive_guard` keyword-only, pydantic v1 passes it positionally)
if sys.version_info >= (3, 12):
    from typing import ForwardRef, cast, Any

    def _patched_evaluate(type_: ForwardRef, globalns: Any, localns: Any) -> Any:
        try:
            return type_._evaluate(globalns, localns, frozenset(), recursive_guard=frozenset())
        except TypeError:
            return type_._evaluate(globalns, localns, frozenset())

    import pydantic.v1.typing as _pv1t
    _pv1t.evaluate_forwardref = _patched_evaluate  # type: ignore

import pytest  # noqa: E402

if __name__ == "__main__":
    sys.exit(pytest.main(sys.argv[1:]))
