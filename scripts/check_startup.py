"""CPU startup and frozen-source integrity smoke check; no model calls."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from metric_review.core import Store
from tempfile import TemporaryDirectory
with TemporaryDirectory() as temporary:
    store=Store(ROOT/"data", Path(temporary)/"startup.sqlite")
    try:
        store._load()
    finally:
        store.close()
print("CPU startup and source integrity passed")
