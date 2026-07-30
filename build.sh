#!/bin/bash
# Build File Renamer.app and a drag-install DMG.
#   chmod +x build.sh && ./build.sh
#
# A PyInstaller bundle runs on the macOS generation it was built on and
# newer — nothing older. For a Catalina-compatible build, run this script
# ON the Catalina machine with the python.org 3.9.13 installer; the pins
# in requirements-catalina.txt are the last releases that work there.
set -euo pipefail
cd "$(dirname "$0")"

APP="File Renamer"
VERSION="1.0.0"
BUNDLE_ID="com.killpidone.filerenamer"
PY="venv/bin/python"

MACOS_VER=$(sw_vers -productVersion)
case "$MACOS_VER" in
  10.*) REQS="requirements-catalina.txt"
        echo "==> Catalina build ($MACOS_VER) using $REQS"
        if ! python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 9) else 1)'; then
          echo "ERROR: on Catalina, install Python 3.9.13 from python.org"
          echo "       (found: $(python3 --version 2>&1))"
          exit 1
        fi
        BOOTSTRAP="python3" ;;
  *)    REQS="requirements.txt"
        echo "==> modern macOS build ($MACOS_VER) using $REQS"
        echo "    note: this .app will NOT run on Catalina — build there for that"
        # Homebrew python + python-tk, never the miniconda python3 on PATH.
        if [ -x /usr/local/opt/python@3.14/bin/python3 ]; then
          BOOTSTRAP="/usr/local/opt/python@3.14/bin/python3"
        elif [ -x /opt/homebrew/opt/python@3.14/bin/python3 ]; then
          BOOTSTRAP="/opt/homebrew/opt/python@3.14/bin/python3"
        else
          BOOTSTRAP="python3"
        fi ;;
esac

echo "==> venv + dependencies (via $BOOTSTRAP)"
# A venv built by a different Python is unusable — recreate it.
if [ -x "$PY" ]; then
  VENV_VER=$($PY -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo none)
  SYS_VER=$($BOOTSTRAP -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  if [ "$VENV_VER" != "$SYS_VER" ]; then
    echo "    recreating venv (was Python $VENV_VER, need $SYS_VER)"
    rm -rf venv
  fi
fi
[ -d venv ] || "$BOOTSTRAP" -m venv venv
$PY -m pip install --quiet --upgrade pip
$PY -m pip install --quiet -r "$REQS"
$PY -c 'import tkinter' || {
  echo "ERROR: this Python has no tkinter. On Homebrew: brew install python-tk@3.14"
  exit 1
}

echo "==> Python 3.9 / Catalina source compatibility"
$PY compat_check.py

echo "==> self-test (must pass before building)"
$PY selftest.py

echo "==> icon"
$PY assets/make_icon.py

# Stamp the build so the running app can say which one it is — the
# version string alone never changes between rebuilds.
echo "==> build stamp"
echo "BUILD = \"$(date '+%Y-%m-%d %H:%M')\"" > _build.py
cat _build.py

echo "==> PyInstaller"
rm -rf build dist
$PY -m PyInstaller --noconfirm --windowed --name "$APP" \
  --icon assets/icon.icns \
  --osx-bundle-identifier "$BUNDLE_ID" \
  --collect-all tkinterdnd2 \
  --hidden-import _build \
  file_renamer.py

PLIST="dist/$APP.app/Contents/Info.plist"
echo "==> Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PLIST" 2>/dev/null || \
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string '$VERSION'" "$PLIST"
# 10.15 is the oldest macOS this app is built and tested against.
/usr/libexec/PlistBuddy -c "Set :LSMinimumSystemVersion 10.15" "$PLIST" 2>/dev/null || \
/usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string '10.15'" "$PLIST"
# No NSRequiresAquaSystemAppearance — the app follows the system
# Light/Dark setting, which is the whole point of the aqua ttk theme.

echo "==> headless launch check (no window is shown)"
"dist/$APP.app/Contents/MacOS/$APP" --version

echo "==> portability (no Homebrew paths may leak into the bundle)"
LEAKS=$(find "dist/$APP.app" \( -name '*.so' -o -name '*.dylib' -o -type f -perm -u+x \) -print0 2>/dev/null \
  | xargs -0 otool -L 2>/dev/null \
  | grep -E '^\s+(/usr/local|/opt/homebrew)' | sort -u || true)
if [ -n "$LEAKS" ]; then
  echo "WARNING: bundle references paths that a stock Mac will not have:"
  echo "$LEAKS"
else
  echo "no /usr/local or /opt/homebrew references — safe on a stock Mac"
fi

echo "==> DMG"
mkdir -p release
DMG="release/File-Renamer-$VERSION.dmg"
rm -f "$DMG"
STAGE=$(mktemp -d)
cp -R "dist/$APP.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp README.md CHANGELOG.md LICENSE.txt "$STAGE/" 2>/dev/null || true
hdiutil create -volname "$APP" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

echo "==> verify DMG"
hdiutil verify "$DMG" >/dev/null && echo "DMG verified OK"
ls -lh "$DMG"

echo
echo "Done."
echo "  App:       dist/$APP.app"
echo "  Installer: $DMG"
echo "Nothing was launched — open the DMG yourself when you want to install."
