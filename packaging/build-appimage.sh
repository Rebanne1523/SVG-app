#!/usr/bin/env bash
# Build VectorFlow-x86_64.AppImage. Needs: python3 (with venv + pip), curl.
# Used by the GitHub Action, but you can run it locally too:  ./packaging/build-appimage.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
BUILD="$ROOT/build"
APPDIR="$BUILD/AppDir"
OUT="$BUILD/VectorFlow-x86_64.AppImage"

rm -rf "$APPDIR" "$BUILD/dist" "$BUILD/work"
mkdir -p "$BUILD"

echo ">> Creating build environment"
python3 -m venv "$BUILD/venv"
# shellcheck disable=SC1091
. "$BUILD/venv/bin/activate"
pip install --upgrade pip wheel
pip install -r requirements.txt pyinstaller

echo ">> Icon"
python packaging/make_icon.py "$BUILD/vectorflow.png"

echo ">> Freezing with PyInstaller"
pyinstaller --noconfirm --clean --name vectorflow --windowed \
    --paths "$ROOT" \
    --distpath "$BUILD/dist" --workpath "$BUILD/work" --specpath "$BUILD" \
    --exclude-module pymupdf.layout --exclude-module onnxruntime --exclude-module tkinter --exclude-module matplotlib --exclude-module numpy.tests \
    --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets \
    --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml \
    packaging/launcher.py

echo ">> Assembling AppDir"
mkdir -p "$APPDIR/usr/bin"
cp -r "$BUILD/dist/vectorflow" "$APPDIR/usr/bin/vectorflow"
cp packaging/vectorflow.desktop "$APPDIR/vectorflow.desktop"
cp "$BUILD/vectorflow.png" "$APPDIR/vectorflow.png"
ln -sf vectorflow.png "$APPDIR/.DirIcon"
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/vectorflow/vectorflow" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

echo ">> Packing AppImage"
TOOL="$BUILD/appimagetool-x86_64.AppImage"
if [ ! -x "$TOOL" ]; then
    curl -fL -o "$TOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$TOOL"
fi
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUT"
echo ">> Done: $OUT"
