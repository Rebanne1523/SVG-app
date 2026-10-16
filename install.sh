#!/usr/bin/env bash
# VectorFlow installer for CachyOS / Arch / any Linux (user-level, no sudo needed).
#
#   curl -fsSL https://raw.githubusercontent.com/Rebanne1523/SVG-app/main/install.sh | bash
#   ./install.sh /path/to/VectorFlow-x86_64.AppImage   # install a file you already have
#   ./install.sh --uninstall
set -euo pipefail

REPO="Rebanne1523/SVG-app"
BIN_DIR="$HOME/.local/bin"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
TARGET="$BIN_DIR/VectorFlow.AppImage"

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$TARGET" "$APP_DIR/vectorflow.desktop" "$ICON_DIR/vectorflow.png" "$BIN_DIR/vectorflow"
    command -v update-desktop-database >/dev/null && update-desktop-database "$APP_DIR" || true
    echo "VectorFlow removed."
    exit 0
fi

mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR"

if [ -n "${1:-}" ] && [ -f "$1" ]; then
    echo ">> Installing $1"
    cp "$1" "$TARGET"
else
    URL="https://github.com/$REPO/releases/latest/download/VectorFlow-x86_64.AppImage"
    echo ">> Downloading $URL"
    curl -fL --progress-bar "$URL" -o "$TARGET.part"
    mv "$TARGET.part" "$TARGET"
fi
chmod +x "$TARGET"
ln -sf "$TARGET" "$BIN_DIR/vectorflow"

# icon (taken from inside the AppImage)
TMP="$(mktemp -d)"
( cd "$TMP" && "$TARGET" --appimage-extract vectorflow.png >/dev/null 2>&1 && \
    cp squashfs-root/vectorflow.png "$ICON_DIR/vectorflow.png" ) || echo "(icon not extracted, continuing)"
rm -rf "$TMP"

cat > "$APP_DIR/vectorflow.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=VectorFlow
GenericName=Vector editor
Comment=Vector editor with easy layers, smart bucket and measurement lines
Exec=$TARGET %F
Icon=vectorflow
Terminal=false
Categories=Graphics;VectorGraphics;2DGraphics;
MimeType=image/svg+xml;image/svg+xml-compressed;
StartupWMClass=vectorflow
DESKTOP
command -v update-desktop-database >/dev/null && update-desktop-database "$APP_DIR" || true

echo
echo "VectorFlow installed. Find it in your application menu, or run:  vectorflow"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "(add $BIN_DIR to your PATH to use the 'vectorflow' command)";; esac

# AppImages need FUSE 2
if ! ldconfig -p 2>/dev/null | grep -q 'libfuse.so.2'; then
    echo
    echo "NOTE: AppImages need FUSE 2. On CachyOS/Arch install it with:  sudo pacman -S fuse2"
    echo "      (or run VectorFlow with:  VectorFlow.AppImage --appimage-extract-and-run)"
fi
