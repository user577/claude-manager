DARK_THEME = """
QMainWindow, QDialog {
    background-color: #1e1e1e;
    color: #cccccc;
}
QWidget {
    background-color: #1e1e1e;
    color: #cccccc;
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #474747;
    border-radius: 4px;
    background: #1e1e1e;
}
QTabBar::tab {
    background: #3c3c3c;
    color: #cccccc;
    padding: 8px 20px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #474747;
    color: #007acc;
}
QTabBar::tab:hover {
    background: #555555;
}
QPushButton {
    background-color: #474747;
    color: #cccccc;
    border: 1px solid #555555;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #555555;
    border-color: #007acc;
}
QPushButton:pressed {
    background-color: #3c3c3c;
}
QPushButton:disabled {
    background-color: #3c3c3c;
    color: #6e6e6e;
    border-color: #474747;
}
QPushButton#launchBtn {
    background-color: #007acc;
    color: #ffffff;
    font-size: 15px;
    padding: 12px;
    border: none;
}
QPushButton#launchBtn:hover {
    background-color: #1a8ad4;
}
QPushButton#commitBtn {
    background-color: #4ec963;
    color: #1e1e1e;
    border: none;
}
QPushButton#commitBtn:hover {
    background-color: #6dd680;
}
QPushButton#pushBtn {
    background-color: #e8a838;
    color: #1e1e1e;
    border: none;
}
QPushButton#pushBtn:hover {
    background-color: #eebb5e;
}
QPushButton#syncBtn {
    background-color: #3dc9b0;
    color: #1e1e1e;
    border: none;
}
QPushButton#syncBtn:hover {
    background-color: #5ed6c2;
}
QLineEdit {
    background-color: #3c3c3c;
    color: #cccccc;
    border: 1px solid #474747;
    border-radius: 4px;
    padding: 6px 10px;
    selection-background-color: #007acc;
}
QLineEdit:focus {
    border-color: #007acc;
}
QSpinBox {
    background-color: #3c3c3c;
    color: #cccccc;
    border: 1px solid #474747;
    border-radius: 4px;
    padding: 4px 8px;
}
QComboBox {
    background-color: #3c3c3c;
    color: #cccccc;
    border: 1px solid #474747;
    border-radius: 4px;
    padding: 4px 8px;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #3c3c3c;
    color: #cccccc;
    selection-background-color: #474747;
    border: 1px solid #555555;
}
QCheckBox {
    spacing: 8px;
    color: #cccccc;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #474747;
    border-radius: 3px;
    background: #3c3c3c;
}
QCheckBox::indicator:checked {
    background: #007acc;
    border-color: #007acc;
}
QTextEdit, QPlainTextEdit {
    background-color: #252526;
    color: #9e9e9e;
    border: 1px solid #474747;
    border-radius: 4px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
}
QScrollBar:vertical {
    background: #252526;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #474747;
    border-radius: 5px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: #252526;
    height: 10px;
    border: none;
}
QScrollBar::handle:horizontal {
    background: #474747;
    border-radius: 5px;
    min-width: 20px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QGroupBox {
    border: 1px solid #474747;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
    color: #007acc;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
/* Repo-card buttons. These live here rather than in per-widget setStyleSheet
   calls because the card list is built ~116 deep: four setStyleSheet calls per
   card cost seconds of style recalculation at startup. */
QPushButton#cardLaunchBtn {
    background: #474747;
    color: #cccccc;
    border: none;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}
QPushButton#cardLaunchBtn:hover {
    background: #555555;
}
QPushButton#cardAutoBtn, QPushButton#cardHeavyBtn, QPushButton#cardTeamBtn {
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: bold;
}
QPushButton#cardAutoBtn { background: #8b3a3a; }
QPushButton#cardAutoBtn:hover { background: #a84545; }
QPushButton#cardHeavyBtn { background: #6e40c9; }
QPushButton#cardHeavyBtn:hover { background: #8b5cf6; }
QPushButton#cardTeamBtn { background: #1f6f8b; }
QPushButton#cardTeamBtn:hover { background: #2e8cab; }
QLabel#cardName {
    font-weight: bold;
    font-size: 13px;
}
QLabel#cardDetail {
    font-size: 11px;
    color: #9e9e9e;
}
QLabel#cardCommit {
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
    color: #6e6e6e;
}
QLabel#sectionHeader {
    color: #007acc;
    font-size: 14px;
    font-weight: bold;
}
"""

# Status colors
COLOR_CLEAN = "#4ec963"
COLOR_DIRTY = "#e8a838"
COLOR_ERROR = "#f44747"
COLOR_UNKNOWN = "#6e6e6e"
COLOR_AHEAD = "#007acc"
COLOR_BEHIND = "#9c6acd"
