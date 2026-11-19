import Clutter from 'gi://Clutter';
import Cogl from 'gi://Cogl';
import GdkPixbuf from 'gi://GdkPixbuf';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Pango from 'gi://Pango';
import St from 'gi://St';
import Cairo from 'cairo';

import {Extension, InjectionManager} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as Workspace from 'resource:///org/gnome/shell/ui/workspace.js';
import * as WorkspaceAnimation from 'resource:///org/gnome/shell/ui/workspaceAnimation.js';
import * as WorkspaceThumbnail from 'resource:///org/gnome/shell/ui/workspaceThumbnail.js';

// Índices de área começam em zero. O visual pertence exclusivamente à segunda.
const TARGET_WORKSPACE = 1;
const MOON_STYLE = {
    contrast: 1.23, blackPoint: 0.065, gamma: 0.92,
    ambientLight: 0.14, diffuseLight: 0.92,
    lightX: -0.48, lightY: -0.30, lightZ: 0.82,
    tintRed: 0.97, tintGreen: 0.995, tintBlue: 1.035,
    glowStrength: 0.028, glowAudioStrength: 0.19,
    rayLength: 118, rayWidth: 1.6,
    librationDegrees: 1.2, librationSpeed: 0.028,
    floatPixels: 6, floatSpeed: 0.04, floatXPixels: 10, floatXSpeed: 0.03,
    earthFloatX: 18, earthFloatY: 12, earthSpeed: 0.018,
    earthRoll: 0.7, earthBreath: 0.004,
    pulseStrength: 0.012, ambientBreath: 0.005, localBreath: 0.0018,
};
const EMPTY_STATE = {
    title: 'Sua música, em órbita', artist: 'Abra seu player e dê play',
    playback: 'Stopped', position: 0, duration: 0, lyric: '', nextLyric: '',
    lyricsState: 'idle', bars: Array(96).fill(0), beat: 0, artPath: '',
    canControl: false, canPrevious: false, canNext: false, canPlayPause: false,
};

function timeLabel(seconds) {
    const value = Math.max(0, Math.floor(seconds || 0));
    return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
}

class Earth {
    constructor(path, width, height) {
        const size = width * 1.23;
        this.actor = new St.Widget({width: size, height: size, reactive: false});
        this.actor.set_position(width * 0.18, height * 0.06);
        this.actor.set_pivot_point(0.5, 0.5);
        const photograph = new St.Widget({width: size, height: size, reactive: false,
            style: `background-image: url("${path}/terra.jpg"); background-size: contain;`});
        this.actor.add_child(photograph);
        this.shading = new St.DrawingArea({width: size, height: size, reactive: false});
        this.actor.add_child(this.shading);
        this.repaintId = this.shading.connect('repaint', area => this._paint(area));
    }

    _paint(area) {
        const cr = area.get_context();
        const [width, height] = area.get_surface_size();
        cr.scale(width / 1000, height / 1000);
        // Centro e raio da esfera na fotografia Apollo 17, sem alterar a foto.
        cr.translate(497.2, 498);
        const radius = 448;
        const atmosphere = new Cairo.RadialGradient(0, 0, radius - 5, 0, 0, radius + 17);
        atmosphere.addColorStopRGBA(0, 0.32, 0.66, 0.94, 0.025);
        atmosphere.addColorStopRGBA(0.22, 0.40, 0.74, 1, 0.25);
        atmosphere.addColorStopRGBA(0.38, 0.30, 0.62, 0.99, 0.13);
        atmosphere.addColorStopRGBA(1, 0.15, 0.40, 0.84, 0);
        cr.setSource(atmosphere);
        cr.arc(0, 0, radius + 17, 0, Math.PI * 2);
        cr.fill();
        cr.save();
        cr.arc(0, 0, radius, 0, Math.PI * 2);
        cr.clip();
        const night = new Cairo.LinearGradient(-radius * 0.7, -radius * 0.85,
            radius * 0.85, radius * 0.55);
        night.addColorStopRGBA(0, 0.005, 0.012, 0.028, 0);
        night.addColorStopRGBA(0.38, 0.005, 0.012, 0.028, 0.025);
        night.addColorStopRGBA(0.65, 0.003, 0.009, 0.022, 0.13);
        night.addColorStopRGBA(0.85, 0.002, 0.006, 0.018, 0.39);
        night.addColorStopRGBA(1, 0.001, 0.004, 0.014, 0.75);
        cr.setSource(night);
        cr.paint();
        const limb = new Cairo.RadialGradient(-radius * 0.2, -radius * 0.28,
            radius * 0.42, 0, 0, radius);
        limb.addColorStopRGBA(0, 0, 0.008, 0.025, 0);
        limb.addColorStopRGBA(0.72, 0, 0.008, 0.025, 0.035);
        limb.addColorStopRGBA(1, 0, 0.006, 0.020, 0.30);
        cr.setSource(limb);
        cr.paint();
        cr.restore();
        cr.setSourceRGBA(0.53, 0.80, 1, 0.25);
        cr.setLineWidth(0.8);
        cr.arc(0, 0, radius - 0.5, -Math.PI, -Math.PI * 0.06);
        cr.stroke();
        cr.$dispose();
    }

    destroy() {
        this.shading.disconnect(this.repaintId);
        this.actor.destroy();
    }
}

