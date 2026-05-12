#!/usr/bin/env python3
import sys
import os
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

MODEL_DIR = Path(__file__).parent / 'models'
MODEL_PATH = MODEL_DIR / 'kokoro-v0_19.onnx'
VOICES_PATH = MODEL_DIR / 'voices.bin'


def _check_models() -> list[str]:
    missing = []
    if not MODEL_PATH.exists():
        missing.append('models/kokoro-v0_19.onnx')
    if not VOICES_PATH.exists():
        missing.append('models/voices.bin')
    return missing


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Canto')

    missing = _check_models()
    if missing:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle('Missing model files')
        msg.setText(
            'Kokoro model files are missing:\n\n'
            + '\n'.join(f'  - {f}' for f in missing)
            + '\n\nRun setup first:\n\n    bash setup.sh'
        )
        msg.exec()
        sys.exit(1)

    from tts_engine import TTSEngine
    from window import MainWindow

    tts = TTSEngine(str(MODEL_PATH), str(VOICES_PATH))
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
