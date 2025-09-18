#!/usr/bin/env python3
"""
YouTube OSINT Reconnaissance Tool - Main Entry Point
A modular YouTube OSINT tool for intelligence gathering and analysis.
"""

import sys
import os
from PyQt5.QtWidgets import QApplication

# Add the modules directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'modules'))

# Import the main window from the GUI module
from gui import MainWindow

def main():
    """Main entry point for the YouTube OSINT Tool."""
    app = QApplication(sys.argv)
    mw = MainWindow()
    mw.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
