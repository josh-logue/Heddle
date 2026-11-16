"""Launch Heddle.  Usage:  python main.py [board.json]"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from heddle import error_log
from heddle.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Heddle")
    app.setStyle("Fusion")
    error_log.install()  # unexpected errors are logged and reported, not lost
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    window = MainWindow(path)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
