#!/bin/bash
# Build a macOS .app bundle for Research Taxonomy Library.
# Compiles a native launcher that exec's into Python with full Cocoa/GUI access.
# The .app runs from source — code changes take effect on next launch.
# Usage: ./build_app.sh
set -euo pipefail

APP_NAME="Research Taxonomy Library"
APP_DIR="${APP_NAME}.app"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION=$(python3 -c "import re; print(re.search(r'APP_VERSION\s*=\s*\"(.+?)\"', open('config.py').read()).group(1))" 2>/dev/null || echo "1.0.0")

echo "Building ${APP_NAME} v${VERSION}..."

# -- Ensure venv exists with dependencies --
if [ ! -d "${PROJECT_DIR}/venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "${PROJECT_DIR}/venv"
fi

echo "Installing dependencies..."
"${PROJECT_DIR}/venv/bin/pip" install -q -r "${PROJECT_DIR}/requirements.txt"

# -- Ensure logs dir exists --
mkdir -p "${PROJECT_DIR}/logs"

# -- Build .app directory structure --
rm -rf "${PROJECT_DIR}/${APP_DIR}"
mkdir -p "${PROJECT_DIR}/${APP_DIR}/Contents/MacOS"
mkdir -p "${PROJECT_DIR}/${APP_DIR}/Contents/Resources"

# -- Compile native launcher --
# A Mach-O binary is required for macOS to recognize the .app bundle.
# exec() replaces the launcher with Python, giving pywebview full GUI access.
CURRENT_PATH="$PATH"
LAUNCHER_C=$(mktemp /tmp/launcher_XXXXXX.c)
cat > "${LAUNCHER_C}" << CSOURCE
#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    setenv("PATH", "${CURRENT_PATH}", 1);
    chdir("${PROJECT_DIR}");

    /* Redirect stdout/stderr to log file */
    freopen("${PROJECT_DIR}/logs/desktop.log", "a", stdout);
    freopen("${PROJECT_DIR}/logs/desktop.log", "a", stderr);

    /* exec replaces this process with Python — pywebview gets full GUI context */
    execl("${PROJECT_DIR}/venv/bin/python3", "python3",
          "${PROJECT_DIR}/desktop.py", (char *)NULL);

    /* Only reached if exec fails */
    perror("exec failed");
    return 1;
}
CSOURCE

clang -O2 -o "${PROJECT_DIR}/${APP_DIR}/Contents/MacOS/${APP_NAME}" "${LAUNCHER_C}"
rm -f "${LAUNCHER_C}"
echo "Native launcher compiled."

# -- Info.plist --
cat > "${PROJECT_DIR}/${APP_DIR}/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>com.olly.taxonomy-library</string>
    <key>CFBundleVersion</key>
    <string>${VERSION}</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIconFile</key>
    <string>icon</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSRequiresAquaSystemAppearance</key>
    <false/>
    <key>NSHumanReadableCopyright</key>
    <string>Olly Research</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

# -- PkgInfo --
echo -n "APPL????" > "${PROJECT_DIR}/${APP_DIR}/Contents/PkgInfo"

# -- Copy icon --
if [ -f "${PROJECT_DIR}/icon.icns" ]; then
    cp "${PROJECT_DIR}/icon.icns" "${PROJECT_DIR}/${APP_DIR}/Contents/Resources/icon.icns"
    echo "Custom icon applied."
fi

# -- Ad-hoc sign so macOS trusts the bundle --
codesign --force --sign - "${PROJECT_DIR}/${APP_DIR}" 2>/dev/null || true

# -- Remove quarantine --
xattr -cr "${PROJECT_DIR}/${APP_DIR}" 2>/dev/null || true

# -- Touch to flush Finder icon cache --
touch "${PROJECT_DIR}/${APP_DIR}"

echo ""
echo "Done! Built: ${APP_DIR} (v${VERSION})"
echo ""
echo "To launch:    open \"${PROJECT_DIR}/${APP_DIR}\""
echo "To add to Dock: drag the .app to your Dock"
echo ""
echo "Code changes take effect on next app launch (runs from source)."
