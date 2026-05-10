#!/usr/bin/env bash
set -e

echo "==> Installing Python dependencies..."
pip install -r requirements.txt

echo "==> Downloading Kokoro model files..."
mkdir -p models

if [ ! -f "models/kokoro-v0_19.onnx" ]; then
    wget -O models/kokoro-v0_19.onnx \
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx"
else
    echo "    kokoro-v0_19.onnx already present, skipping."
fi

if [ ! -f "models/voices.bin" ]; then
    wget -O models/voices.bin \
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin"
else
    echo "    voices.bin already present, skipping."
fi

echo "==> Done. Run with: python main.py [book.epub]"
