import os
import sys
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp(prefix="wsne-test-")
os.environ.update(DATA_DIR=tmp, INBOX_DIR=str(Path(tmp) / "inbox"), ADMIN_PASSWORD="test-pass",
                  DISABLE_BACKGROUND="1", LANGUAGETOOL_URL="", DATABASE_URL=f"sqlite:///{tmp}/hub.db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
