#!/bin/bash
# Build ExCoModel.app (macOS). Run from repo root. Requires: curl, python3.14.
set -euo pipefail

BLENDER_VERSION=5.2.1
BLENDER_DMG="blender-${BLENDER_VERSION}-macos-arm64.dmg"
BLENDER_URL="https://download.blender.org/release/Blender5.2/${BLENDER_DMG}"
BUILD=.build-app
VENV="$BUILD/venv"

rm -rf "$BUILD" dist/ExCoModel.app
mkdir -p "$BUILD"

# 1. build venv with app deps
python3.14 -m venv "$VENV"
"$VENV/bin/pip" install --quiet ./kernel ./orchestrator -r app/requirements-app.txt

# 2. fetch portable Blender
if [ ! -f "$BUILD/$BLENDER_DMG" ]; then
  curl -L "$BLENDER_URL" -o "$BUILD/$BLENDER_DMG"
fi
hdiutil attach -nobrowse -mountpoint "$BUILD/mnt" "$BUILD/$BLENDER_DMG"
mkdir -p "$BUILD/blender"
cp -R "$BUILD/mnt/Blender.app" "$BUILD/blender/Blender.app"
hdiutil detach "$BUILD/mnt"

# 3. pyinstaller onedir .app
"$VENV/bin/pyinstaller" --noconfirm --clean --onedir --windowed \
  --name ExCoModel \
  --add-data "orchestrator/orchestrator/static:orchestrator/static" \
  app/main.py

# 4. drop Blender where find_blender() looks: Contents/MacOS/blender/Blender.app
mkdir -p dist/ExCoModel.app/Contents/MacOS/blender
cp -R "$BUILD/blender/Blender.app" dist/ExCoModel.app/Contents/MacOS/blender/Blender.app

# 5. third-party notices
cp app/THIRD_PARTY_NOTICES.md dist/ExCoModel.app/Contents/MacOS/
# Blender <= 4.x ships Resources/LICENSE; 5.x ships text/license/license.md
BLENDER_LICENSE="$BUILD/blender/Blender.app/Contents/Resources/LICENSE"
if [ ! -f "$BLENDER_LICENSE" ]; then
  BLENDER_LICENSE="$BUILD/blender/Blender.app/Contents/Resources/text/license/license.md"
fi
if [ -f "$BLENDER_LICENSE" ]; then
  cp "$BLENDER_LICENSE" dist/ExCoModel.app/Contents/MacOS/BLENDER-LICENSE.txt
fi

echo "built: dist/ExCoModel.app"
