import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# isolate QSettings so tests never read/write real user settings
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="bwxtest-")
