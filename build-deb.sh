#!/bin/bash
# Gera dist/jbl-quantum810_<versão>_all.deb
set -euo pipefail
cd "$(dirname "$0")"

VERSION="${1:-1.0.0}"
MAINTAINER="Thiago Adriano <thiago.adriano@portergroup.com.br>"
BUILD=build
rm -rf "$BUILD" && mkdir -p "$BUILD" dist
# ---------- JBL Quantum 810 / fones ----------
P="$BUILD/jbl-quantum810"
install -Dm755 quantum810.py "$P/usr/bin/quantum810"
install -Dm644 70-jbl-quantum810.rules "$P/usr/lib/udev/rules.d/70-jbl-quantum810.rules"
mkdir -p "$P/usr/share/gnome-shell/extensions"
cp -r jbl-quantum810@local "$P/usr/share/gnome-shell/extensions/"
install -Dm644 /dev/stdin "$P/usr/share/applications/jbl-quantum810.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=JBL Quantum 810
Comment=Bateria, iluminação e ajustes do fone JBL Quantum 810
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
Description: Bateria e controles do JBL Quantum 810 (e fones Bluetooth) no GNOME
 Extensão do GNOME Shell com a bateria do fone na barra superior, alertas de
 bateria baixa, iluminação/cor RGB, cancelamento de ruído, sidetone e
 desligamento automático do JBL Quantum 810 Wireless (dongle USB 0ecb:2069).
 Sem o JBL, mostra a bateria de fones Bluetooth via UPower.
 Inclui o app quantum810 (GTK) e a regra udev de acesso ao dongle.
EOF
cat > "$P/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = configure ] && command -v udevadm >/dev/null; then
    udevadm control --reload || true
    udevadm trigger --action=change --subsystem-match=hidraw || true
fi
echo "Habilite com: gnome-extensions enable jbl-quantum810@local  (e reinicie o GNOME Shell)"
EOF
cat > "$P/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if command -v udevadm >/dev/null; then
    udevadm control --reload || true
fi
EOF
chmod 755 "$P/DEBIAN/postinst" "$P/DEBIAN/postrm"

# Permissões padrão de pacote: 755 pastas/executáveis, 644 demais arquivos
chmod -R u=rwX,go=rX "$BUILD"

dpkg-deb --root-owner-group --build "$BUILD/jbl-quantum810" "dist/jbl-quantum810_${VERSION}_all.deb"
rm -rf "$BUILD"
