DARK_THEME = """
QMainWindow, QDialog {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #45475a;
    border-radius: 4px;
    background: #1e1e2e;
}
QTabBar::tab {
    background: #313244;
    color: #cdd6f4;
    padding: 8px 20px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #45475a;
    color: #cba6f7;
}
QTabBar::tab:hover {
    background: #585b70;
}
QPushButton {
    background-color: #45475a;
    color: #cdd6f4;
    border: 1px solid #585b70;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #585b70;
    border-color: #cba6f7;
}
QPushButton:pressed {
    background-color: #313244;
}
QPushButton:disabled {
    background-color: #313244;
    color: #585b70;
    border-color: #45475a;
}
QPushButton#launchBtn {
    background-color: #89b4fa;
    color: #1e1e2e;
    font-size: 15px;
    padding: 12px;
    border: none;
}
QPushButton#launchBtn:hover {
    background-color: #b4d0fb;
}
QPushButton#commitBtn {
    background-color: #a6e3a1;
    color: #1e1e2e;
    border: none;
}
QPushButton#commitBtn:hover {
    background-color: #c6f0c2;
}
QPushButton#pushBtn {
    background-color: #f9e2af;
    color: #1e1e2e;
    border: none;
}
QPushButton#pushBtn:hover {
    background-color: #fbecc8;
}
QPushButton#syncBtn {
    background-color: #89dceb;
    color: #1e1e2e;
    border: none;
}
QPushButton#syncBtn:hover {
    background-color: #b0e8f2;
}
QLineEdit {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 6px 10px;
    selection-background-color: #cba6f7;
}
QLineEdit:focus {
    border-color: #cba6f7;
}
QSpinBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
}
QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    selection-background-color: #45475a;
    border: 1px solid #585b70;
}
QCheckBox {
    spacing: 8px;
    color: #cdd6f4;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #45475a;
    border-radius: 3px;
    background: #313244;
}
QCheckBox::indicator:checked {
    background: #cba6f7;
    border-color: #cba6f7;
}
QTextEdit, QPlainTextEdit {
    background-color: #181825;
    color: #a6adc8;
    border: 1px solid #45475a;
    border-radius: 4px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
}
QScrollBar:vertical {
    background: #181825;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 5px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: #181825;
    height: 10px;
    border: none;
}
QScrollBar::handle:horizontal {
    background: #45475a;
    border-radius: 5px;
    min-width: 20px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QGroupBox {
    border: 1px solid #45475a;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
    color: #cba6f7;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QLabel#sectionHeader {
    color: #cba6f7;
    font-size: 14px;
    font-weight: bold;
}
"""

# Status colors
COLOR_CLEAN = "#a6e3a1"
COLOR_DIRTY = "#f9e2af"
COLOR_ERROR = "#f38ba8"
COLOR_UNKNOWN = "#585b70"
COLOR_AHEAD = "#89b4fa"
