import sys
from unittest.mock import MagicMock

# Block langsmith from crashing pytest on this Python/pydantic version
for mod in ["langsmith", "langsmith.schemas", "langsmith.utils", "langsmith.pytest_plugin"]:
    sys.modules.setdefault(mod, MagicMock())
