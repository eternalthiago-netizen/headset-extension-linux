#!/usr/bin/env python3
"""Monitor do JBL Quantum 810 Wireless (dongle 0ecb:2069) para Linux/GTK3.

Protocolo (confirmado pela comunidade):
  - Feature report 0x49 -> [0x49, bateria%]          (consulta ativa)
  - Feature report 0x4a -> [0x4a, 0|1]               (lê estado da iluminação)
  - Feature report 0x45 -> ANC 0 off / 1 on / 2 TalkThru
  - Feature report 0x67 -> microfone 1 ativo / 0 mudo
  - Feature report 0x5c -> sidetone 0 off / 1 baixo / 2 médio / 3 alto
  - Feature report 0x62 -> mix jogo/chat 0..16
  - Feature report 0x75 -> desligamento automático, em unidades de 5 min (0 = nunca)
  - Feature report 0x4b <- [0x4b, 0|1]               (desliga/liga iluminação)
  - Feature report 0x4c <- [0x4c, elem, vel, nseg]   (cabeçalho da tabela RGB)
  - Feature report 0x4d <- [0x4d, elem, i, R, G, B, modo, last]  (segmento)
    Valores fora do conjunto que o QuantumENGINE envia podem travar o RGB de
    forma permanente (nseg > 5!). Ver JBL_810_RGB_Tray/docs/RGB_SAFE_RANGES.md
  - Input report  0x08 -> [0x08, bateria%]           (enviado pelo headset)
  - Input report  0x02 -> 0 ANC off / 1 ANC / 2 TalkThru
  - Input report  0x06 -> 0 mic mudo / 1 mic ativo
  - Input report  0x07 -> 0 luzes off / 1 luzes on

Uso:  python3 quantum810.py          (janela)
      python3 quantum810.py --cli    (imprime a bateria e sai)
      python3 quantum810.py --lights on|off|toggle
      python3 quantum810.py --color RRGGBB[,RRGGBB...]   (até 5, alterna)
      python3 quantum810.py --anc off|on|talkthru
      python3 quantum810.py --sidetone off|low|mid|high
      python3 quantum810.py --autooff never|30|60|120   (minutos)
      python3 quantum810.py --status (JSON para a extensão do GNOME)
"""
import fcntl
import glob
import json
import os
import sys
import time

VID, PID = 0x0ECB, 0x2069
POLL_SECONDS = 30
LOW_BATTERY = 20

# RGB: exatamente a tabela de fábrica do QuantumENGINE, trocando só a cor.
RGB_SEGMENTS = 5                 # NUNCA acima de 5: trava o MCU da iluminação
RGB_SPEED = 0x64                 # velocidade de fábrica
RGB_MODES = {0: 0x02, 1: 0x05}   # 0 = logo, 1 = anel; modos de fábrica
RGB_ARM_REPORTS = (0x68, 0x67, 0x62, 0x5C, 0x75, 0x49, 0x51, 0x47, 0x4A, 0x45)
RGB_WRITE_DELAY = 0.01           # o dongle descarta SETs enviados em rajada
RGB_ENABLED = True
CONFIG = os.path.expanduser("~/.config/quantum810.json")
COLOR_PRESETS = {
    "Vermelho": "ff0000", "Verde": "00ff00", "Azul": "0000ff", "Branco": "ffffff",
    "Roxo": "8000ff", "Laranja": "ff6000", "Ciano": "33ffcc", "Rosa": "ff0099",
    "Verde + Amarelo": "00ff00,ffff00",
}


def HIDIOCGFEATURE(length):
    return (3 << 30) | (length << 16) | (ord("H") << 8) | 0x07


def HIDIOCSFEATURE(length):
    return (3 << 30) | (length << 16) | (ord("H") << 8) | 0x06


def find_hidraw():
    for dev in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(dev, "device/uevent")) as f:
                uevent = f.read()
        except OSError:
            continue
        if f"HID_ID=0003:{VID:08X}:{PID:08X}" in uevent:
            return "/dev/" + os.path.basename(dev)
    return None