class Turntable {
    constructor(scale) {
        this.scale = scale;
        this.angle = 0;
        this.playing = false;
        this._artPath = '';
        this.actor = new St.Widget({width: 310 * scale, height: 226 * scale,
            reactive: false, clip_to_allocation: true});
        this.record = new St.Widget({width: 208 * scale, height: 208 * scale,
            reactive: false});
        this.record.set_position(-80 * scale, 9 * scale);
        this.record.set_pivot_point(0.5, 0.5);
        this.actor.add_child(this.record);
        this.disc = new St.DrawingArea({width: 208 * scale, height: 208 * scale,
            reactive: false});
        this.record.add_child(this.disc);
        this.repaintId = this.disc.connect('repaint', area => this._paint(area));
        this.cover = new Clutter.Actor({width: 116 * scale, height: 116 * scale,
            reactive: false, visible: false});
        this.cover.set_position(46 * scale, 46 * scale);
        this.record.add_child(this.cover);
        const spindle = new St.Widget({width: 11 * scale, height: 11 * scale,
            reactive: false, style: `background-color: #081111; border: ${0.7 * scale}px solid rgba(225, 242, 223, 0.85); border-radius: ${6 * scale}px;`});
        spindle.set_position(98.5 * scale, 98.5 * scale);
        this.record.add_child(spindle);
        this.controls = [
            {action: 'Previous', name: 'Faixa anterior', icon: 'media-skip-backward-symbolic',
                x: 151, y: 29, size: 36, caption: 'VOLTAR'},
            {action: 'PlayPause', name: 'Reproduzir', icon: 'media-playback-start-symbolic',
                x: 167, y: 88, size: 50, caption: 'TOCAR'},
            {action: 'Next', name: 'Próxima faixa', icon: 'media-skip-forward-symbolic',
                x: 151, y: 161, size: 36, caption: 'AVANÇAR'},
        ];
        for (const control of this.controls) {
            const primary = control.action === 'PlayPause';
            const visual = new St.Widget({width: control.size * scale, height: control.size * scale,
                layout_manager: new Clutter.BinLayout(), reactive: false,
                style: `border-radius: ${control.size * scale / 2}px; border: 1px solid rgba(190, 218, 202, ${primary ? 0.50 : 0.21}); background-color: rgba(13, 23, 23, 0.82);`});
            visual.set_position(control.x * scale, control.y * scale);
            control.visual = visual;
            control.iconActor = new St.Icon({icon_name: control.icon,
                icon_size: (primary ? 21 : 14) * scale,
                style: 'color: #e3efdf;', reactive: false});
            visual.add_child(control.iconActor);
            this.actor.add_child(visual);
            control.label = new St.Label({text: control.caption, reactive: false,
                style: `font-family: "DejaVu Sans"; font-size: ${8 * scale}px; color: #a1b9ac;`});
            control.label.set_position((control.x + control.size + 12) * scale,
                (control.y + control.size / 2 - 5) * scale);
            this.actor.add_child(control.label);
        }
    }

    update(state) {
        this.playing = state.playback === 'Playing';
        this._setCover(state.artPath || '');
        for (const control of this.controls) {
            control.enabled = !!state.player && state.canControl !== false &&
                (control.action === 'Previous' ? state.canPrevious !== false :
                    control.action === 'Next' ? state.canNext !== false : state.canPlayPause !== false);
            control.visual.opacity = control.enabled ? 255 : 100;
            control.label.opacity = control.enabled ? 255 : 120;
            if (control.action === 'PlayPause') {
                control.name = this.playing ? 'Pausar' : 'Reproduzir';
                control.iconActor.icon_name = this.playing ? 'media-playback-pause-symbolic' : 'media-playback-start-symbolic';
                control.label.text = this.playing ? 'PAUSAR' : 'TOCAR';
            }
        }
    }

    _setCover(filename) {
        if (filename === this._artPath)
            return;
        this._artPath = filename;
        this.cover.visible = false;
        this.cover.content = null;
        if (filename) {
            try {
                const original = GdkPixbuf.Pixbuf.new_from_file(filename);
                const side = Math.min(original.width, original.height);
                const size = 256;
                const source = original.new_subpixbuf(
                    Math.floor((original.width - side) / 2), Math.floor((original.height - side) / 2), side, side)
                    .scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR);
                const pixels = source.get_pixels();
                const stride = source.get_rowstride();
                const channels = source.get_n_channels();
                const rgba = new Uint8Array(size * size * 4);
                const center = (size - 1) / 2;
                for (let y = 0; y < size; y++) {
                    for (let x = 0; x < size; x++) {
                        const input = y * stride + x * channels;
                        const output = (y * size + x) * 4;
                        const edge = Math.max(0, Math.min(1, center - Math.hypot(x - center, y - center)));
                        rgba[output] = pixels[input];
                        rgba[output + 1] = pixels[input + 1];
                        rgba[output + 2] = pixels[input + 2];
                        rgba[output + 3] = Math.round(edge * (channels === 4 ? pixels[input + 3] : 255));
                    }
                }
                const image = new Clutter.Image();
                image.set_data(rgba, Cogl.PixelFormat.RGBA_8888, size, size, size * 4);
                this.cover.content = image;
                this.cover.visible = true;
            } catch (_) {
                // Uma capa ausente mantém o rótulo do vinil e os controles.
            }
        }
        this.disc.queue_repaint();
    }

    tick(elapsed = 1 / 24) {
        if (this.playing) {
            this.angle = (this.angle + elapsed * Math.PI * 2 / 16) % (Math.PI * 2);
            this.record.rotation_angle_z = this.angle * 180 / Math.PI;
        }
    }

    _paint(area) {
        const cr = area.get_context();
        const [width, height] = area.get_surface_size();
        cr.scale(width / 208, height / 208);
        cr.translate(104, 104);
        const vinyl = new Cairo.RadialGradient(-28, -35, 4, 0, 0, 103);
        vinyl.addColorStopRGB(0, 0.14, 0.19, 0.19);
        vinyl.addColorStopRGB(0.65, 0.035, 0.055, 0.06);
        vinyl.addColorStopRGB(1, 0.015, 0.025, 0.03);
        cr.setSource(vinyl);
        cr.arc(0, 0, 102, 0, Math.PI * 2);
        cr.fill();
        cr.setSourceRGBA(0.75, 0.86, 0.79, 0.38);
        cr.setLineWidth(1);
        cr.arc(0, 0, 102, 0, Math.PI * 2);
        cr.stroke();
        for (let radius = this.cover.visible ? 62 : 40; radius < 99; radius += 3) {
            cr.setSourceRGBA(0.77, 0.87, 0.8, radius % 2 ? 0.12 : 0.06);
            cr.setLineWidth(0.6);
            cr.arc(0, 0, radius, 0, Math.PI * 2);
            cr.stroke();
        }
        cr.save();
        cr.arc(0, 0, 100, 0, Math.PI * 2);
        cr.clip();
        const sheen = new Cairo.LinearGradient(-90, -90, 90, 90);
        sheen.addColorStopRGBA(0, 0.88, 0.95, 0.85, 0);
        sheen.addColorStopRGBA(0.43, 0.88, 0.95, 0.85, 0.01);
        sheen.addColorStopRGBA(0.5, 0.88, 0.95, 0.85, 0.13);
        sheen.addColorStopRGBA(0.57, 0.88, 0.95, 0.85, 0.01);
        sheen.addColorStopRGBA(1, 0.88, 0.95, 0.85, 0);
        cr.setSource(sheen);
        cr.paint();
        cr.restore();
        cr.save();
        cr.setSourceRGB(0.77, 0.85, 0.76);
        cr.arc(0, 0, this.cover.visible ? 59 : 34, 0, Math.PI * 2);
        cr.fill();
        cr.setSourceRGBA(0.1, 0.19, 0.17, 0.65);
        cr.setLineWidth(0.5);
        cr.arc(0, 0, 29, 0, Math.PI * 2);
        cr.stroke();
        cr.selectFontFace('DejaVu Sans', Cairo.FontSlant.NORMAL, Cairo.FontWeight.BOLD);
        cr.setFontSize(5.6);
        cr.moveTo(-17, -13);
        cr.showText('O R B I T A');
        cr.setFontSize(4.8);
        cr.moveTo(-9, 17);
        cr.showText('33 RPM');
        cr.setLineWidth(1);
        cr.moveTo(-25, 0);
        cr.lineTo(-12, 0);
        cr.moveTo(12, 0);
        cr.lineTo(25, 0);
        cr.stroke();
        cr.restore();
        cr.setSourceRGB(0.03, 0.055, 0.055);
        cr.arc(0, 0, 4.5, 0, Math.PI * 2);
        cr.fill();
        cr.setSourceRGBA(0.9, 0.96, 0.87, 0.8);
        cr.setLineWidth(0.7);
        cr.arc(0, 0, 5, 0, Math.PI * 2);
        cr.stroke();
        cr.$dispose();
    }

    destroy() {
        this.disc.disconnect(this.repaintId);
        this.actor.destroy();
    }
}

