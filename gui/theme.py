"""
theme.py — Dark theme palette and stylesheet for the Synthetic Organoid Generator GUI.
"""

from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtCore import Qt


# ── Colour tokens ────────────────────────────────────────────────────
BG_DEEP    = "#1a1a2e"   # main window background
BG_PANEL   = "#16213e"   # side panels
BG_WIDGET  = "#0f3460"   # input widgets, list items
BG_HOVER   = "#1a4a7a"   # hover state
ACCENT     = "#4ec9b0"   # teal — primary accent
ACCENT2    = "#56cfe1"   # lighter teal for highlights
WARNING    = "#f0a500"   # amber
DANGER     = "#e05252"   # red
SUCCESS    = "#6bcb77"   # green
TEXT       = "#d4d4d4"   # primary text
TEXT_DIM   = "#888899"   # secondary text / labels
TEXT_HEAD  = "#ffffff"   # heading text
BORDER     = "#2a2a4a"   # subtle borders
SEPARATOR  = "#2e2e4e"


STYLESHEET = f"""
/* ── Global ── */
QMainWindow, QDialog, QWidget {{
    background-color: {BG_DEEP};
    color: {TEXT};
    font-family: "Segoe UI", "Arial", sans-serif;
    font-size: 12px;
}}

/* ── Tab bar ── */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background: {BG_PANEL};
}}
QTabBar::tab {{
    background: {BG_DEEP};
    color: {TEXT_DIM};
    padding: 10px 24px;
    border: none;
    font-size: 13px;
    font-weight: bold;
    min-width: 140px;
}}
QTabBar::tab:selected {{
    background: {BG_PANEL};
    color: {ACCENT};
    border-bottom: 3px solid {ACCENT};
}}
QTabBar::tab:hover:!selected {{
    background: {BG_WIDGET};
    color: {TEXT};
}}

/* ── Splitter ── */
QSplitter::handle {{
    background: {BORDER};
    width: 2px;
    height: 2px;
}}

/* ── GroupBox ── */
QGroupBox {{
    color: {ACCENT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 14px;
    padding: 8px 6px 6px 6px;
    font-weight: bold;
    font-size: 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    left: 10px;
}}

/* ── Labels ── */
QLabel {{
    color: {TEXT};
}}
QLabel#dim {{
    color: {TEXT_DIM};
    font-size: 11px;
}}
QLabel#heading {{
    color: {TEXT_HEAD};
    font-size: 14px;
    font-weight: bold;
}}
QLabel#accent {{
    color: {ACCENT};
    font-weight: bold;
}}

/* ── Buttons ── */
QPushButton {{
    background-color: {BG_WIDGET};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 6px 14px;
    font-size: 12px;
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton:pressed {{
    background-color: {ACCENT};
    color: #000000;
}}
QPushButton:disabled {{
    background-color: {BG_DEEP};
    color: {TEXT_DIM};
    border-color: {BORDER};
}}
QPushButton#primary {{
    background-color: {ACCENT};
    color: #000000;
    font-weight: bold;
    font-size: 13px;
    padding: 8px 20px;
    border: none;
}}
QPushButton#primary:hover {{
    background-color: {ACCENT2};
}}
QPushButton#primary:disabled {{
    background-color: #2a5a52;
    color: #6a9a92;
}}
QPushButton#danger {{
    background-color: transparent;
    color: {DANGER};
    border-color: {DANGER};
}}
QPushButton#danger:hover {{
    background-color: {DANGER};
    color: white;
}}

/* ── Line edits / spin boxes ── */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {BG_WIDGET};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    padding-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {BG_WIDGET};
    color: {TEXT};
    selection-background-color: {BG_HOVER};
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: {BG_HOVER};
    border: none;
    width: 16px;
}}

/* ── Sliders ── */
QSlider::groove:horizontal {{
    height: 4px;
    background: {SEPARATOR};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -5px 0;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}

/* ── List widget ── */
QListWidget {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    outline: none;
}}
QListWidget::item {{
    padding: 8px 12px;
    border-bottom: 1px solid {SEPARATOR};
}}
QListWidget::item:selected {{
    background-color: {BG_HOVER};
    color: {ACCENT};
}}
QListWidget::item:hover:!selected {{
    background-color: {BG_WIDGET};
}}

/* ── Scroll bars ── */
QScrollBar:vertical {{
    background: {BG_PANEL};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}

QScrollBar:horizontal {{
    background: {BG_PANEL};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {ACCENT};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}

/* ── Progress bar ── */
QProgressBar {{
    background: {BG_WIDGET};
    border: 1px solid {BORDER};
    border-radius: 4px;
    text-align: center;
    color: {TEXT};
    height: 18px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {ACCENT}, stop:1 {ACCENT2});
    border-radius: 3px;
}}

/* ── Tool tips ── */
QToolTip {{
    background-color: {BG_WIDGET};
    color: {TEXT};
    border: 1px solid {ACCENT};
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 11px;
}}

/* ── Status bar ── */
QStatusBar {{
    background: {BG_DEEP};
    color: {TEXT_DIM};
    border-top: 1px solid {BORDER};
}}

/* ── Menu bar ── */
QMenuBar {{
    background: {BG_DEEP};
    color: {TEXT};
}}
QMenuBar::item:selected {{
    background: {BG_WIDGET};
}}
QMenu {{
    background: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
}}
QMenu::item:selected {{
    background: {BG_HOVER};
    color: {ACCENT};
}}

/* ── CheckBox / RadioButton ── */
QCheckBox, QRadioButton {{
    color: {TEXT};
    spacing: 8px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER};
    border-radius: 3px;
    background: {BG_WIDGET};
}}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

/* ── Separator line ── */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {BORDER};
}}
"""


def apply_theme(app):
    """Apply dark theme to a QApplication."""
    app.setStyle("Fusion")
    palette = QPalette()

    palette.setColor(QPalette.Window,          QColor(BG_DEEP))
    palette.setColor(QPalette.WindowText,      QColor(TEXT))
    palette.setColor(QPalette.Base,            QColor(BG_WIDGET))
    palette.setColor(QPalette.AlternateBase,   QColor(BG_PANEL))
    palette.setColor(QPalette.ToolTipBase,     QColor(BG_WIDGET))
    palette.setColor(QPalette.ToolTipText,     QColor(TEXT))
    palette.setColor(QPalette.Text,            QColor(TEXT))
    palette.setColor(QPalette.Button,          QColor(BG_WIDGET))
    palette.setColor(QPalette.ButtonText,      QColor(TEXT))
    palette.setColor(QPalette.BrightText,      QColor(ACCENT))
    palette.setColor(QPalette.Link,            QColor(ACCENT))
    palette.setColor(QPalette.Highlight,       QColor(ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor("#000000"))
    palette.setColor(QPalette.Disabled, QPalette.Text,       QColor(TEXT_DIM))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(TEXT_DIM))

    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
