#!/bin/bash
# Build a macOS .app bundle for Research Taxonomy Library.
# Usage: ./build_app.sh
set -euo pipefail

APP_NAME="Research Taxonomy Library"
APP_DIR="${APP_NAME}.app"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Building ${APP_NAME}..."

# -- Ensure venv exists with dependencies --
if [ ! -d "${PROJECT_DIR}/venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "${PROJECT_DIR}/venv"
fi

echo "Installing dependencies..."
"${PROJECT_DIR}/venv/bin/pip" install -q -r "${PROJECT_DIR}/requirements.txt"

# -- Create .app bundle structure --
rm -rf "${PROJECT_DIR}/${APP_DIR}"
mkdir -p "${PROJECT_DIR}/${APP_DIR}/Contents/MacOS"
mkdir -p "${PROJECT_DIR}/${APP_DIR}/Contents/Resources"

# -- Launcher script --
cat > "${PROJECT_DIR}/${APP_DIR}/Contents/MacOS/launcher" << 'LAUNCHER'
#!/bin/bash
# Resolve the real project directory (not inside the .app bundle)
APP_PATH="$(cd "$(dirname "$0")/../../.." && pwd)"

# Activate venv
source "${APP_PATH}/venv/bin/activate"

# Run the desktop launcher
exec python "${APP_PATH}/desktop.py"
LAUNCHER

chmod +x "${PROJECT_DIR}/${APP_DIR}/Contents/MacOS/launcher"

# -- Info.plist --
cat > "${PROJECT_DIR}/${APP_DIR}/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>com.taxonomy.research-library</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

echo ""
echo "Done! Built: ${PROJECT_DIR}/${APP_DIR}"
echo ""
echo "To launch:  open \"${PROJECT_DIR}/${APP_DIR}\""
echo "To add to Dock: drag the .app to your Dock."
