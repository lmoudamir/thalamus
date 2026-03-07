#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
THALAMUS_DIR="$(dirname "$SCRIPT_DIR")"
APP_NAME="Thalamus"
APP_DIR="$SCRIPT_DIR/dist/${APP_NAME}.app"

echo "========================================="
echo "  Thalamus macOS .app Builder (Swift)"
echo "========================================="

# 1. Generate icon if needed
echo "🎨 Generating icon..."
mkdir -p "$SCRIPT_DIR/assets"
if [ ! -f "$SCRIPT_DIR/assets/icon.icns" ]; then
  python3 "$SCRIPT_DIR/generate_icon.py"
fi
echo "✅ Icon ready"

# 2. Compile Swift
echo "🔨 Compiling Swift..."
swiftc -O -o "$SCRIPT_DIR/thalamus_bin" \
  -framework Cocoa -framework WebKit \
  "$SCRIPT_DIR/ThalamusApp.swift"
echo "✅ Compiled"

# 3. Clean & create .app bundle
rm -rf "$APP_DIR"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"

mkdir -p "$MACOS" "$RESOURCES"

# 4. Info.plist
cat > "$CONTENTS/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Thalamus</string>
    <key>CFBundleDisplayName</key><string>Thalamus</string>
    <key>CFBundleIdentifier</key><string>com.thalamus.launcher</string>
    <key>CFBundleVersion</key><string>1.0.0</string>
    <key>CFBundleShortVersionString</key><string>1.0.0</string>
    <key>CFBundleExecutable</key><string>thalamus</string>
    <key>CFBundleIconFile</key><string>icon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>LSMinimumSystemVersion</key><string>10.15</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# 5. Copy binary
mv "$SCRIPT_DIR/thalamus_bin" "$MACOS/thalamus"

# 6. Copy icon
cp "$SCRIPT_DIR/assets/icon.icns" "$RESOURCES/icon.icns" 2>/dev/null || true

# 7. Copy UI files
cp "$SCRIPT_DIR/launcher_ui.py" "$RESOURCES/"
cp "$SCRIPT_DIR/index.html" "$RESOURCES/"

# 8. Write path config (points to real thalamus-py dir with .venv)
echo "$THALAMUS_DIR" > "$RESOURCES/thalamus_path.conf"

echo ""
echo "========================================="
echo "  ✅ Build Complete!"
echo ""
echo "  📍 $APP_DIR"
echo "  📂 thalamus-py: $THALAMUS_DIR"
echo ""
echo "  ▶ Run:     open \"$APP_DIR\""
echo "  📂 Install: drag to /Applications"
echo "========================================="
