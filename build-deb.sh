#!/bin/bash
# Builds dist/jbl-quantum810_<version>_all.deb
set -euo pipefail
cd "$(dirname "$0")"

VERSION="${1:-1.0.0}"
MAINTAINER="Thiago Adriano <thiago.adriano@portergroup.com.br>"
BUILD=build
rm -rf "$BUILD" && mkdir -p "$BUILD" dist
# ---------- JBL Quantum 810 / headphones ----------
P="$BUILD/jbl-quantum810"
install -Dm755 quantum810.py "$P/usr/bin/quantum810"
install -Dm644 70-jbl-quantum810.rules "$P/usr/lib/udev/rules.d/70-jbl-quantum810.rules"
mkdir -p "$P/usr/share/gnome-shell/extensions"
cp -r jbl-quantum810@local "$P/usr/share/gnome-shell/extensions/"
install -Dm644 /dev/stdin "$P/usr/share/applications/jbl-quantum810.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=JBL Quantum 810
Comment=Battery, lighting and settings for the JBL Quantum 810 headset
Exec=quantum810
Icon=audio-headset
Categories=AudioVideo;Settings;HardwareSettings;
EOF
mkdir -p "$P/DEBIAN"
cat > "$P/DEBIAN/control" <<EOF
Package: jbl-quantum810
Version: $VERSION
Architecture: all
Maintainer: $MAINTAINER
Depends: python3, python3-gi, gir1.2-gtk-3.0, gnome-shell (>= 45), udev
Recommends: upower, gir1.2-notify-0.7
Section: gnome
Priority: optional
Description: JBL Quantum 810 (and Bluetooth headphones) battery and controls for GNOME
 GNOME Shell extension with the headset battery in the top bar, low-battery
 alerts, RGB lighting/color, noise cancelling, sidetone and auto power-off
 for the JBL Quantum 810 Wireless (USB dongle 0ecb:2069).
 Without the JBL, shows Bluetooth headphone battery via UPower.
 Includes the quantum810 GTK app and the udev rule for dongle access.
EOF
cat > "$P/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = configure ] && command -v udevadm >/dev/null; then
    udevadm control --reload || true
    udevadm trigger --action=change --subsystem-match=hidraw || true
fi
echo "Enable with: gnome-extensions enable jbl-quantum810@local  (then restart GNOME Shell)"
EOF
cat > "$P/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if command -v udevadm >/dev/null; then
    udevadm control --reload || true
fi
EOF
chmod 755 "$P/DEBIAN/postinst" "$P/DEBIAN/postrm"

# Standard package permissions: 755 dirs/executables, 644 other files
chmod -R u=rwX,go=rX "$BUILD"

dpkg-deb --root-owner-group --build "$BUILD/jbl-quantum810" "dist/jbl-quantum810_${VERSION}_all.deb"
rm -rf "$BUILD"
