import os
import sys
from pathlib import Path

# business-rules.py требует ключ MISTRAL уже на этапе импорта модуля —
# в тестах реальный ключ не нужен, т.к. сам вызов LLM мокается.
os.environ.setdefault("MISTRAL", "test-mistral-key")

WEBAPP_DIR = Path(__file__).resolve().parent.parent
if str(WEBAPP_DIR) not in sys.path:
    sys.path.insert(0, str(WEBAPP_DIR))
