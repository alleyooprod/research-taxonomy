#!/bin/bash
# Build a macOS .app bundle for Research Taxonomy Library.
# Uses AppleScript wrapper so macOS grants proper file access permissions.
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

# -- Ensure logs dir exists --
mkdir -p "${PROJECT_DIR}/logs"

# -- Create AppleScript-based .app --
# AppleScript apps inherit full user permissions (Documents, Desktop, etc.)
rm -rf "${PROJECT_DIR}/${APP_DIR}"

osacompile -o "${PROJECT_DIR}/${APP_DIR}" -e "
do shell script \"cd '${PROJECT_DIR}' && '${PROJECT_DIR}/venv/bin/python3' '${PROJECT_DIR}/desktop.py' >> '${PROJECT_DIR}/logs/desktop.log' 2>&1 &\"
"

# -- Remove quarantine flag --
xattr -cr "${PROJECT_DIR}/${APP_DIR}" 2>/dev/null || true

echo ""
echo "Done! Built: ${PROJECT_DIR}/${APP_DIR}"
echo ""
echo "To launch:  open \"${PROJECT_DIR}/${APP_DIR}\""
echo "To add to Dock: drag the .app to your Dock."