class Scene {
    constructor(path, monitor) {
        this.width = monitor.width;
        this.height = monitor.height;
        this.scale = Math.min(this.width / 1920, this.height / 1080);
        this.actor = new St.Widget({
            width: this.width, height: this.height,
            reactive: false, clip_to_allocation: true,
            style: 'background-color: #020407;',
        });
        this.bars = Array(96).fill(0);
        this.targets = Array(96).fill(0);
        this.state = {...EMPTY_STATE};
        this._lyricText = 'DEIXE O MUNDO\nLÁ FORA.';
        this._lyricCue = null;
        this._lyricRevision = 0;
        this._followingRevision = 0;
        this._lyricTransition = null;
        this._followingTransition = null;
        this._followingText = 'Dê play. O resto vira atmosfera.';
        this._hasPlayer = false;
        this._motionPhase = 0;
        this._spacePhase = 0;
        this._moonRotation = 0;
        this._moonPulse = 0;
        this._ambientMode = false;
        this._analysisMode = false;
        this._beatPulse = 0;
        this._bassAverage = 0;
        this._lastAudioActivity = 0;
        this._lastTick = GLib.get_monotonic_time() / 1e6;
        this._assetsPath = path;
        this._moonStyleRaw = '';
        this._moonStyle = {...MOON_STYLE};
        this._lastStyleCheck = 0;
        this.reloadMoonStyle();
        const w = this.width;
        const h = this.height;
        const s = this.scale;
        this.turntable = new Turntable(s);
        this.earth = new Earth(path, w, h);
        this.actor.add_child(this.earth.actor);
        this._box(0, 0, w, h, 'background-color: rgba(0, 5, 12, 0.38);');
        this._box(0, 0, w * 0.68, h,
            'background-gradient-direction: horizontal; background-gradient-start: rgba(1, 3, 7, 0.97); background-gradient-end: rgba(1, 3, 7, 0);');
        this._box(0, h * 0.43, w, h * 0.57,
            'background-gradient-direction: vertical; background-gradient-start: rgba(1, 3, 7, 0); background-gradient-end: rgba(1, 3, 7, 0.98);');
        this._label('Ó R B I T A', w * 0.071, h * 0.102, 14,
            'font-weight: 700; color: #e6eee9;');
        this._label('Á R E A   0 2', w * 0.071, h * 0.139, 9,
            'color: #89a5a4;');
        this.clock = this._label('', w * 0.833, h * 0.097, 48,
            'font-weight: 300; color: #e4ebe7;');
        this.date = this._label('', w * 0.834, h * 0.159, 11,
            'color: #91a2a1;');
        this.eyebrow = this._label('U M   I N S T A N T E   S Ó   S E U', w * 0.072, h * 0.309, 9,
            'color: #91aaa7;');
        this.lyricViewport = new St.Widget({width: w * 0.365, height: h * 0.265,
            clip_to_allocation: true, reactive: false});
        this.lyricViewport.set_position(w * 0.069, h * 0.35);
        this.actor.add_child(this.lyricViewport);
        this.lyric = this._createLyricLabel(this._lyricText);
        this._spareLyric = this._createLyricLabel('');
        this._spareLyric.opacity = 0;
        this.following = this._label('Dê play. O resto vira atmosfera.', w * 0.072, h * 0.63, 15,
            'color: #95a3a0;');
        this.following.set_width(w * 0.36);
        this.following.clutter_text.set_ellipsize(Pango.EllipsizeMode.END);

        const cx = w * 0.65;
        const cy = h * 0.465;
        const diameter = 640 * s;
        this.lunarGroup = new St.Widget({width: diameter, height: diameter, reactive: false});
        this.lunarGroup.set_position(cx - diameter / 2, cy - diameter / 2);
        this.lunarGroup.set_pivot_point(0.5, 0.5);
        this.actor.add_child(this.lunarGroup);
        this.spectrum = new St.DrawingArea({width: diameter, height: diameter, reactive: false});
        this.lunarGroup.add_child(this.spectrum);
        this.repaintId = this.spectrum.connect('repaint', area => this._paintSpectrum(area));
        const moon = 240 * s;
        this.moon = this._createMoon(`${path}/lua.jpg`, moon);
        this.moon.set_position((diameter - moon) / 2, (diameter - moon) / 2);
        this.moon.set_pivot_point(0.5, 0.5);
        this.lunarGroup.add_child(this.moon);
        this.lunarGroup.set_child_above_sibling(this.moon, this.spectrum);
        this._label('S I N T A   A   F R E Q U Ê N C I A', cx - 113 * s, cy + 260 * s, 9,
            'color: #9aaea7;');
        this.turntable.actor.set_position(0, h * 0.735);
        this.actor.add_child(this.turntable.actor);
        this._box(w * 0.185, h * 0.796, 3 * s, 41 * s, 'background-color: #a8d8c5;');
        this.title = this._label(EMPTY_STATE.title, w * 0.199, h * 0.792, 20,
            'font-weight: 600; color: #e8eeea;');
        this.title.set_width(w * 0.25);
        this.title.clutter_text.set_ellipsize(Pango.EllipsizeMode.END);
        this.artist = this._label(EMPTY_STATE.artist, w * 0.2, h * 0.826, 12,
            'color: #8eaaa2;');
        this.artist.set_width(w * 0.25);
        this.artist.clutter_text.set_ellipsize(Pango.EllipsizeMode.END);
        this._box(w * 0.185, h * 0.892, w * 0.264, 2 * s, 'background-color: rgba(195, 219, 208, 0.17);');
        this.progress = this._box(w * 0.185, h * 0.892, 1, 2 * s, 'background-color: #b5ddc9;');
        this.elapsed = this._label('0:00', w * 0.185, h * 0.907, 10, 'color: #89a49b;');
        this.total = this._label('0:00', w * 0.429, h * 0.907, 10, 'color: #89a49b;');
        this.audioStatus = this._label('●  ÁUDIO DO SISTEMA', w * 0.79, h * 0.9, 10,
            'color: #88a69b;');
        this.updateClock();
    }

