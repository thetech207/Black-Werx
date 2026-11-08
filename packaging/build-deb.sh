#!/bin/sh
# Build a .deb from dist/blackwerx (run pyinstaller first).
# Usage: packaging/build-deb.sh <version>
set -eu
VER="$1"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
STAGE=$(mktemp -d)/blackwerx-$VER
mkdir -p "$STAGE/DEBIAN" "$STAGE/usr/lib" "$STAGE/usr/bin" \
    "$STAGE/usr/share/applications" \
    "$STAGE/usr/share/icons/hicolor/256x256/apps" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps" \
    "$STAGE/usr/share/doc/blackwerx"

cp -r "$ROOT/dist/blackwerx" "$STAGE/usr/lib/blackwerx"
chmod -R u=rwX,go=rX "$STAGE/usr/lib/blackwerx"

printf '#!/bin/sh\nexec /usr/lib/blackwerx/blackwerx "$@"\n' \
    > "$STAGE/usr/bin/blackwerx"
chmod 755 "$STAGE/usr/bin/blackwerx"

install -m 644 "$ROOT/packaging/blackwerx.desktop" \
    "$STAGE/usr/share/applications/blackwerx.desktop"
install -m 644 "$ROOT/Images/blackwerx-icon.svg" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps/blackwerx.svg"
install -m 644 "$ROOT/Images/blackwerx-icon-1024.png" \
    "$STAGE/usr/share/icons/hicolor/256x256/apps/blackwerx.png"

printf 'Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\nUpstream-Name: Black-Werx\nSource: https://github.com/thetech207/Black-Werx\n' \
    > "$STAGE/usr/share/doc/blackwerx/copyright"

cat > "$STAGE/DEBIAN/control" <<CTL
Package: blackwerx
Version: $VER
Section: graphics
Priority: optional
Architecture: amd64
Maintainer: thetech207 <https://github.com/thetech207>
Depends: libc6, libstdc++6, libgl1, libegl1, libxkbcommon0, libdbus-1-3, libfontconfig1, libglib2.0-0t64
Description: Blackwork embroidery pattern editor
 Vector-style editor for blackwork (cross-stitch) embroidery patterns.
 Features an Aida-grid canvas, reusable blocks with libraries and
 arrays, symmetry tools, layers and guides, SVG import, and chart,
 realistic, PDF/PNG/SVG, and Tajima .pat export.
CTL

dpkg-deb --build --root-owner-group "$STAGE" \
    "$ROOT/dist/blackwerx_${VER}_amd64.deb"
echo "built dist/blackwerx_${VER}_amd64.deb"
