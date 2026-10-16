"""A number box that is quick to type into: click selects everything, "." and "," both work
as the decimal mark (numpad included) and no trailing zeros are kept."""
from __future__ import annotations

from PySide6.QtCore import QLocale, Qt, QTimer
from PySide6.QtWidgets import QDoubleSpinBox


class NumField(QDoubleSpinBox):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.setLocale(QLocale(QLocale.C))
        self.setKeyboardTracking(False)
        self.setGroupSeparatorShown(False)

    def textFromValue(self, v):
        t = f"{v:.{self.decimals()}f}"
        if "." in t:
            t = t.rstrip("0").rstrip(".")
        return t or "0"

    def focusInEvent(self, e):
        super().focusInEvent(e)
        if e.reason() in (Qt.MouseFocusReason, Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason):
            QTimer.singleShot(0, self.selectAll)

    def keyPressEvent(self, e):
        if e.text() in (",", ".") or e.key() in (Qt.Key_Comma, Qt.Key_Period):
            self.lineEdit().insert(".")
            return
        super().keyPressEvent(e)