    _box(x, y, width, height, style) {
        const actor = new St.Widget({width, height, reactive: false, style});
        actor.set_position(x, y);
        this.actor.add_child(actor);
        return actor;
    }

    _label(text, x, y, size, style) {
        const label = new St.Label({text, reactive: false,
            style: `font-family: "DejaVu Sans"; font-size: ${size * this.scale}px; ${style}`});
        label.set_position(x, y);
        this.actor.add_child(label);
        return label;
    }

    _createLyricLabel(text) {
        const label = new St.Label({text, reactive: false,
            width: this.lyricViewport.width, height: this.lyricViewport.height,
            style: `font-family: "DejaVu Sans"; font-size: ${58 * this.scale}px; font-weight: 800; color: #f0f2e9;`});
        label.clutter_text.set_line_wrap(true);
        label.clutter_text.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR);
        label.clutter_text.set_ellipsize(Pango.EllipsizeMode.END);
        this.lyricViewport.add_child(label);
        return label;
    }

    _showLyric(text, animate, cue = null) {
        if (text === this._lyricText && cue === this._lyricCue)
            return;
        this._lyricText = text;
        this._lyricCue = cue;
        this._lyricRevision++;
        const outgoing = this.lyric;
        const incoming = this._spareLyric;
        outgoing.remove_all_transitions();
        incoming.remove_all_transitions();
        incoming.text = text;
        incoming.visible = true;
        this.lyric = incoming;
        this._spareLyric = outgoing;
        this.lyricViewport.set_child_above_sibling(incoming, outgoing);
        if (!animate) {
            this._lyricTransition = null;
            incoming.opacity = 255;
            incoming.translation_y = 0;
            outgoing.opacity = 0;
            return;
        }
        incoming.opacity = 0;
        incoming.translation_y = 40 * this.scale;
        this._lyricTransition = {start: GLib.get_monotonic_time() / 1e6,
            incoming, outgoing, opacity: outgoing.opacity, y: outgoing.translation_y};
    }

    _showFollowing(text, animate) {
        if (text === this._followingText)
            return;
        this._followingText = text;
        this._followingRevision++;
        this.following.remove_all_transitions();
        if (!animate) {
            this._followingTransition = null;
            this.following.text = text;
            this.following.opacity = 255;
            this.following.translation_y = 0;
            return;
        }
        this._followingTransition = {start: GLib.get_monotonic_time() / 1e6,
            text, opacity: this.following.opacity, y: this.following.translation_y,
            switched: false};
    }

    _advanceLyricAnimations(now) {
        const ease = progress => 1 - Math.pow(1 - Math.min(1, Math.max(0, progress)), 3);
        const transition = this._lyricTransition;
        if (transition) {
            const elapsed = now - transition.start;
            const entering = ease(elapsed / 0.4);
            const leaving = ease(elapsed / 0.22);
            transition.incoming.opacity = Math.round(255 * entering);
            transition.incoming.translation_y = 40 * this.scale * (1 - entering);
            transition.outgoing.opacity = Math.round(transition.opacity * (1 - leaving));
            transition.outgoing.translation_y = transition.y + (-32 * this.scale - transition.y) * leaving;
            if (elapsed >= 0.4)
                this._lyricTransition = null;
        }
        const next = this._followingTransition;
        if (next) {
            const elapsed = now - next.start;
            if (elapsed < 0.12) {
                const progress = ease(elapsed / 0.12);
                this.following.opacity = Math.round(next.opacity * (1 - progress));
                this.following.translation_y = next.y + (-6 * this.scale - next.y) * progress;
            } else {
                if (!next.switched) {
                    this.following.text = next.text;
                    next.switched = true;
                }
                const progress = ease((elapsed - 0.12) / 0.22);
                this.following.opacity = Math.round(255 * progress);
                this.following.translation_y = 8 * this.scale * (1 - progress);
                if (elapsed >= 0.34)
                    this._followingTransition = null;
            }
        }
    }

    _createMoon(filename, diameter) {
        // A fotografia tem uma margem preta. O recorte e a máscara pertencem
        // à textura em memória, preservando o arquivo original e seus créditos.
        const original = GdkPixbuf.Pixbuf.new_from_file(filename);
        const size = 512;
        const source = original.new_subpixbuf(224, 180, 2136, 2136)
            .scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR);
        const pixels = source.get_pixels();
        const stride = source.get_rowstride();
        const channels = source.get_n_channels();
        const rgba = new Uint8Array(size * size * 4);
        const center = (size - 1) / 2;
        const style = this._moonStyle;
        const lightLength = Math.hypot(style.lightX, style.lightY, style.lightZ) || 1;
        const light = [style.lightX / lightLength, style.lightY / lightLength, style.lightZ / lightLength];
        const tones = new Float32Array(256);
        for (let value = 0; value < 256; value++)
            tones[value] = Math.pow(Math.max(0, Math.min(1,
                (value / 255 - style.blackPoint) * style.contrast)), style.gamma);
        for (let y = 0; y < size; y++) {
            for (let x = 0; x < size; x++) {
                const input = y * stride + x * channels;
                const output = (y * size + x) * 4;
                const distance = Math.hypot(x - center, y - center);
                const alpha = Math.max(0, Math.min(1, (center - distance) / 1.6));
                if (alpha === 0)
                    continue;
                const nx = (x - center) / center;
                const ny = (y - center) / center;
                const nz = Math.sqrt(Math.max(0, 1 - nx * nx - ny * ny));
                const diffuse = Math.max(0, nx * light[0] + ny * light[1] + nz * light[2]);
                const limb = 0.76 + 0.24 * Math.pow(nz, 0.3);
                const illumination = (style.ambientLight + style.diffuseLight * diffuse) * limb;
                rgba[output] = Math.min(255, Math.round(tones[pixels[input]] * illumination * style.tintRed * 255));
                rgba[output + 1] = Math.min(255, Math.round(tones[pixels[input + 1]] * illumination * style.tintGreen * 255));
                rgba[output + 2] = Math.min(255, Math.round(tones[pixels[input + 2]] * illumination * style.tintBlue * 255));
                rgba[output + 3] = Math.round(alpha * 255);
            }
        }
        const image = new Clutter.Image();
        image.set_data(rgba, Cogl.PixelFormat.RGBA_8888, size, size, size * 4);
        return new Clutter.Actor({width: diameter, height: diameter,
            reactive: false, content: image});
    }

    reloadMoonStyle() {
        try {
            const file = Gio.File.new_for_path(`${this._assetsPath}/moon-style.json`);
            const [success, bytes] = file.load_contents(null);
            if (!success)
                return false;
            const raw = new TextDecoder().decode(bytes);
            if (raw === this._moonStyleRaw)
                return false;
            const values = JSON.parse(raw);
            const style = {...MOON_STYLE};
            for (const key of Object.keys(style)) {
                if (Number.isFinite(values[key]))
                    style[key] = Math.max(key.startsWith('light') ? -2 : 0, Math.min(100, values[key]));
            }
            style.gamma = Math.max(0.1, style.gamma);
            this._moonStyle = style;
            this._moonStyleRaw = raw;
            if (this.moon) {
                const old = this.moon;
                const moon = this._createMoon(`${this._assetsPath}/lua.jpg`, old.width);
                moon.set_position(old.x, old.y);
                moon.set_pivot_point(0.5, 0.5);
                moon.rotation_angle_z = old.rotation_angle_z;
                this.lunarGroup.add_child(moon);
                this.lunarGroup.set_child_above_sibling(moon, this.spectrum);
                this.moon = moon;
                old.destroy();
            }
            return true;
        } catch (_) {
            // Um arquivo incompleto durante a edição preserva o visual atual.
            return false;
        }
    }

    updateClock() {
        const now = GLib.DateTime.new_now_local();
        this.clock.text = now.format('%H:%M');
        const weekdays = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo'];
        this.date.text = `${weekdays[now.get_day_of_week() - 1]}  ·  ${now.format('%d / %m')}`;
    }

    update(state) {
        this.state = {...EMPTY_STATE, ...state};
        this.targets = this.state.bars;
        const now = GLib.get_monotonic_time() / 1e6;
        if (now - this._lastStyleCheck > 2) {
            this._lastStyleCheck = now;
            this.reloadMoonStyle();
        }
        if (this.targets.some(value => value > 0.04))
            this._lastAudioActivity = now;
        this._analysisMode = this.state.audio === 'spotify-analysis';
        this._ambientMode = !this._analysisMode && this.state.playback === 'Playing' && now - this._lastAudioActivity > 2;
        const bass = this.targets.slice(0, 24).reduce((sum, value) => sum + value, 0) / 24;
        this._bassAverage += (bass - this._bassAverage) * 0.06;
        const onset = this._analysisMode ? Math.max(0, Math.min(1, this.state.beat || 0)) :
            Math.max(0, Math.min(1, (bass - this._bassAverage - 0.025) * 3.5));
        this._beatPulse = this.state.playback === 'Playing' ?
            Math.max(onset, this._beatPulse * 0.7) : 0;
        this.title.text = this.state.title;
        this.artist.text = this.state.artist;
        const hasPlayer = !!this.state.player;
        this.eyebrow.text = hasPlayer ? 'A G O R A   N A   S U A   Ó R B I T A' : 'U M   I N S T A N T E   S Ó   S E U';
        const timedLyrics = ['synced', 'estimated'].includes(this.state.lyricsState);
        const text = (this.state.lyric || (hasPlayer ? timedLyrics ? '♪' : this.state.title : 'DEIXE O MUNDO\nLÁ FORA.')).toLocaleUpperCase('pt-BR');
        const cue = typeof this.state.lyricCue === 'number' ?
            `${this.state.player}:${this.state.title}:${this.state.lyricCue}` : null;
        this._showLyric(text, this._hasPlayer && hasPlayer, cue);
        const following = this.state.nextLyric ||
            (this.state.playback === 'Paused' ? 'No seu tempo. A música espera.' :
                this.state.lyricsState === 'loading' ? 'Buscando a letra…' :
                    hasPlayer ? this.state.artist : 'Dê play. O resto vira atmosfera.');
        this._showFollowing(following, this._hasPlayer && hasPlayer);
        this._hasPlayer = hasPlayer;
        const ratio = this.state.duration > 0 ? Math.min(1, Math.max(0, this.state.position / this.state.duration)) : 0;
        this.progress.width = Math.max(1, this.width * 0.264 * ratio);
        this.elapsed.text = timeLabel(this.state.position);
        this.total.text = timeLabel(this.state.duration);
        this.audioStatus.text = state.error ? '○  ÁUDIO INDISPONÍVEL' :
            this.state.playback === 'Paused' ? '○  PAUSADO' :
                this._analysisMode ? '●  RITMO DO SPOTIFY' :
                    this._ambientMode ? '○  ANIMAÇÃO AMBIENTE' : '●  ÁUDIO DO SISTEMA';
        this.turntable.update(this.state);
    }

    tick() {
        const now = GLib.get_monotonic_time() / 1e6;
        const elapsed = Math.min(0.08, Math.max(0, now - this._lastTick));
        this._lastTick = now;
        this._advanceLyricAnimations(now);
        this.spectrum.queue_repaint();
        this.turntable.tick(elapsed);
        this._spacePhase += elapsed;
        const playing = this.state.playback === 'Playing';
        if (playing)
            this._motionPhase += elapsed;
        const bass = playing ? this.targets.slice(0, 24).reduce((sum, value) => sum + value, 0) / 24 : 0;
        this._moonPulse += (bass - this._moonPulse) * 0.16;
        this._applySpaceMotion();
    }

    _applySpaceMotion() {
        const style = this._moonStyle;
        const phase = this._spacePhase;
        const earth = this.earth.actor;
        earth.translation_x = Math.sin(phase * style.earthSpeed) * style.earthFloatX * this.scale;
        earth.translation_y = Math.sin(phase * style.earthSpeed * 0.83) * style.earthFloatY * this.scale;
        earth.rotation_angle_z = Math.sin(phase * style.earthSpeed * 0.67) * style.earthRoll;
        const distance = 1 + Math.sin(phase * style.earthSpeed * 0.72) * style.earthBreath;
        earth.set_scale(distance, distance);
        this._moonRotation = Math.sin(phase * style.librationSpeed) * style.librationDegrees;
        const breathing = this._ambientMode ? style.ambientBreath : style.localBreath;
        const pulse = 1 + this._moonPulse * style.pulseStrength + Math.sin(phase * 0.032) * breathing;
        this.moon.rotation_angle_z = this._moonRotation;
        this.lunarGroup.set_scale(pulse, pulse);
        this.lunarGroup.translation_x = -Math.sin(phase * style.floatXSpeed) * style.floatXPixels * this.scale;
        this.lunarGroup.translation_y = Math.sin(phase * style.floatSpeed) * style.floatPixels * this.scale;
    }

    _paintSpectrum(area) {
        const cr = area.get_context();
        const [width, height] = area.get_surface_size();
        cr.scale(width / 640, height / 640);
        cr.translate(320, 320);
        cr.setLineCap(Cairo.LineCap.ROUND);
        for (let i = 0; i < 96; i++) {
            const target = Math.max(0, Math.min(1, this.targets[i] || 0));
            this.bars[i] += (target - this.bars[i]) * (target > this.bars[i] ? 0.76 : 0.22);
        }
        const energy = this._ambientMode ? 0.12 + Math.sin(this._motionPhase * 1.3) * 0.04 :
            this.bars.reduce((sum, value) => sum + value, 0) / 96;
        const style = this._moonStyle;
        cr.save();
        cr.translate(12, 17);
        cr.scale(1, 0.94);
        const shadow = new Cairo.RadialGradient(0, 0, 95, 0, 0, 155);
        shadow.addColorStopRGBA(0, 0, 0.006, 0.015, 0.33);
        shadow.addColorStopRGBA(0.5, 0, 0.006, 0.015, 0.18);
        shadow.addColorStopRGBA(1, 0, 0.006, 0.015, 0);
        cr.setSource(shadow);
        cr.arc(0, 0, 155, 0, Math.PI * 2);
        cr.fill();
        cr.restore();
        const beat = this._ambientMode ? 0 : this._beatPulse;
        const glow = style.glowStrength + (energy + beat * 0.55) * style.glowAudioStrength;
        const haloRadius = 176 + beat * 25;
        const halo = new Cairo.RadialGradient(0, 0, 112, 0, 0, haloRadius);
        halo.addColorStopRGBA(0, 0.67, 0.80, 0.97, glow);
        halo.addColorStopRGBA(0.28, 0.57, 0.74, 0.95, glow * 0.45);
        halo.addColorStopRGBA(0.65, 0.45, 0.65, 0.90, glow * 0.12);
        halo.addColorStopRGBA(1, 0.45, 0.65, 0.90, 0);
        cr.setSource(halo);
        cr.arc(0, 0, haloRadius, 0, Math.PI * 2);
        cr.fill();
        cr.setSourceRGBA(0.66, 0.85, 0.94, 0.18 + beat * 0.34);
        cr.setLineWidth(0.7 + beat * 0.6);
        cr.arc(0, 0, 120.8, 0, Math.PI * 2);
        cr.stroke();
        for (let i = 0; i < 144; i++) {
            const mirrored = i < 72 ? i : 143 - i;
            const index = Math.round(mirrored / 71 * 95);
            const amplitude = this._ambientMode ?
                0.04 + (0.5 + Math.sin(index * 0.25 + this._motionPhase) * 0.5) * 0.09 : this.bars[index];
            const length = 1.2 + Math.pow(amplitude, 1.18) * style.rayLength;
            const angle = i / 144 * Math.PI * 2 - Math.PI / 2;
            const radius = 124;
            const c = Math.cos(angle);
            const s = Math.sin(angle);
            // Uma passagem larga dá brilho; a linha fina mantém os raios definidos.
            cr.setSourceRGBA(0.48, 0.82, 0.89, amplitude * 0.17 + beat * amplitude * 0.12);
            cr.setLineWidth(style.rayWidth + 3.4);
            cr.moveTo(c * radius, s * radius);
            cr.lineTo(c * (radius + length), s * (radius + length));
            cr.stroke();
            cr.setSourceRGBA(0.75 + beat * 0.18, 0.93, 0.98, 0.12 + Math.sqrt(amplitude) * 0.84);
            cr.setLineWidth(style.rayWidth);
            cr.moveTo(c * radius, s * radius);
            cr.lineTo(c * (radius + length), s * (radius + length));
            cr.stroke();
        }
        cr.$dispose();
    }

    destroy() {
        this._lyricRevision++;
        this._followingRevision++;
        this._lyricTransition = null;
        this._followingTransition = null;
        this.lyric.remove_all_transitions();
        this._spareLyric.remove_all_transitions();
        this.following.remove_all_transitions();
        this.turntable.destroy();
        this.earth.destroy();
        this.spectrum.disconnect(this.repaintId);
        this.actor.destroy();
    }
}

