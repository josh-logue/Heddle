"""Launch WarpingWeft.  Usage:  python main.py [board.json]"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from warpingweft import error_log
from warpingweft.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("WarpingWeft")
    app.setStyle("Fusion")
    error_log.install()  # unexpected errors are logged and reported, not lost
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    window = MainWindow(path)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
