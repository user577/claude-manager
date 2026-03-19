"""Horizontal preset bar widget — save, load, and delete named launch presets."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget


class PresetsBar(QWidget):
    """Compact bar with a combo box and Load / Save / Delete buttons.

    Signals
    -------
    load_requested(str)  — emitted with the selected preset name
    save_requested()     — emitted when the user clicks Save
    delete_requested(str) — emitted with the selected preset name
    """

    load_requested = Signal(str)
    save_requested = Signal()
    delete_requested = Signal(str)

    _PLACEHOLDER = "\u2014 Presets \u2014"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.combo = QComboBox()
        self.combo.setMinimumWidth(160)
        self.combo.addItem(self._PLACEHOLDER)
        row.addWidget(self.combo, 1)

        self.load_btn = QPushButton("Load")
        self.load_btn.setFixedWidth(56)
        self.load_btn.clicked.connect(self._on_load)
        row.addWidget(self.load_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.setFixedWidth(56)
        self.save_btn.clicked.connect(self._on_save)
        row.addWidget(self.save_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setFixedWidth(56)
        self.delete_btn.clicked.connect(self._on_delete)
        row.addWidget(self.delete_btn)

    # --- helpers ---

    def set_names(self, names: list[str]) -> None:
        """Repopulate the combo with the given preset names."""
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(self._PLACEHOLDER)
        for name in sorted(names):
            self.combo.addItem(name)
        self.combo.blockSignals(False)

    def selected_name(self) -> str | None:
        """Return the currently selected preset name, or None if placeholder."""
        text = self.combo.currentText()
        if text == self._PLACEHOLDER:
            return None
        return text

    # --- slots ---

    def _on_load(self) -> None:
        name = self.selected_name()
        if name:
            self.load_requested.emit(name)

    def _on_save(self) -> None:
        self.save_requested.emit()

    def _on_delete(self) -> None:
        name = self.selected_name()
        if name:
            self.delete_requested.emit(name)