export default class OrbitaDesktop extends Extension {
    enable() {
        this._enabled = true;
        this._signals = [];
        this._clones = new Set();
        this._controlHits = [];
        this._controlPending = false;
        this._controlCancellable = new Gio.Cancellable();
        this._injections = new InjectionManager();
        this._state = {...EMPTY_STATE};
        this._monitor = Main.layoutManager.primaryIndex;
        this._buildScene();
        this._installWorkspaceViews();
        this._connect(global.workspace_manager, 'active-workspace-changed', () => this._sync());
        this._connect(global.workspace_manager, 'workspaces-reordered', () => this._syncClones());
        this._connect(Main.overview, 'showing', () => this._sync());
        this._connect(Main.overview, 'hidden', () => this._sync());
        this._connect(Main.layoutManager, 'monitors-changed', () => this._rebuild());
        this._connect(Main.sessionMode, 'updated', () => this._sync());
        this._connect(global.display, 'restacked', () => this._syncControls());
        this._connect(global.display, 'notify::focus-window', () => this._syncControls());
        this._controlsTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 150, () => {
            if (this._shouldRun())
                this._syncControls();
            return GLib.SOURCE_CONTINUE;
        });
        this._clockTimer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 15, () => {
            this._scene?.updateClock();
            return GLib.SOURCE_CONTINUE;
        });
        this._animationTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 41, () => {
            if (this._shouldRun())
                this._scene?.tick();
            return GLib.SOURCE_CONTINUE;
        });
        this._sync();
    }

    _connect(object, signal, callback) {
        this._signals.push([object, object.connect(signal, callback)]);
    }

    _buildScene() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;
        this._scene = new Scene(this.path, monitor);
        this._scene.actor.set_position(monitor.x, monitor.y);
        // O grupo fica abaixo das janelas e dos ícones do desktop.
        Main.layoutManager._backgroundGroup.add_child(this._scene.actor);
        this._scene.update(this._state);
        this._createControlHits();
    }

    _createControlHits() {
        const monitor = Main.layoutManager.primaryMonitor;
        const s = this._scene.scale;
        for (const control of this._scene.turntable.controls) {
            // Somente a área clicável vai ao chrome. O desenho permanece atrás
            // das janelas, junto ao papel de parede e suas prévias.
            const button = new St.Button({width: control.size * s, height: control.size * s,
                reactive: true, can_focus: true, track_hover: true,
                accessible_name: control.name, style_class: 'orbita-control-hit'});
            button.set_position(monitor.x + control.x * s,
                monitor.y + monitor.height * 0.735 + control.y * s);
            button.connect('clicked', () => this._controlPlayer(control.action));
            Main.layoutManager.addChrome(button, {affectsStruts: false, affectsInputRegion: true});
            this._controlHits.push({button, control});
        }
        this._syncControls();
    }

    _syncControls() {
        if (!this._scene || !this._controlHits)
            return;
        const active = this._shouldRun() && !Main.overview.visible;
        const workspace = global.workspace_manager.get_active_workspace();
        const windows = active ? global.get_window_actors().map(actor => actor.meta_window).filter(window =>
            window.get_window_type() !== Meta.WindowType.DESKTOP &&
            window.get_window_type() !== Meta.WindowType.DOCK &&
            !window.minimized && window.located_on_workspace(workspace) &&
            window.showing_on_its_workspace()) : [];
        for (const {button, control} of this._controlHits) {
            const x = button.x;
            const y = button.y;
            const covered = windows.some(window => {
                const r = window.get_frame_rect();
                return r.x < x + button.width && r.x + r.width > x &&
                    r.y < y + button.height && r.y + r.height > y;
            });
            button.visible = active && !covered;
            button.reactive = button.visible && !!control.enabled && !this._controlPending;
            button.can_focus = button.reactive;
            button.accessible_name = control.name;
        }
    }

    _controlPlayer(action) {
        const control = this._scene?.turntable.controls.find(item => item.action === action);
        const player = this._state.player;
        if (!this._shouldRun() || Main.overview.visible || this._controlPending ||
            !control?.enabled || !player?.startsWith('org.mpris.MediaPlayer2.'))
            return Promise.resolve(false);
        this._controlPending = true;
        this._syncControls();
        return new Promise(resolve => {
            Gio.DBus.session.call(player, '/org/mpris/MediaPlayer2',
                'org.mpris.MediaPlayer2.Player', action, null, null,
                Gio.DBusCallFlags.NO_AUTO_START, 1500, this._controlCancellable,
                (bus, result) => {
                    let success = false;
                    try {
                        bus.call_finish(result);
                        success = true;
                    } catch (error) {
                        if (this._enabled && !this._controlCancellable?.is_cancelled())
                            console.error(`Órbita: controle do player: ${error.message}`);
                    }
                    this._controlPending = false;
                    if (this._enabled)
                        this._syncControls();
                    resolve(success);
                });
        });
    }

    _destroyControlHits() {
        for (const {button} of this._controlHits) {
            Main.layoutManager.removeChrome(button);
            button.destroy();
        }
        this._controlHits = [];
    }

    _shouldRun() {
        return this._enabled && !Main.sessionMode.isLocked &&
            global.workspace_manager.get_active_workspace_index() === TARGET_WORKSPACE;
    }

    _sync() {
        if (!this._scene)
            return;
        const active = this._shouldRun();
        this._scene.actor.visible = active && !Main.overview.visible;
        if (active)
            this._startBridge();
        else
            this._stopBridge();
        this._syncClones();
        this._syncControls();
    }

    _installWorkspaceViews() {
        const extension = this;
        this._injections.overrideMethod(Workspace.Workspace.prototype, '_init', original => function (...args) {
            original.call(this, ...args);
            extension._addClone(this._background._backgroundGroup, this.metaWorkspace, this.monitorIndex);
        });
        this._injections.overrideMethod(WorkspaceAnimation.WorkspaceGroup.prototype, '_init', original => function (...args) {
            original.call(this, ...args);
            if (this._workspace)
                extension._addClone(this._background, this._workspace, this._monitor.index);
        });
        this._injections.overrideMethod(WorkspaceThumbnail.WorkspaceThumbnail.prototype, '_init', original => function (...args) {
            original.call(this, ...args);
            extension._addClone(this._contents, this.metaWorkspace, this.monitorIndex, true);
        });
        this._scanExistingViews();
    }

    _scanExistingViews() {
        const walk = actor => {
            if (actor instanceof Workspace.Workspace)
                this._addClone(actor._background._backgroundGroup, actor.metaWorkspace, actor.monitorIndex);
            else if (actor instanceof WorkspaceThumbnail.WorkspaceThumbnail)
                this._addClone(actor._contents, actor.metaWorkspace, actor.monitorIndex, true);
            for (const child of actor.get_children())
                walk(child);
        };
        walk(global.stage);
    }

    _addClone(parent, workspace, monitorIndex, thumbnail = false) {
        if (!this._scene || monitorIndex !== Main.layoutManager.primaryIndex || !workspace || !parent)
            return;
        if (parent.get_children().some(child => this._clones.has(child)))
            return;
        const clone = new Clutter.Clone({source: this._scene.actor,
            width: this._scene.width, height: this._scene.height, reactive: false});
        clone._orbitaWorkspace = workspace;
        if (thumbnail) {
            const monitor = Main.layoutManager.primaryMonitor;
            clone.set_position(monitor.x, monitor.y);
            parent.insert_child_at_index(clone, 0);
        } else {
            parent.add_child(clone);
        }
        clone.visible = workspace.index() === TARGET_WORKSPACE;
        clone.connect('destroy', () => this._clones?.delete(clone));
        this._clones.add(clone);
    }

    _syncClones() {
        for (const clone of this._clones)
            clone.visible = clone._orbitaWorkspace.index() === TARGET_WORKSPACE && !Main.sessionMode.isLocked;
    }

    _rebuild() {
        this._stopBridge();
        this._destroyControlHits();
        for (const clone of [...this._clones])
            clone.destroy();
        this._scene?.destroy();
        this._scene = null;
        this._monitor = Main.layoutManager.primaryIndex;
        this._buildScene();
        this._scanExistingViews();
        this._sync();
    }

    _startBridge() {
        if (this._process || !this._enabled)
            return;
        try {
            const process = Gio.Subprocess.new(['/usr/bin/python3', `${this.path}/bridge.py`],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
            this._process = process;
            this._cancellable = new Gio.Cancellable();
            const cancellable = this._cancellable;
            const stream = new Gio.DataInputStream({base_stream: process.get_stdout_pipe()});
            const read = () => {
                stream.read_line_async(GLib.PRIORITY_DEFAULT, cancellable, (source, result) => {
                    try {
                        const [line] = source.read_line_finish_utf8(result);
                        if (line === null || !this._enabled || cancellable.is_cancelled())
                            return;
                        const state = JSON.parse(line);
                        if (state.error) {
                            this._scene?.update({...this._state, error: state.error});
                        } else {
                            this._state = state;
                            this._scene?.update(state);
                        }
                        read();
                    } catch (error) {
                        if (!cancellable.is_cancelled())
                            console.error(`Órbita: ${error.message}`);
                    }
                });
            };
            read();
            process.wait_async(null, (_source, result) => {
                try {
                    process.wait_finish(result);
                } catch (_) {
                    // O processo pode já ter sido finalizado ao desativar a extensão.
                }
                if (this._process === process) {
                    this._process = null;
                    this._cancellable = null;
                    if (this._enabled && this._shouldRun() && !this._retryTimer) {
                        this._retryTimer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 5, () => {
                            this._retryTimer = 0;
                            if (this._shouldRun())
                                this._startBridge();
                            return GLib.SOURCE_REMOVE;
                        });
                    }
                }
            });
        } catch (error) {
            console.error(`Órbita: ${error.message}`);
            this._scene?.update({...this._state, error: error.message});
        }
    }

    _stopBridge() {
        this._cancellable?.cancel();
        this._cancellable = null;
        this._process?.send_signal(15);
        this._process = null;
        if (this._retryTimer) {
            GLib.source_remove(this._retryTimer);
            this._retryTimer = 0;
        }
    }

    disable() {
        this._enabled = false;
        this._controlCancellable?.cancel();
        this._controlCancellable = null;
        this._stopBridge();
        this._destroyControlHits();
        for (const [object, id] of this._signals)
            object.disconnect(id);
        this._signals = [];
        for (const timer of [this._clockTimer, this._animationTimer, this._controlsTimer]) {
            if (timer)
                GLib.source_remove(timer);
        }
        this._clockTimer = this._animationTimer = this._controlsTimer = 0;
        this._injections?.clear();
        this._injections = null;
        for (const clone of [...this._clones])
            clone.destroy();
        this._clones.clear();
        this._scene?.destroy();
        this._scene = null;
    }
}
