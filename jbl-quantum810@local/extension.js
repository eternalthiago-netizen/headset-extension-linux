import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Pango from 'gi://Pango';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as MessageTray from 'resource:///org/gnome/shell/ui/messageTray.js';

// The .deb package installs to /usr/bin; a manual install lives in ~/.local/bin
const SCRIPT = GLib.find_program_in_path('quantum810') ??
    GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'quantum810']);
const POLL_SECONDS = 60;
// Low-battery alerts (the headset reports in 5% steps)
const LOW_THRESHOLDS = [20, 10];
const REARM_AT = 30;   // charged above this: the alerts are re-armed
const ALERTS_FILE = GLib.build_filenamev([GLib.get_user_cache_dir(), 'jbl-quantum810-alerts.json']);

function loadSent() {
    try {
        const [, bytes] = GLib.file_get_contents(ALERTS_FILE);
        return JSON.parse(new TextDecoder().decode(bytes)).sent ?? [];
    } catch {
        return [];
    }
}

function saveSent(sent) {
    try {
        GLib.file_set_contents(ALERTS_FILE, JSON.stringify({sent}));
    } catch (e) {
        logError(e);
    }
}

function batteryStyle(pct) {
    if (pct <= 10)
        return 'color: #ff6b6b;';
    if (pct <= 20)
        return 'color: #ffb347;';
    return '';
}
const ANC = {0: 'Off', 1: 'On', 2: 'TalkThru'};
// key: [label, [[headset value, script argument, label], ...]]
const SETTINGS = {
    anc: ['Noise cancelling', [[0, 'off', 'Off'], [1, 'on', 'On'], [2, 'talkthru', 'TalkThru']]],
    sidetone: ['Sidetone', [[0, 'off', 'Off'], [1, 'low', 'Low'], [2, 'mid', 'Mid'], [3, 'high', 'High']]],
    autooff: ['Auto power-off', [[0, 'never', 'Never'], [6, '30', '30 min'], [12, '60', '1 h'], [24, '120', '2 h']]],
};
const MIC = {0: 'Muted', 1: 'Active'};
const SIDETONE = {0: 'Off', 1: 'Low', 2: 'Mid', 3: 'High'};

function autoOff(v) {
    if (v === null || v === undefined)
        return '—';
    if (v === 0)
        return 'Never';
    const min = v * 5;
    return min < 60 ? `${min} min` : `${min / 60} h`;
}

const COLORS = [
    ['Red', 'ff0000'], ['Green', '00ff00'], ['Blue', '0000ff'], ['White', 'ffffff'],
    ['Purple', '8000ff'], ['Orange', 'ff6000'], ['Cyan', '33ffcc'], ['Pink', 'ff0099'],
    ['Green + Yellow', '00ff00,ffff00'],
];

