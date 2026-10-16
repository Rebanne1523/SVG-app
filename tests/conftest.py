import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def win(qapp):
    from PySide6.QtCore import QPointF
    from vectorflow.mainwindow import MainWindow
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    qapp.processEvents()
    w.canvas.set_zoom(1.0, (0, 0))
    w.canvas.origin = QPointF(50, 50)
    yield w
    w.doc.modified = False
    w.close()