class Headset:
    def __init__(self):
        self.path = find_hidraw()
        if not self.path:
            raise RuntimeError("Dongle JBL Quantum 810 não encontrado.")
        try:
            self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError:
            raise RuntimeError(
                f"Sem permissão para {self.path}. Instale a regra udev "
                "(veja 70-jbl-quantum810.rules) e reconecte o dongle."
            )
        self.state = {"battery": None, "anc": None, "mic": None, "lights": None,
                      "sidetone": None, "mix": None, "autooff": None}

    def read_battery(self):
        buf = bytearray([0x49, 0])
        fcntl.ioctl(self.fd, HIDIOCGFEATURE(len(buf)), buf)
        # 0 costuma significar headset desligado/fora de alcance
        self.state["battery"] = buf[1] if 0 < buf[1] <= 100 else None
        return self.state["battery"]

    def read_lights(self):
        buf = bytearray([0x4a, 0])
        fcntl.ioctl(self.fd, HIDIOCGFEATURE(len(buf)), buf)
        self.state["lights"] = buf[1]
        return buf[1]

    def arm(self):
        """Leituras que o QuantumENGINE faz ao conectar. Sem elas o headset
        pode ignorar comandos de iluminação (visto ao vivo)."""
        for rid in RGB_ARM_REPORTS:
            buf = bytearray([rid] + [0] * 63)
            try:
                fcntl.ioctl(self.fd, HIDIOCGFEATURE(len(buf)), buf)
            except OSError:
                pass

    def _get(self, rid):
        buf = bytearray([rid, 0])
        fcntl.ioctl(self.fd, HIDIOCGFEATURE(len(buf)), buf)
        return buf[1]

    def read_all(self):
        """Lê todos os estados consultáveis (somente leitura)."""
        self.read_battery()
        self.read_lights()
        for key, rid in (("anc", 0x45), ("mic", 0x67), ("sidetone", 0x5C),
                         ("mix", 0x62), ("autooff", 0x75)):
            self.state[key] = self._get(rid)
        return self.state

    def set_setting(self, name, value):
        """SET de 2 bytes do QuantumENGINE + confirmação por leitura."""
        set_id, get_id, allowed = SETTINGS[name]
        if value not in allowed:  # só valores vistos nas capturas oficiais
            raise ValueError(f"Valor inválido para {name}: {value}")
        for _ in range(4):
            self.arm()
            self._set([set_id, value])
            time.sleep(0.4)
            if self._get(get_id) == value:
                self.state[name] = value
                return True
        return False

    def set_lights(self, on):
        """Liga/desliga e confirma lendo 0x4a. Retorna True se o headset aceitou."""
        want = 1 if on else 0
        for _ in range(4):
            self.arm()
            self._set([0x4B, want])
            time.sleep(0.4)
            if self.read_lights() == want:
                return True
        return False

    def _set(self, data):
        fcntl.ioctl(self.fd, HIDIOCSFEATURE(len(data)), bytes(data))
        time.sleep(RGB_WRITE_DELAY)

    def set_color(self, hexcolor):
        """Uma cor ("ff0000") ou até 5 separadas por vírgula, tocadas em sequência."""
        if not RGB_ENABLED:
            raise RuntimeError("Mudança de cor desativada.")
        colors = [parse_color(c) for c in hexcolor.split(",")]
        if not 1 <= len(colors) <= RGB_SEGMENTS:
            raise ValueError(f"Use de 1 a {RGB_SEGMENTS} cores.")
        # Cor única: tabela de fábrica com 5 segmentos iguais
        segments = RGB_SEGMENTS if len(colors) == 1 else len(colors)
        assert 1 <= segments <= RGB_SEGMENTS  # > 5 trava o MCU da iluminação
        self.arm()
        for elem in (0, 1):
            self._set([0x4C, elem, RGB_SPEED, segments])
            for i in range(segments):
                r, g, b = colors[i % len(colors)]
                self._set([0x4D, elem, i, r, g, b, RGB_MODES[elem], i * 2])
        # A tabela só é aplicada na transição desligado -> ligado
        self.set_lights(False)
        if not self.set_lights(True):
            raise RuntimeError("Cor enviada, mas o headset não religou as luzes.")
        save_config({"color": ",".join("%02x%02x%02x" % c for c in colors)})

    def drain_input(self):
        """Lê os input reports pendentes. Retorna True se algo mudou."""
        changed = False
        while True:
            try:
                data = os.read(self.fd, 64)
            except BlockingIOError:
                break
            if len(data) < 2:
                continue
            rid, val = data[0], data[1]
            key = {0x08: "battery", 0x02: "anc", 0x06: "mic", 0x07: "lights"}.get(rid)
            if key and self.state[key] != val:
                self.state[key] = val
                changed = True
        return changed

    def close(self):
        os.close(self.fd)


