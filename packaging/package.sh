#!/usr/bin/env bash
#
# Wrap a finished PyInstaller build into the thing a person downloads.
#
#   packaging/package.sh <version> <target>
#
# <target> is one of macOS-arm64, macOS-x86_64, Windows-x64, Linux-x86_64.
# Reads dist/ (what PyInstaller wrote), writes out/. File names carry no
# version, so releases/latest/download/<name> is a permanent link (the
# README's download buttons); the version is in the app and the DMG title.
#
# One script rather than three near-identical blocks of CI YAML, so the
# same command can be run by hand while debugging a platform.

set -euo pipefail

VERSION="${1:?usage: package.sh <version> <target>}"
TARGET="${2:?usage: package.sh <version> <target>}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$ROOT/dist"
OUT="$ROOT/out"
mkdir -p "$OUT"

case "$TARGET" in
  macOS-*)
    APP="$DIST/Ruyso.app"
    [ -d "$APP" ] || { echo "no $APP -- run pyinstaller first" >&2; exit 1; }

    # An arm64 binary must carry *a* signature to run at all: this is the
    # loader, not Gatekeeper, and "unsigned" is not a runnable state.
    # Ad-hoc ("-") satisfies it. It does not stop the quarantine warning
    # on a downloaded app -- only notarisation does that.
    echo "ad-hoc signing $APP"
    codesign --force --deep --sign - "$APP"
    codesign --verify --deep --strict --verbose=2 "$APP"

    DMG="$OUT/Ruyso-$TARGET.dmg"
    rm -f "$DMG"
    STAGE="$(mktemp -d)"
    cp -R "$APP" "$STAGE/"
    ln -s /Applications "$STAGE/Applications"   # the drag-here affordance
    hdiutil create -volname "Ruyso $VERSION" -srcfolder "$STAGE" \
        -ov -format UDZO "$DMG"
    rm -rf "$STAGE"
    echo "wrote $DMG"
    ;;

  Windows-x64)
    [ -d "$DIST/ruyso" ] || { echo "no $DIST/ruyso" >&2; exit 1; }
    # Inno Setup is not guaranteed on the runner image; CI installs it.
    iscc "//DAppVersion=$VERSION" "$(cygpath -w "$ROOT/packaging/ruyso.iss" 2>/dev/null || echo "$ROOT/packaging/ruyso.iss")"
    echo "wrote $OUT/Ruyso-Windows-x64-Setup.exe"
    ;;

  Linux-x86_64)
    [ -d "$DIST/ruyso" ] || { echo "no $DIST/ruyso" >&2; exit 1; }
    APPDIR="$(mktemp -d)/Ruyso.AppDir"
    mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
    cp -R "$DIST/ruyso/." "$APPDIR/usr/bin/"

    cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/ruyso" "$@"
APPRUN
    chmod +x "$APPDIR/AppRun"

    cat > "$APPDIR/ruyso.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Ruyso
Comment=Visual data science pipeline builder
Exec=ruyso
Icon=ruyso
Categories=Science;Education;
Terminal=false
DESKTOP

    if [ -f "$ROOT/packaging/icons/icon-256.png" ]; then
      cp "$ROOT/packaging/icons/icon-256.png" "$APPDIR/ruyso.png"
      cp "$ROOT/packaging/icons/icon-256.png" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps/ruyso.png"
    fi

    # --appimage-extract-and-run because CI runners have no FUSE.
    ARCH=x86_64 appimagetool --appimage-extract-and-run \
        "$APPDIR" "$OUT/Ruyso-Linux-x86_64.AppImage"
    echo "wrote $OUT/Ruyso-Linux-x86_64.AppImage"
    ;;

  *)
    echo "unknown target: $TARGET" >&2
    exit 2
    ;;
esac
