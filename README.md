# JBL Quantum 810 for Linux

Battery and controls for the **JBL Quantum 810 Wireless** headset (USB dongle `0ecb:2069`) on Linux, with a GNOME top-bar indicator. Without the JBL plugged in, it shows the battery of Bluetooth headphones via UPower.

## Features

- Top bar: headset icon and battery percentage, orange at 20% and red at 10%, with a notification.
- Menu: microphone and game/chat mix (read-only), noise cancelling, sidetone and auto power-off (configurable), lighting on/off and RGB color (including "Green + Yellow").
- `quantum810` GTK app and command line:

```bash
quantum810 --status              # JSON with battery and settings
quantum810 --lights toggle
quantum810 --color 00ff00,ffff00
quantum810 --anc off|on|talkthru
quantum810 --sidetone off|low|mid|high
quantum810 --autooff never|30|60|120
```

## Install

```bash
./build-deb.sh            # builds dist/jbl-quantum810_1.0.0_all.deb
sudo apt install ./dist/jbl-quantum810_1.0.0_all.deb
gnome-extensions enable jbl-quantum810@local
```

Restart GNOME Shell (X11: Alt+F2, `r`, Enter; Wayland: log out and back in). The package installs the `70-jbl-quantum810.rules` udev rule, which gives access to the dongle without root.

## HID protocol notes

- Settings/lighting commands only take effect after a round of reads ("arm": `0x68 0x67 0x62 0x5c 0x75 0x49 0x51 0x47 0x4a 0x45`). The script always confirms by reading back.
- The firmware reports battery in 5% steps.
- **Never send more than 5 color segments** in report `0x4c`: larger values can permanently brick the lighting controller.
- The udev rule must be numbered below 73 (`uaccess` is applied in `73-seat-late`).