def parse_color(text):
    text = text.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError("Cor deve ser RRGGBB, ex.: ff0000")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def load_config():
    try:
        with open(CONFIG) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(values):
    cfg = load_config()
    cfg.update(values)
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w") as f:
        json.dump(cfg, f)


# nome: (SET id, GET id, valores permitidos)
SETTINGS = {
    "anc": (0x46, 0x45, (0, 1, 2)),
    "sidetone": (0x5D, 0x5C, (0, 1, 2, 3)),
    "autooff": (0x75, 0x75, (0, 6, 12, 24)),   # unidades de 5 min
}
SETTING_ARGS = {
    "anc": {"off": 0, "on": 1, "talkthru": 2},
    "sidetone": {"off": 0, "low": 1, "mid": 2, "high": 3},
    "autooff": {"never": 0, "30": 6, "60": 12, "120": 24},
}

ANC_LABEL = {0: "Desligado", 1: "Cancelamento de ruído", 2: "TalkThru"}
SIDETONE_LABEL = {0: "Desligado", 1: "Baixo", 2: "Médio", 3: "Alto"}


def autooff_label(v):
    if v is None:
        return "—"
    return "Nunca" if v == 0 else (f"{v * 5} min" if v * 5 < 60 else f"{v * 5 / 60:g} h")


def cli():
    hs = Headset()
    pct = hs.read_battery()
    print(f"{hs.path}: bateria {pct}%" if pct is not None else "Headset desligado ou fora de alcance")


# Tipos do UPower que contam como fone: headset, headphones, other-audio
UPOWER_HEADPHONE_KINDS = {17: "headset", 19: "headphones", 21: "other-audio"}


def bluetooth_headphone():
    """Fone Bluetooth com bateria, via UPower (que lê o org.bluez.Battery1)."""
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

        def call(path, iface, method, args=None):
            return bus.call_sync("org.freedesktop.UPower", path, iface, method, args,
                                 None, Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]

        for path in call("/org/freedesktop/UPower", "org.freedesktop.UPower", "EnumerateDevices"):
            props = call(path, "org.freedesktop.DBus.Properties", "GetAll",
                         GLib.Variant("(s)", ("org.freedesktop.UPower.Device",)))
            if props.get("Type") in UPOWER_HEADPHONE_KINDS and props.get("IsPresent", True):
                return {"source": "bluetooth", "name": props.get("Model") or "Fone Bluetooth",
                        "battery": round(props.get("Percentage", 0))}
    except Exception:  # sem D-Bus/UPower: só não há fone Bluetooth para mostrar
        pass
    return None


def status_cli():
    try:
        hs = Headset()
        out = dict(hs.read_all(), color=load_config().get("color"), source="jbl",
                   name="JBL Quantum 810")
    except (RuntimeError, OSError) as e:
        out = bluetooth_headphone() or {"battery": None, "lights": None, "error": str(e)}
    print(json.dumps(out))


def lights_cli(arg):
    hs = Headset()
    on = {"on": True, "off": False, "toggle": not hs.read_lights()}.get(arg)
    if on is None:
        sys.exit("Use: --lights on|off|toggle")
    if not hs.set_lights(on):
        sys.exit("O headset não confirmou a mudança de iluminação.")
    print("Iluminação", "ligada" if on else "desligada")


