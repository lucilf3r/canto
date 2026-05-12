#!/usr/bin/env bash
set -e

echo "==> Installing Python dependencies..."
pip install -r requirements.txt

echo "==> Downloading Supertonic model (~305 MB, first run only)..."
python -c "
from supertonic import TTS
import pathlib
TTS(auto_download=True, model_dir=pathlib.Path('models/supertonic-3'))
"

echo "==> Done. Run with: python main.py [book.epub]"
