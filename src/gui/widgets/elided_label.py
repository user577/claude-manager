from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import QLabel


class ElidedLabel(QLabel):
    """A single-line label that ellipsizes instead of clipping.

    Plain QLabel reports its full text width as its size hint, so a long repo
    name or commit subject forces its whole row wider than the window and
    pushes the trailing buttons off-screen. This one asks for almost nothing
    and shrinks with an ellipsis instead.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = text
        self.setMinimumWidth(20)

    def setText(self, text: str):  # noqa: N802 (Qt naming)
        self._full = text
        super().setText(text)
        self.updateGeometry()
        self.update()

    def sizeHint(self):  # noqa: N802 (Qt naming)
        # Pad the height: painting into a rect of exactly the font height clips
        # descenders, which silently ate the underscores in repo names.
        hint = super().sizeHint()
        hint.setHeight(QFontMetrics(self.font()).height() + 3)
        return hint

    def minimumSizeHint(self):  # noqa: N802 (Qt naming)
        return QSize(20, self.sizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(self._full, Qt.ElideRight, self.width())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.rect(), int(self.alignment()), elided)
        painter.end()
