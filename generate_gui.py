"""
generate_gui.py — Entry point for the Synthetic Organoid Generator GUI.

Usage:
    python generate_gui.py

Packaging (PyInstaller):
    pyinstaller --onefile --windowed --name "OrganoidGenerator" ^
        --add-data "presets;presets" --add-data "core;core" ^
        generate_gui.py
"""

import sys
import os
from pathlib import Path

# Make sure core/ is importable whether running as script or frozen exe
if getattr(sys, "frozen", False):
    # PyInstaller frozen exe — base path is sys._MEIPASS
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent

sys.path.insert(0, str(BASE_DIR))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from gui.theme import apply_theme
from gui.main_window import MainWindow


def main():
    # High-DPI support
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps,   True)

    app = QApplication(sys.argv)
    app.setApplicationName("Synthetic Organoid Generator")
    app.setOrganizationName("DigitalSreeni")

    # Default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Apply dark theme
    apply_theme(app)

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