def color_cli(arg):
    try:
        Headset().set_color(arg)
    except ValueError as e:
        sys.exit(str(e))
    print("Cor aplicada:", arg.lower())


def setting_cli(name, arg):
    value = SETTING_ARGS[name].get(arg)
    if value is None:
        sys.exit(f"Use: --{name} " + "|".join(SETTING_ARGS[name]))
    if not Headset().set_setting(name, value):
        sys.exit("O headset não confirmou a mudança.")
    print(f"{name} = {arg}")


def gui():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Notify", "0.7")
    from gi.repository import GLib, Gtk
    try:
        from gi.repository import Notify
        Notify.init("JBL Quantum 810")
    except (ImportError, ValueError):
        Notify = None

    win = Gtk.Window(title="JBL Quantum 810")
    win.set_default_size(320, 0)
    win.set_border_width(18)
    win.connect("destroy", Gtk.main_quit)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    win.add(box)
    big = Gtk.Label()
    big.set_markup("<span size='xx-large' weight='bold'>—</span>")
    box.pack_start(big, False, False, 0)
    bar = Gtk.LevelBar(min_value=0, max_value=100)
    bar.add_offset_value("low", LOW_BATTERY)
    bar.add_offset_value("high", 50)
    bar.add_offset_value("full", 100)
    box.pack_start(bar, False, False, 0)

    grid = Gtk.Grid(column_spacing=12, row_spacing=4)
    box.pack_start(grid, False, False, 6)
    values = {}
    for i, (key, label) in enumerate(
        [("anc", "Modo de áudio"), ("mic", "Microfone"), ("sidetone", "Sidetone"),
         ("mix", "Mix jogo/chat"), ("autooff", "Desligamento automático"), ("dev", "Dispositivo")]
    ):
        name = Gtk.Label(label=label, xalign=0)
        name.get_style_context().add_class("dim-label")
        val = Gtk.Label(label="—", xalign=0)
        grid.attach(name, 0, i, 1, 1)
        grid.attach(val, 1, i, 1, 1)
        values[key] = val

    lights_row = Gtk.Box(spacing=12)
    lights_label = Gtk.Label(label="Iluminação", xalign=0)
    lights_row.pack_start(lights_label, True, True, 0)
    lights_switch = Gtk.Switch(sensitive=False)
    lights_row.pack_end(lights_switch, False, False, 0)
    box.pack_start(lights_row, False, False, 0)

    color_row = Gtk.Box(spacing=12)
    color_row.pack_start(Gtk.Label(label="Cor", xalign=0), True, True, 0)
    color_btn = Gtk.ColorButton(use_alpha=False, sensitive=False)
    color_row.set_no_show_all(not RGB_ENABLED)
    saved = load_config().get("color")
    if saved:
        from gi.repository import Gdk
        rgba = Gdk.RGBA()
        rgba.parse("#" + saved.split(",")[0])
        color_btn.set_rgba(rgba)
    color_row.pack_end(color_btn, False, False, 0)
    preset_combo = Gtk.ComboBoxText(sensitive=False)
    for name, hexcolor in COLOR_PRESETS.items():
        preset_combo.append(hexcolor, name)
    if saved in COLOR_PRESETS.values():
        preset_combo.set_active_id(saved)
    color_row.pack_end(preset_combo, False, False, 0)
    box.pack_start(color_row, False, False, 0)

    status = Gtk.Label(xalign=0, wrap=True)
    status.get_style_context().add_class("dim-label")
    box.pack_start(status, False, False, 0)
    btn = Gtk.Button(label="Atualizar")
    box.pack_start(btn, False, False, 0)

    ctx = {"hs": None, "warned": False, "syncing": False}

    def render():
        hs = ctx["hs"]
        st = hs.state if hs else {}
        pct = st.get("battery")
        big.set_markup(
            f"<span size='xx-large' weight='bold'>{pct}%</span>" if pct is not None
            else "<span size='x-large'>Headset desligado</span>"
        )
        bar.set_value(pct or 0)
        values["anc"].set_text(ANC_LABEL.get(st.get("anc"), "—"))
        values["mic"].set_text({0: "Mudo", 1: "Ativo"}.get(st.get("mic"), "—"))
        values["sidetone"].set_text(SIDETONE_LABEL.get(st.get("sidetone"), "—"))
        values["mix"].set_text("—" if st.get("mix") is None else f"{st['mix']} (0–16)")
        values["autooff"].set_text(autooff_label(st.get("autooff")))
        lights = st.get("lights")
        lights_switch.set_sensitive(hs is not None and lights is not None)
        color_btn.set_sensitive(hs is not None)
        preset_combo.set_sensitive(hs is not None)
        ctx["syncing"] = True
        lights_switch.set_active(bool(lights))
        ctx["syncing"] = False
        values["dev"].set_text(hs.path if hs else "—")
        win.set_title(f"JBL Quantum 810 — {pct}%" if pct is not None else "JBL Quantum 810")

        # Aviso de bateria baixa: fica a cargo da extensão do GNOME (evita duplicar)

    def on_input(_fd, _cond):
        try:
            if ctx["hs"].drain_input():
                render()
        except OSError:
            disconnect("Dongle desconectado.")
            return False
        return True

    def disconnect(msg):
        if ctx["hs"]:
            GLib.source_remove(ctx["watch"])
            ctx["hs"].close()
            ctx["hs"] = None
        status.set_text(msg)
        render()

    def refresh(*_):
        if ctx["hs"] is None:
            try:
                ctx["hs"] = Headset()
                ctx["watch"] = GLib.io_add_watch(ctx["hs"].fd, GLib.IO_IN, on_input)
            except RuntimeError as e:
                status.set_text(str(e))
                render()
                return True
        try:
            ctx["hs"].read_all()
            status.set_text(f"Atualizado a cada {POLL_SECONDS}s")
        except OSError as e:
            disconnect(f"Erro de leitura: {e}")
        render()
        return True

    def on_lights(switch, _param):
        if ctx["syncing"] or ctx["hs"] is None:
            return
        try:
            ctx["hs"].set_lights(switch.get_active())
        except OSError as e:
            status.set_text(f"Falha ao mudar a iluminação: {e}")
        render()

    lights_switch.connect("notify::active", on_lights)

    def apply_color(hexcolor):
        try:
            ctx["hs"].set_color(hexcolor)
            status.set_text(f"Cor aplicada: #{hexcolor}")
        except (OSError, RuntimeError) as e:
            status.set_text(f"Falha ao mudar a cor: {e}")
        render()

    def on_color(button):
        if ctx["hs"] is None:
            return
        c = button.get_rgba()
        ctx["syncing"] = True
        preset_combo.set_active(-1)
        ctx["syncing"] = False
        apply_color("%02x%02x%02x" % (round(c.red * 255), round(c.green * 255), round(c.blue * 255)))

    def on_preset(combo):
        if ctx["syncing"] or ctx["hs"] is None or combo.get_active_id() is None:
            return
        apply_color(combo.get_active_id())

    color_btn.connect("color-set", on_color)
    preset_combo.connect("changed", on_preset)
    btn.connect("clicked", refresh)
    refresh()
    GLib.timeout_add_seconds(POLL_SECONDS, refresh)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    try:
        if "--cli" in sys.argv:
            cli()
        elif "--status" in sys.argv:
            status_cli()
        elif any(f"--{n}" in sys.argv for n in SETTINGS):
            name = next(n for n in SETTINGS if f"--{n}" in sys.argv)
            i = sys.argv.index(f"--{name}")
            setting_cli(name, sys.argv[i + 1] if i + 1 < len(sys.argv) else "")
        elif "--color" in sys.argv:
            i = sys.argv.index("--color")
            color_cli(sys.argv[i + 1] if i + 1 < len(sys.argv) else "")
        elif "--lights" in sys.argv:
            i = sys.argv.index("--lights")
            lights_cli(sys.argv[i + 1] if i + 1 < len(sys.argv) else "")
        else:
            gui()
    except RuntimeError as e:
        sys.exit(str(e))
