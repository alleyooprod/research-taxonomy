#!/bin/bash
# Build, sign, and notarize the macOS .app bundle.
#
# Prerequisites:
#   - Apple Developer certificate installed in Keychain
#   - Set DEVELOPER_ID to your signing identity
#   - Set APPLE_ID and APPLE_TEAM_ID for notarization
#
# Usage:
#   ./build.sh                            # Build only
#   ./build.sh --sign                     # Build + sign
#   ./build.sh --sign --notarize          # Build + sign + notarize
#   ./build.sh --sign --notarize --create-dmg  # Build + sign + notarize + DMG

set -euo pipefail

APP_NAME="Research Taxonomy Library"
DIST_DIR="dist"
APP_PATH="$DIST_DIR/$APP_NAME.app"

# Extract version from config.py
VERSION=$(python3 -c "from config import APP_VERSION; print(APP_VERSION)")
echo "Version: $VERSION"

# Configurable via environment
DEVELOPER_ID="${DEVELOPER_ID:-}"
APPLE_ID="${APPLE_ID:-}"
APPLE_TEAM_ID="${APPLE_TEAM_ID:-}"
KEYCHAIN_PROFILE="${KEYCHAIN_PROFILE:-notarize-profile}"

SIGN=false
NOTARIZE=false
CREATE_DMG=false

for arg in "$@"; do
    case "$arg" in
        --sign) SIGN=true ;;
        --notarize) NOTARIZE=true ;;
        --create-dmg) CREATE_DMG=true ;;
    esac
done

echo "=== Building $APP_NAME v$VERSION ==="

# Clean previous build artifacts
echo "Cleaning previous build artifacts..."
rm -rf build "$DIST_DIR"

# Run py2app
python setup.py py2app 2>&1

if [ ! -d "$APP_PATH" ]; then
    echo "ERROR: Build failed — $APP_PATH not found"
    exit 1
fi

echo "Build complete: $APP_PATH"
du -sh "$APP_PATH"

# --- Code Signing ---
if [ "$SIGN" = true ]; then
    if [ -z "$DEVELOPER_ID" ]; then
        echo "WARNING: DEVELOPER_ID not set. Skipping code signing."
        echo "  Set it with: export DEVELOPER_ID='Developer ID Application: Your Name (TEAMID)'"
    else
        echo ""
        echo "=== Signing ==="
        codesign --deep --force --options runtime \
            --sign "$DEVELOPER_ID" \
            --entitlements entitlements.plist \
            "$APP_PATH"
        echo "Signed: $APP_PATH"
        codesign --verify --deep --strict "$APP_PATH"
        echo "Signature verified."
        echo ""
        echo "Codesign info:"
        codesign -dvv "$APP_PATH" 2>&1 | head -20
    fi
fi

# --- Notarization ---
if [ "$NOTARIZE" = true ] && [ "$SIGN" = true ]; then
    if [ -z "$APPLE_ID" ] || [ -z "$APPLE_TEAM_ID" ]; then
        echo "WARNING: APPLE_ID or APPLE_TEAM_ID not set. Skipping notarization."
        echo "  Set: export APPLE_ID='you@example.com' APPLE_TEAM_ID='XXXXXXXXXX'"
    else
        echo ""
        echo "=== Notarizing ==="
        ZIP_PATH="$DIST_DIR/$APP_NAME.zip"
        ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"

        xcrun notarytool submit "$ZIP_PATH" \
            --keychain-profile "$KEYCHAIN_PROFILE" \
            --wait

        echo "Stapling notarization ticket..."
        xcrun stapler staple "$APP_PATH"
        echo "Notarization complete."

        echo ""
        echo "=== Verifying notarization ==="
        spctl -a -v "$APP_PATH"

        rm -f "$ZIP_PATH"
    fi
fi

# --- DMG Creation ---
if [ "$CREATE_DMG" = true ]; then
    DMG_NAME="Research_Taxonomy_Library_${VERSION}.dmg"
    echo ""
    echo "=== Creating DMG ==="
    hdiutil create -volname "Research Taxonomy Library" \
        -srcfolder dist/ \
        -ov -format UDZO \
        "dist/$DMG_NAME"
    echo "DMG created: dist/$DMG_NAME"
fi

echo ""
echo "=== Done ==="
echo "App: $APP_PATH"
echo "Version: $VERSION"
echo ""
echo "To run: open '$APP_PATH'"