function run(args) {
    return new Promise((resolve, reject) => {
        const proc = Gio.Subprocess.new([SCRIPT, ...args],
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
        proc.communicate_utf8_async(null, null, (p, res) => {
            try {
                const [, out] = p.communicate_utf8_finish(res);
                resolve(out);
            } catch (e) {
                reject(e);
            }
        });
    });
}

const Indicator = GObject.registerClass(
class Indicator extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'JBL Quantum 810');

        // panel-status-menu-box = icon + text side by side (like clock/keyboard)
        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        this._icon = new St.Icon({icon_name: 'audio-headset-symbolic', style_class: 'system-status-icon'});
        this._label = new St.Label({text: '…', y_align: Clutter.ActorAlign.CENTER});
        this._label.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
        box.add_child(this._icon);
        box.add_child(this._label);
        this.add_child(box);

        this._info = new PopupMenu.PopupMenuItem('JBL Quantum 810', {reactive: false});
        this.menu.addMenuItem(this._info);

        this._rows = {};
        this._settings = {};
        for (const [key, [label, options]] of Object.entries(SETTINGS)) {
            const sub = new PopupMenu.PopupSubMenuMenuItem(label);
            sub._options = [];
            for (const [value, arg, optLabel] of options) {
                const item = new PopupMenu.PopupMenuItem(optLabel);
                item.connect('activate', () => {
                    sub.label.text = `${label}: …`;
                    run([`--${key}`, arg]).then(() => this.refresh()).catch(logError);
                });
                sub.menu.addMenuItem(item);
                sub._options.push([value, item]);
            }
            this.menu.addMenuItem(sub);
            this._settings[key] = [label, sub];
        }

        for (const [key, label] of [['mic', 'Microphone'], ['mix', 'Game/chat mix']]) {
            const item = new PopupMenu.PopupMenuItem(label, {reactive: false});
            const value = new St.Label({text: '—', x_expand: true, x_align: Clutter.ActorAlign.END,
                y_align: Clutter.ActorAlign.CENTER});
            item.add_child(value);
            this.menu.addMenuItem(item);
            this._rows[key] = value;
        }
        this._jblSep = new PopupMenu.PopupSeparatorMenuItem();
        this.menu.addMenuItem(this._jblSep);

        this._lights = new PopupMenu.PopupSwitchMenuItem('Lighting', false);
        this._lights.connect('toggled', (_item, state) => {
            run(['--lights', state ? 'on' : 'off']).then(() => this.refresh()).catch(logError);
        });
        this.menu.addMenuItem(this._lights);

        this._colors = new PopupMenu.PopupSubMenuMenuItem('Color');
        for (const [name, hex] of COLORS) {
            const item = new PopupMenu.PopupMenuItem(name);
            item.insert_child_at_index(new St.Widget({
                style: `background-gradient-direction: horizontal; background-gradient-start: #${hex.split(',')[0]}; background-gradient-end: #${hex.split(',').at(-1)}; border-radius: 4px; width: 14px; height: 14px; margin-right: 6px;`,
                y_align: Clutter.ActorAlign.CENTER,
            }), 1);
            item.connect('activate', () => {
                this._info.label.text = `Applying color ${name}…`;
                run(['--color', hex]).then(() => this.refresh()).catch(logError);
            });
            this._colors.menu.addMenuItem(item);
        }
        this.menu.addMenuItem(this._colors);

        const refresh = new PopupMenu.PopupMenuItem('Refresh');
        refresh.connect('activate', () => this.refresh());
        this.menu.addMenuItem(refresh);

        this.menu.connect('open-state-changed', (_m, open) => {
            if (open)
                this.refresh();
        });

        this.refresh();
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, POLL_SECONDS, () => {
            this.refresh();
            return GLib.SOURCE_CONTINUE;
        });
    }

    async refresh() {
        let st;
        try {
            st = JSON.parse(await run(['--status']));
        } catch (e) {
            st = {battery: null, lights: null, error: String(e)};
        }
        if (st.battery === null) {
            this._label.text = '';
            this._label.style = '';
            this._icon.opacity = 110;
            this._info.label.text = st.error ?? 'Headset off or out of range';
        } else {
            this._label.text = `${st.battery}%`;
            this._label.style = batteryStyle(st.battery);
            this._icon.opacity = 255;
            this._info.label.text = `${st.name ?? 'Headphones'}: ${st.battery}%`;
            this._checkBattery(st.battery, st.name ?? 'Headphones');
        }
        // Bluetooth headphones: battery only; the controls below are JBL-only
        const jbl = st.source !== 'bluetooth';
        for (const item of [this._jblSep, this._lights, this._colors,
            ...Object.values(this._settings).map(([, sub]) => sub),
            ...Object.values(this._rows).map(label => label.get_parent())])
            item.visible = jbl;
        const on = st.battery !== null;
        const fmt = (map, v) => (on && v !== null && v !== undefined ? map[v] ?? String(v) : '—');
        this._rows.mic.text = fmt(MIC, st.mic);
        this._rows.mix.text = on && st.mix !== null && st.mix !== undefined ? `${st.mix} / 16` : '—';
        const current = {anc: fmt(ANC, st.anc), sidetone: fmt(SIDETONE, st.sidetone),
            autooff: on ? autoOff(st.autooff) : '—'};
        for (const [key, [label, sub]] of Object.entries(this._settings)) {
            sub.label.text = `${label}: ${current[key]}`;
            sub.setSensitive(on);
            for (const [value, item] of sub._options)
                item.setOrnament(st[key] === value ? PopupMenu.Ornament.CHECK : PopupMenu.Ornament.NONE);
        }
        this._lights.setSensitive(st.lights !== null);
        this._lights.setToggleState(st.lights === 1);
        this._colors.setSensitive(st.lights !== null);
        const cur = COLORS.find(([, hex]) => hex === st.color);
        this._colors.label.text = cur ? `Color: ${cur[0]}` : (st.color ? `Color: #${st.color}` : 'Color');
    }

    _checkBattery(pct, name) {
        let sent = loadSent();
        if (pct >= REARM_AT && sent.length) {
            saveSent([]);
            return;
        }
        const hit = LOW_THRESHOLDS.filter(t => pct <= t && !sent.includes(t));
        if (hit.length === 0)
            return;
        sent = [...sent, ...hit];
        saveSent(sent);
        const critical = Math.min(...hit) <= 10;
        const source = MessageTray.getSystemSource();
        source.addNotification(new MessageTray.Notification({
            source,
            title: `${name}: battery at ${pct}%`,
            body: critical ? 'Plug in the headset to charge.' : 'Low battery.',
            iconName: critical ? 'battery-level-10-symbolic' : 'battery-level-20-symbolic',
            urgency: critical ? MessageTray.Urgency.CRITICAL : MessageTray.Urgency.NORMAL,
        }));
    }

    destroy() {
        if (this._timer) {
            GLib.source_remove(this._timer);
            this._timer = null;
        }
        super.destroy();
    }
});

export default class JblQuantumExtension extends Extension {
    enable() {
        this._indicator = new Indicator();
        // position 0 of the right box = just left of the network/sound/battery icons
        Main.panel.addToStatusArea(this.uuid, this._indicator, 0, 'right');
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
