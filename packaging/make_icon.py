"""Write the application icon as a PNG: python make_icon.py out.png"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from vectorflow.icons import app_icon  # noqa: E402

app = QGuiApplication([])
out = sys.argv[1] if len(sys.argv) > 1 else "vectorflow.png"
if not app_icon().pixmap(256, 256).save(out):
    sys.exit("could not write " + out)
