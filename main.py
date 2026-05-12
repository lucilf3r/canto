#!/usr/bin/env python3
import sys
import os
from pathlib import Path

from PySide6.QtWidgets import QApplication

_BUNDLED_MODEL = Path(__file__).parent / 'models' / 'supertonic-3'


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Canto')

    from tts_engine import TTSEngine
    from window import MainWindow

    model_dir = _BUNDLED_MODEL if _BUNDLED_MODEL.exists() else None
    tts = TTSEngine(model_dir=model_dir)
    win = MainWindow(tts)
    win.show()

    if len(sys.argv) > 1:
        epub_path = sys.argv[1]
        if os.path.isfile(epub_path):
            win.load_epub(epub_path)
        else:
            print(f'Warning: file not found: {epub_path}', file=sys.stderr)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
