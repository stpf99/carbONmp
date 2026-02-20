#!/usr/bin/env python3
"""
CarbonX Player  v3.0  "Grid Edition"
- Naprawiony tor audio: uridecodebin + tee -> FX chain -> autoaudiosink
- Layout 2x2 (16:10): playlista | wizualizer / FX tabs z TapeSim/Spatial/EQ/Chain
- Skalowalny UI (przyciski + / -)
- Signal Chain 13 modulow DSP z zapisem presetow JSON
- Monitor Mode przez wirtualny PulseAudio sink
"""
import sys, os, math, random, re, json, locale, time

# Wymuszamy locale C dla GLib/GStreamer — MUSI być przed importem gi
# Bez tego GLib loguje floaty z przecinkiem (pl_PL) i set_property może odrzucać wartości
os.environ["LC_NUMERIC"] = "C"
os.environ["LC_ALL"] = ""          # zachowaj resztę locale (język UI)
try:
    locale.setlocale(locale.LC_NUMERIC, "C")
except Exception:
    pass

from PyQt6.QtWidgets import (QInputDialog,
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QListWidget, QFileDialog, QFrame,
    QComboBox, QGroupBox, QCheckBox, QMessageBox, QDial,
    QDialog, QLineEdit, QSpinBox, QListWidgetItem, QStackedWidget,
    QScrollArea, QSplitter, QTabWidget, QButtonGroup
)
from PyQt6.QtCore  import Qt, QTimer, QPointF, QRect, QUrl, pyqtSignal
from PyQt6.QtGui   import (QPainter, QColor, QPen, QBrush, QLinearGradient,
                            QRadialGradient, QPixmap, QImage, QPainterPath,
                            QFontMetrics, QFont, QPalette)
from PyQt6.QtMultimedia        import QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
Gst.init(None)

try:
    import eyed3, logging
    logging.getLogger("eyed3").setLevel(logging.ERROR)
    EYE3D_OK = True
except ImportError:
    EYE3D_OK = False

try:
    from pyradios import RadioBrowser
    PYRADIOS_OK = True
except ImportError:
    PYRADIOS_OK = False

# ============================================================================
# STALE
# ============================================================================
VIRTUAL_SINK   = "carbon_monitor"
CHAIN_FILE     = "carbon_chain_presets.json"

CHAIN_ORDER = [
    "phase_inv","gate","compressor","expander",
    "hi_pass","lo_pass","notch",
    "panorama","karaoke","chorus","reverb","stereo_fx","trim",
]

# label, accent color, {param: (min,max,default,scale,unit)}
CHAIN_DEFS = {
    "phase_inv":  ("Phase Inv L/R", "#FF5555", {}),
    "gate":       ("Gate",          "#FFAA00",
                   {"threshold":(0.0,1.0,0.05,1000,""),
                    "ratio":    (1.0,20.0,5.0,10,":1")}),
    "compressor": ("Comp",          "#FFD700",
                   {"threshold":(0.0,1.0,0.5,1000,""),
                    "ratio":    (1.0,20.0,2.0,10,":1")}),
    "expander":   ("Expand",        "#AAFF44",
                   {"threshold":(0.0,1.0,0.3,1000,""),
                    "ratio":    (1.0,10.0,1.5,10,":1")}),
    "hi_pass":    ("Hi-Pass",       "#44FFAA",
                   {"cutoff":(20.0,2000.0,80.0,1,"Hz")}),
    "lo_pass":    ("Lo-Pass",       "#44FFFF",
                   {"cutoff":(1000.0,20000.0,16000.0,1,"Hz")}),
    "notch":      ("Notch",         "#4488FF",
                   {"lower-frequency":(20.0,20000.0,900.0,1,"Hz"),
                    "upper-frequency":(20.0,20000.0,1100.0,1,"Hz")}),
    "panorama":   ("Pan",           "#8844FF",
                   {"panorama":(-1.0,1.0,0.0,100,"")}),
    "karaoke":    ("Karaoke",       "#FF44FF",
                   {"level":(0.0,1.0,1.0,100,""),
                    "mono-level":(0.0,1.0,1.0,100,"")}),
    "chorus":     ("Chorus",        "#FF44AA",
                   {"delay":(1000000,40000000,10000000,1,"ns"),
                    "intensity":(0.0,1.0,0.4,100,""),
                    "feedback":(0.0,0.9,0.0,100,"")}),
    "reverb":     ("Reverb",        "#FF6644",
                   {"room-size":(0.0,1.0,0.3,100,""),
                    "damping":(0.0,1.0,0.5,100,""),
                    "level":(0.0,1.0,0.2,100,"")}),
    "stereo_fx":  ("Stereo",        "#44FF88",
                   {"stereo":(0.0,1.0,1.0,100,"x")}),
    "trim":       ("Trim",          "#AAAAFF",
                   {"amplification":(0.0,4.0,1.0,100,"x")}),
}

# plugin, bypass-neutral props, {gst_prop:(bypass_val, ui_param)}
CHAIN_GST = {
    "phase_inv":  ("audioinvert",
                   {"degree":0.0},
                   {"degree":(0.0,"degree")}),
    "gate":       ("audiodynamic",
                   {"characteristics":"hard-knee","mode":"compressor",
                    "threshold":1.0,"ratio":1.0},
                   {"threshold":(1.0,"threshold"),"ratio":(1.0,"ratio")}),
    "compressor": ("audiodynamic",
                   {"characteristics":"soft-knee","mode":"compressor",
                    "threshold":1.0,"ratio":1.0},
                   {"threshold":(1.0,"threshold"),"ratio":(1.0,"ratio")}),
    "expander":   ("audiodynamic",
                   {"characteristics":"soft-knee","mode":"expander",
                    "threshold":0.0,"ratio":1.0},
                   {"threshold":(0.0,"threshold"),"ratio":(1.0,"ratio")}),
    "hi_pass":    ("audiocheblimit",
                   {"cutoff":20.0,"mode":"high-pass","poles":4},
                   {"cutoff":(20.0,"cutoff")}),
    "lo_pass":    ("audiocheblimit",
                   {"cutoff":20000.0,"mode":"low-pass","poles":4},
                   {"cutoff":(20000.0,"cutoff")}),
    "notch":      ("audiowsincband",
                   {"lower-frequency":900.0,"upper-frequency":1100.0,
                    "mode":"band-reject","window":"blackman"},
                   {"lower-frequency":(20.0,"lower-frequency"),
                    "upper-frequency":(20000.0,"upper-frequency")}),
    "panorama":   ("audiopanorama",
                   {"panorama":0.0},
                   {"panorama":(0.0,"panorama")}),
    "karaoke":    ("audiokaraoke",
                   {"level":0.0,"mono-level":0.0},
                   {"level":(0.0,"level"),"mono-level":(0.0,"mono-level")}),
    "chorus":     ("audioecho",
                   {"delay":1,"intensity":0.0,"feedback":0.0},
                   {"delay":(1,"delay"),"intensity":(0.0,"intensity"),
                    "feedback":(0.0,"feedback")}),
    "reverb":     ("freeverb",
                   {"room-size":0.0,"level":0.0,"damping":0.5},
                   {"room-size":(0.0,"room-size"),"damping":(0.5,"damping"),
                    "level":(0.0,"level")}),
    "stereo_fx":  ("stereo",{"stereo":1.0},{"stereo":(1.0,"stereo")}),
    "trim":       ("audioamplify",{"amplification":1.0},
                   {"amplification":(1.0,"amplification")}),
}

EQ_PRESETS = {
    "Flat":[0]*10,"Club":[0,0,2,3,3,3,2,0,0,0],
    "Bass":[6,5,4,2,0,0,0,0,0,0],"Treble":[0,0,0,0,0,1,3,5,5,8],
    "Rock":[4,3,1,-1,-2,-2,0,1,3,4],"Techno":[4,3,0,-2,-3,-2,0,2,4,4],
    "Vocal":[-2,-3,-3,1,3,3,3,1,0,-1],
}

# ============================================================================
# MULTIBAND LIMITER — definicja pasm
# ============================================================================
# Każde pasmo ma:
#   name      — etykieta w UI
#   color     — kolor paska metra
#   filter    — "lo"/"hi"/"band" — jaki filtr przed limiterem
#   f_lo/f_hi — granice pasma Hz (dla band: oba; dla lo: f_hi; dla hi: f_lo)
#   threshold — domyślny próg limitera (0.0..1.0, wartość amplitudy)
#   ratio     — domyślny ratio limitera
#   attack_ms / release_ms — szybkość (symulowane przez audiodynamic)

MBLIMIT_BANDS = [
    {"name":"SUB",    "color":"#FF3333", "filter":"lo",   "f_lo":None, "f_hi":80.0,
     "threshold":0.85, "ratio":4.0},
    {"name":"BASS",   "color":"#FF8800", "filter":"band", "f_lo":80.0, "f_hi":250.0,
     "threshold":0.80, "ratio":3.0},
    {"name":"LO-MID", "color":"#FFFF00", "filter":"band", "f_lo":250.0,"f_hi":1500.0,
     "threshold":0.75, "ratio":2.5},
    {"name":"HI-MID", "color":"#88FF00", "filter":"band", "f_lo":1500.0,"f_hi":6000.0,
     "threshold":0.75, "ratio":2.5},
    {"name":"AIR",    "color":"#00FFCC", "filter":"hi",   "f_lo":6000.0,"f_hi":None,
     "threshold":0.70, "ratio":3.0},
]


BUILTIN_SCENES = {
    # Filozofia: minimalna ingerencja, przezroczystość sygnału.
    # Każda scena to subtelna korekcja — nie "efekt", a punkt startowy.
    "🎙 Podcast": {
        "meta": {"icon": "🎙", "desc": "Mowa — lekka korekcja, naturalny głos"},
        "volume": 78,
        "chain": {
            "gate":       {"enabled": True,  "params": {"threshold": 0.02, "ratio": 3.0}},
            "compressor": {"enabled": True,  "params": {"threshold": 0.75, "ratio": 2.0}},
            "hi_pass":    {"enabled": True,  "params": {"cutoff": 80.0}},
        },
        "eq":      {"preset": "Vocal",   "bands": [-1,-2,-2,0,2,2,1,0,0,0]},
        "tape":    {"active": False, "drive": 10, "warmth": 15, "comp": 5},
        "spatial": {"active": True,  "width": 5,  "delay": 4,  "saturation": 10},
        "phantom": {"active": True,  "preset": "Podcast Mono", "mode": "haas",      "width": 10, "delay": 8,  "blend": 0},
        "limiter": {
            "POST_FX": {"enabled": True,
                        "bands": [{"thr":0.95,"ratio":2.0},{"thr":0.92,"ratio":1.8},
                                  {"thr":0.90,"ratio":1.5},{"thr":0.90,"ratio":1.5},
                                  {"thr":0.92,"ratio":2.0}]},
        },
    },
    "📺 TV Audio": {
        "meta": {"icon": "📺", "desc": "TV — wyrównanie dynamiki, subtelne stereo"},
        "volume": 80,
        "chain": {
            "gate":       {"enabled": True,  "params": {"threshold": 0.02, "ratio": 2.5}},
            "compressor": {"enabled": True,  "params": {"threshold": 0.70, "ratio": 2.5}},
            "hi_pass":    {"enabled": True,  "params": {"cutoff": 60.0}},
        },
        "eq":      {"preset": "Flat",    "bands": [0,0,0,0,0,0,0,0,0,0]},
        "tape":    {"active": False, "drive": 8,  "warmth": 10, "comp": 5},
        "spatial": {"active": True,  "width": 5,  "delay": 5,  "saturation": 10},
        "phantom": {"active": True,  "preset": "TV Wide",  "mode": "haas",  "width": 12, "delay": 6,  "blend": 0},
        "limiter": {
            "POST_FX": {"enabled": True,
                        "bands": [{"thr":0.93,"ratio":2.5},{"thr":0.90,"ratio":2.0},
                                  {"thr":0.90,"ratio":1.8},{"thr":0.90,"ratio":1.8},
                                  {"thr":0.93,"ratio":2.5}]},
        },
    },
    "🎵 Music Hi-Fi": {
        "meta": {"icon": "🎵", "desc": "Muzyka — czysto, przezroczyście, bez efektów"},
        "volume": 80,
        "chain": {},
        "eq":      {"preset": "Flat",    "bands": [0]*10},
        "tape":    {"active": False, "drive": 5,  "warmth": 5,  "comp": 5},
        "spatial": {"active": False, "width": 5,  "delay": 0,  "saturation": 10},
        "phantom": {"active": False, "preset": "Off", "mode": "off", "width": 5, "delay": 0, "blend": 0},
        "limiter": {
            "POST_FX": {"enabled": True,
                        "bands": [{"thr":0.98,"ratio":1.2},{"thr":0.98,"ratio":1.2},
                                  {"thr":0.98,"ratio":1.2},{"thr":0.98,"ratio":1.2},
                                  {"thr":0.98,"ratio":1.2}]},
        },
    },
    "🎸 Rock": {
        "meta": {"icon": "🎸", "desc": "Rock — lekki punch, subtelna korekcja basu"},
        "volume": 78,
        "chain": {
            "compressor": {"enabled": True,  "params": {"threshold": 0.70, "ratio": 2.5}},
            "hi_pass":    {"enabled": True,  "params": {"cutoff": 40.0}},
        },
        "eq":      {"preset": "Rock",    "bands": [2,1,0,-1,-1,0,0,0,1,2]},
        "tape":    {"active": True,  "drive": 18, "warmth": 15, "comp": 10},
        "spatial": {"active": True,  "width": 5,  "delay": 5,  "saturation": 10},
        "phantom": {"active": False, "preset": "Studio", "mode": "crossfeed", "width": 5, "delay": 2, "blend": 5},
        "limiter": {
            "POST_FX": {"enabled": True,
                        "bands": [{"thr":0.92,"ratio":2.5},{"thr":0.90,"ratio":2.5},
                                  {"thr":0.92,"ratio":2.0},{"thr":0.92,"ratio":2.0},
                                  {"thr":0.90,"ratio":2.5}]},
        },
    },
    "🌙 Night Mode": {
        "meta": {"icon": "🌙", "desc": "Nocny — ochrona dynamiki, spokojne brzmienie"},
        "volume": 60,
        "chain": {
            "gate":       {"enabled": True,  "params": {"threshold": 0.02, "ratio": 2.0}},
            "compressor": {"enabled": True,  "params": {"threshold": 0.60, "ratio": 4.0}},
            "lo_pass":    {"enabled": True,  "params": {"cutoff": 16000.0}},
        },
        "eq":      {"preset": "Flat",    "bands": [1,1,0,0,0,0,0,0,-1,-1]},
        "tape":    {"active": False, "drive": 5,  "warmth": 20, "comp": 8},
        "spatial": {"active": False, "width": 5,  "delay": 0,  "saturation": 10},
        "phantom": {"active": False, "preset": "Headphones", "mode": "crossfeed", "width": 5, "delay": 0, "blend": 8},
        "limiter": {
            "POST_FX": {"enabled": True,
                        "bands": [{"thr":0.75,"ratio":4.0},{"thr":0.72,"ratio":3.5},
                                  {"thr":0.75,"ratio":3.0},{"thr":0.75,"ratio":3.0},
                                  {"thr":0.72,"ratio":4.0}]},
        },
    },
    "📻 Radio": {
        "meta": {"icon": "📻", "desc": "Radio — wyrównanie pasma, lekka korekcja"},
        "volume": 80,
        "chain": {
            "gate":       {"enabled": True,  "params": {"threshold": 0.02, "ratio": 2.5}},
            "compressor": {"enabled": True,  "params": {"threshold": 0.70, "ratio": 3.0}},
            "hi_pass":    {"enabled": True,  "params": {"cutoff": 80.0}},
            "lo_pass":    {"enabled": True,  "params": {"cutoff": 18000.0}},
        },
        "eq":      {"preset": "Vocal",   "bands": [-1,-1,-1,0,1,1,0,0,0,0]},
        "tape":    {"active": False, "drive": 8,  "warmth": 10, "comp": 5},
        "spatial": {"active": True,  "width": 5,  "delay": 3,  "saturation": 10},
        "phantom": {"active": True,  "preset": "Studio", "mode": "crossfeed", "width": 5, "delay": 2, "blend": 5},
        "limiter": {
            "POST_FX": {"enabled": True,
                        "bands": [{"thr":0.93,"ratio":2.0},{"thr":0.92,"ratio":2.0},
                                  {"thr":0.92,"ratio":1.8},{"thr":0.92,"ratio":1.8},
                                  {"thr":0.93,"ratio":2.0}]},
        },
    },
    "✨ Custom": {
        "meta": {"icon": "✨", "desc": "Twoje własne ustawienia"},
        "volume": 80,
        "chain": {},
        "eq":      {"preset": "Flat", "bands": [0]*10},
        "tape":    {"active": False, "drive": 10, "warmth": 10, "comp": 5},
        "spatial": {"active": False, "width": 5,  "delay": 0,  "saturation": 10},
        "phantom": {"active": False, "preset": "Off", "mode": "off", "width": 5, "delay": 0, "blend": 0},
        "limiter": {},
    },
}

SCENE_FILE = "carbon_scenes.json"


class SceneManager:
    """
    Serializuje i deserializuje stan całej aplikacji.
    Operuje na żywych widgetach — nie na GST bezpośrednio.
    """

    def __init__(self, app_ref):
        self.app   = app_ref          # referencja do CarbonPhaserPlayer
        self.scenes = {}              # name -> scene dict
        self.current = None           # nazwa aktywnej sceny
        self._load()

    # ── Persystencja ─────────────────────────────────────────────────────────

    def _load(self):
        self.scenes = dict(BUILTIN_SCENES)
        try:
            with open(SCENE_FILE, 'r') as f:
                user = json.load(f)
                self.scenes.update(user)   # user override/extends builtins
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save(self):
        # Zapisz tylko sceny nie-builtin lub zmodyfikowane
        user = {n: s for n, s in self.scenes.items()
                if n not in BUILTIN_SCENES or s != BUILTIN_SCENES.get(n)}
        try:
            with open(SCENE_FILE, 'w') as f:
                json.dump(user, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"  [Scenes] save error: {e}")

    # ── Snapshot (czytanie aktualnego stanu aplikacji) ────────────────────────

    def snapshot(self, name, icon="✨", desc=""):
        """Zapisuje aktualny stan aplikacji jako scenę o podanej nazwie."""
        app = self.app
        s = {
            "meta":    {"icon": icon, "desc": desc,
                        "created": self.scenes.get(name, {}).get(
                            "meta", {}).get("created", ""),
                        "modified": ""},
            "volume":  getattr(app, "vol_sl", None) and
                       app.vol_sl.value() or 80,
            "chain":   self._snap_chain(),
            "eq":      self._snap_eq(),
            "tape":    self._snap_tape(),
            "spatial": self._snap_spatial(),
            "phantom": self._snap_phantom(),
            "limiter": self._snap_limiter(),
        }
        self.scenes[name] = s
        self._save()
        print(f"  [Scenes] snapshot saved: {name!r}")
        return s

    def _snap_chain(self):
        cp = self.app.chain_panel
        return {mid: w.get_state() for mid, w in cp.mws.items()}

    def _snap_eq(self):
        ew = self.app.eqw
        return {
            "preset": ew.cb.currentText() if hasattr(ew, "cb") else "Flat",
            "bands":  [sl.value() for sl in ew.sl] if hasattr(ew, "sl") else [0]*10,
        }

    def _snap_tape(self):
        tw = self.app.tape_sim
        dials = {n: d.value() for n, d in zip(
            ["drive","warmth","comp"],
            [d for d, _ in tw._dials]) if tw._dials} if hasattr(tw, "_dials") else {}
        return {
            "active": tw.byp.isChecked() if hasattr(tw, "byp") else False,
            **dials,
        }

    def _snap_spatial(self):
        sw = self.app.tape_spatial
        # SpatialFXWidget przechowuje suwaki w _sliders dict lub _sl
        sliders = {}
        if hasattr(sw, "_sl"):
            for k, sl in sw._sl.items():
                sliders[k] = sl.value()
        return {"active": getattr(sw, "_active", False), **sliders}

    def _snap_phantom(self):
        pw = getattr(self.app, "phantom_stereo", None)
        if pw and hasattr(pw, "get_state"):
            return pw.get_state()
        return {}

    def _snap_limiter(self):
        result = {}
        router = getattr(self.app, "limiter_router", None)
        if not router:
            return result
        for pid in router.registered_points():
            mbl = router.get(pid)
            if mbl:
                result[pid] = {
                    "enabled": mbl._injected,
                    "bands": [
                        {"thr": node.band_cfg["threshold"],
                         "ratio": node.band_cfg["ratio"]}
                        for node in mbl.nodes
                    ],
                }
        return result

    # ── Restore (aplikowanie sceny) ───────────────────────────────────────────

    def apply(self, name, fade_ms=150):
        """
        Aplikuje scenę o podanej nazwie.
        fade_ms: czas dip głośności podczas zmiany (0 = natychmiastowe)
        """
        s = self.scenes.get(name)
        if not s:
            print(f"  [Scenes] nieznana scena: {name!r}")
            return
        self.current = name
        print(f"  [Scenes] applying: {name!r}")

        if fade_ms > 0:
            self._fade_apply(s, fade_ms)
        else:
            self._do_apply(s)

    def _fade_apply(self, s, fade_ms):
        """Dip volume → apply → restore volume."""
        app = self.app
        orig_vol = app.vol_sl.value()
        target_vol = s.get("volume", orig_vol)

        def step1():
            # Fade down
            app.vol_sl.setValue(0)
            QTimer.singleShot(fade_ms, step2)

        def step2():
            # Apply all settings
            self._do_apply(s)
            # Fade up to target
            QTimer.singleShot(30, lambda: app.vol_sl.setValue(target_vol))

        step1()

    def _do_apply(self, s):
        app = self.app

        # Volume
        vol = s.get("volume", 80)
        if hasattr(app, "vol_sl"):
            app.vol_sl.blockSignals(True)
            app.vol_sl.setValue(vol)
            app.vol_sl.blockSignals(False)
            app._vol(vol)

        # Chain DSP
        self._apply_chain(s.get("chain", {}))

        # EQ
        self._apply_eq(s.get("eq", {}))

        # Tape
        self._apply_tape(s.get("tape", {}))

        # Spatial
        self._apply_spatial(s.get("spatial", {}))

        # Phantom Stereo
        self._apply_phantom(s.get("phantom", {}))

        # Limiter
        self._apply_limiter(s.get("limiter", {}))

    def _apply_chain(self, chain_s):
        cp = self.app.chain_panel
        for mid, state in chain_s.items():
            w = cp.mws.get(mid)
            if w:
                w.set_state(state)
        # Moduły nie wymienione w scenie — zostają jak są (selective restore)

    def _apply_eq(self, eq_s):
        ew = self.app.eqw
        bands = eq_s.get("bands")
        if bands and hasattr(ew, "sl"):
            for i, v in enumerate(bands[:len(ew.sl)]):
                ew.sl[i].blockSignals(True)
                ew.sl[i].setValue(int(v))
                ew.sl[i].blockSignals(False)
            # Wymuś aktualizację GST
            if hasattr(ew, "_apply_all"):
                ew._apply_all()
            elif hasattr(ew, "proc"):
                ew.proc.set_all_base(bands)

    def _apply_tape(self, tape_s):
        tw = self.app.tape_sim
        if not tape_s or not hasattr(tw, "_dials"):
            return
        active = tape_s.get("active", False)
        if hasattr(tw, "byp"):
            tw.byp.setChecked(active)
        vals = [tape_s.get("drive"), tape_s.get("warmth"), tape_s.get("comp")]
        for (d, fn), val in zip(tw._dials, vals):
            if val is not None:
                d.blockSignals(True)
                d.setValue(int(val))
                d.blockSignals(False)
                fn(int(val))

    def _apply_spatial(self, spatial_s):
        sw = self.app.tape_spatial
        if not spatial_s:
            return
        active = spatial_s.get("active", False)
        if hasattr(sw, "_active_btn"):
            sw._active_btn.setChecked(active)
        if hasattr(sw, "_sl"):
            for k, sl in sw._sl.items():
                if k in spatial_s:
                    sl.blockSignals(True)
                    sl.setValue(int(spatial_s[k]))
                    sl.blockSignals(False)

    def _apply_phantom(self, phantom_s):
        pw = getattr(self.app, "phantom_stereo", None)
        if pw and phantom_s and hasattr(pw, "set_state"):
            pw.set_state(phantom_s)

    def _apply_limiter(self, limiter_s):
        router = getattr(self.app, "limiter_router", None)
        rw = getattr(self.app, "limiter_router_widget", None)
        if not router or not limiter_s:
            return
        for pid, pstate in limiter_s.items():
            mbl = router.get(pid)
            if not mbl:
                continue
            # Ustaw threshold/ratio per pasmo
            bands = pstate.get("bands", [])
            for i, bd in enumerate(bands[:len(mbl.nodes)]):
                mbl.set_band_threshold(i, bd.get("thr", 0.8))
                mbl.set_band_ratio(i, bd.get("ratio", 3.0))
            # Włącz/wyłącz
            en = pstate.get("enabled", False)
            router.enable(pid, en)
            # Sync checkbox w RouterWidget
            if rw and pid in rw._point_widgets:
                cb = rw._point_widgets[pid]["cb"]
                cb.blockSignals(True)
                cb.setChecked(en)
                cb.blockSignals(False)
        # Wyłącz punkty których nie ma w scenie
        for pid in router.registered_points():
            if pid not in limiter_s and router.get(pid)._injected:
                router.enable(pid, False)
                if rw and pid in rw._point_widgets:
                    cb = rw._point_widgets[pid]["cb"]
                    cb.blockSignals(True); cb.setChecked(False); cb.blockSignals(False)

    # ── Zarządzanie scenami ───────────────────────────────────────────────────

    def delete(self, name):
        if name in BUILTIN_SCENES:
            print(f"  [Scenes] nie można usunąć wbudowanej sceny: {name!r}")
            return False
        self.scenes.pop(name, None)
        self._save()
        return True

    def rename(self, old, new):
        if old in BUILTIN_SCENES:
            return False
        if new in self.scenes:
            return False
        self.scenes[new] = self.scenes.pop(old)
        self._save()
        return True

    def list_scenes(self):
        return list(self.scenes.keys())


# ============================================================================
# GLOBAL SCENE BAR WIDGET
# ============================================================================
class SceneBar(QWidget):
    """
    Poziomy pasek na górze UI z przełącznikiem scen.
    Zawiera:
    - Dropdown ze scenami (lub przyciski dla szybkich presetów)
    - Aktywna scena podświetlona
    - Przyciski: Save As, Delete, [modified indicator]
    - Szybkie przyciski dla pierwszych 6 scen
    """
    scene_changed = pyqtSignal(str)   # emitowane po zmianie sceny

    SS = """
        QWidget#SceneBar {
            background: #0A0A0E;
            border-bottom: 1px solid #1E1E2A;
        }
        QPushButton.scene-btn {
            background: #12121A;
            color: #666;
            border: 1px solid #1E1E2A;
            border-radius: 3px;
            padding: 3px 10px;
            font-size: 10px;
            font-weight: bold;
        }
        QPushButton.scene-btn:hover {
            border-color: #3A3A55;
            color: #AAA;
        }
        QPushButton.scene-btn:checked {
            background: #1A1A30;
            color: #FFFFFF;
            border-color: #5555AA;
            border-bottom: 2px solid #8888FF;
        }
    """

    ACCENT_COLORS = [
        "#FF6644", "#FFAA00", "#44FFAA", "#4488FF",
        "#FF44FF", "#00FFCC", "#FFFF44", "#FF4488",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SceneBar")
        self.setStyleSheet(self.SS)
        self.setFixedHeight(42)
        self.manager: SceneManager = None
        self._btns = {}           # name -> QPushButton
        self._current = None
        self._modified = False
        self._build()

    def set_manager(self, manager: SceneManager):
        self.manager = manager
        self._rebuild_buttons()

    def _build(self):
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 4, 8, 4); h.setSpacing(4)

        # Label
        lbl = QLabel("SCENE")
        lbl.setStyleSheet("color:#444;font-size:9px;font-weight:bold;letter-spacing:2px")
        lbl.setFixedWidth(44)
        h.addWidget(lbl)

        # Kontener na przyciski scen (scroll jeśli za dużo)
        self._btn_area = QWidget()
        self._btn_layout = QHBoxLayout(self._btn_area)
        self._btn_layout.setContentsMargins(0,0,0,0); self._btn_layout.setSpacing(3)
        h.addWidget(self._btn_area, 1)

        # Separator
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color:#222"); h.addWidget(sep)

        # Modified indicator
        self._mod_lbl = QLabel("●")
        self._mod_lbl.setStyleSheet("color:#333;font-size:8px")
        self._mod_lbl.setToolTip("Niezapisane zmiany")
        self._mod_lbl.setFixedWidth(12)
        h.addWidget(self._mod_lbl)

        # Save current
        self._save_btn = QPushButton("💾 Zapisz")
        self._save_btn.setStyleSheet(
            "QPushButton{background:#0A1A0A;color:#44AA44;border:1px solid #1A3A1A;"
            "padding:3px 8px;border-radius:3px;font-size:10px}"
            "QPushButton:hover{border-color:#44AA44}")
        self._save_btn.clicked.connect(self._save_current)
        self._save_btn.setFixedWidth(72)
        h.addWidget(self._save_btn)

        # Save As (nowa scena)
        self._saveas_btn = QPushButton("+ Nowa")
        self._saveas_btn.setStyleSheet(
            "QPushButton{background:#0A0A1A;color:#4444AA;border:1px solid #1A1A3A;"
            "padding:3px 8px;border-radius:3px;font-size:10px}"
            "QPushButton:hover{border-color:#4444AA}")
        self._saveas_btn.clicked.connect(self._save_as)
        self._saveas_btn.setFixedWidth(60)
        h.addWidget(self._saveas_btn)

        # Delete
        self._del_btn = QPushButton("🗑")
        self._del_btn.setStyleSheet(
            "QPushButton{background:#1A0A0A;color:#AA4444;border:1px solid #3A1A1A;"
            "padding:3px 6px;border-radius:3px;font-size:10px}"
            "QPushButton:hover{border-color:#AA4444}")
        self._del_btn.setToolTip("Usuń scenę (tylko użytkownika)")
        self._del_btn.clicked.connect(self._delete_current)
        self._del_btn.setFixedWidth(28)
        h.addWidget(self._del_btn)

    def _rebuild_buttons(self):
        # Wyczyść stare przyciski
        for btn in self._btns.values():
            btn.setParent(None)
        self._btns.clear()
        while self._btn_layout.count():
            self._btn_layout.takeAt(0)

        scenes = self.manager.list_scenes() if self.manager else []
        for i, name in enumerate(scenes):
            cfg = self.manager.scenes.get(name, {})
            meta = cfg.get("meta", {})
            icon = meta.get("icon", "")
            color = self.ACCENT_COLORS[i % len(self.ACCENT_COLORS)]
            is_builtin = name in BUILTIN_SCENES

            btn = QPushButton(f"{icon} {name.split(' ',1)[-1] if icon else name}")
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #10101A;
                    color: #555;
                    border: 1px solid #1E1E2A;
                    border-radius: 3px;
                    padding: 3px 10px;
                    font-size: 10px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    border-color: {color}55;
                    color: #888;
                }}
                QPushButton:checked {{
                    background: #15151F;
                    color: {color};
                    border-color: {color};
                    border-bottom: 2px solid {color};
                }}
            """)
            btn.clicked.connect(lambda checked, n=name: self._select(n))
            btn.setToolTip(meta.get("desc", ""))
            self._btns[name] = btn
            self._btn_layout.addWidget(btn)

        self._btn_layout.addStretch()

    def _select(self, name):
        if not self.manager:
            return
        if name == self._current:
            # Kliknięcie aktywnej sceny — odznacz i wróć
            return
        self._current = name
        # Odznacz pozostałe
        for n, b in self._btns.items():
            b.blockSignals(True)
            b.setChecked(n == name)
            b.blockSignals(False)
        self.manager.apply(name, fade_ms=120)
        self.set_modified(False)
        self.scene_changed.emit(name)

    def set_modified(self, mod=True):
        """Zaznacz że bieżąca scena ma niezapisane zmiany."""
        self._modified = mod
        self._mod_lbl.setStyleSheet(
            f"color:{'#FFAA00' if mod else '#333'};font-size:8px")

    def _save_current(self):
        if not self.manager or not self._current:
            return
        self.manager.snapshot(self._current)
        self.set_modified(False)

    def _save_as(self):
        if not self.manager:
            return
        name, ok = QInputDialog.getText(
            self, "Nowa scena", "Nazwa sceny:",
            text=f"Moja scena {len(self.manager.scenes)+1}")
        if not ok or not name.strip():
            return
        name = name.strip()
        self.manager.snapshot(name, icon="✨", desc="Własna scena")
        self._rebuild_buttons()
        self._select(name)

    def _delete_current(self):
        if not self.manager or not self._current:
            return
        if self._current in BUILTIN_SCENES:
            # Nie usuwaj, ale zresetuj do builtin
            self.manager.scenes[self._current] = dict(BUILTIN_SCENES[self._current])
            self.manager._save()
            self.set_modified(False)
            return
        from PyQt6.QtWidgets import QMessageBox
        r = QMessageBox.question(self, "Usuń scenę",
            f"Usunąć scenę {self._current!r}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            self.manager.delete(self._current)
            self._current = None
            self._rebuild_buttons()

    def notify_change(self):
        """Wywołaj gdy użytkownik zmieni jakikolwiek parametr — zaznacza jako modified."""
        if self._current:
            self.set_modified(True)


# ============================================================================
# MULTIBAND LIMITER — definicja pasm
# ============================================================================
# Każde pasmo ma:
#   name      — etykieta w UI
#   color     — kolor paska metra
#   filter    — "lo"/"hi"/"band" — jaki filtr przed limiterem
#   f_lo/f_hi — granice pasma Hz (dla band: oba; dla lo: f_hi; dla hi: f_lo)
#   threshold — domyślny próg limitera (0.0..1.0, wartość amplitudy)
#   ratio     — domyślny ratio limitera
#   attack_ms / release_ms — szybkość (symulowane przez audiodynamic)

MBLIMIT_BANDS = [
    {"name":"SUB",    "color":"#FF3333", "filter":"lo",   "f_lo":None, "f_hi":80.0,
     "threshold":0.85, "ratio":4.0},
    {"name":"BASS",   "color":"#FF8800", "filter":"band", "f_lo":80.0, "f_hi":250.0,
     "threshold":0.80, "ratio":3.0},
    {"name":"LO-MID", "color":"#FFFF00", "filter":"band", "f_lo":250.0,"f_hi":1500.0,
     "threshold":0.75, "ratio":2.5},
    {"name":"HI-MID", "color":"#88FF00", "filter":"band", "f_lo":1500.0,"f_hi":6000.0,
     "threshold":0.75, "ratio":2.5},
    {"name":"AIR",    "color":"#00FFCC", "filter":"hi",   "f_lo":6000.0,"f_hi":None,
     "threshold":0.70, "ratio":3.0},
]


class BandLimiterNode:
    """
    Samowystarczalny węzeł limitera jednopasmowego.
    Można go wstrzyknąć między dowolne dwa elementy GST w pipeline.

    Wewnętrzna struktura jednej instancji:
        [sink_pad] → audioconvert → filtr_pasmowy → audiodynamic(limiter)
                   → level → audioconvert → [src_pad]

    Użycie:
        node = BandLimiterNode(pipeline, "band0", band_cfg, bus_callback)
        node.inject(upstream_el, downstream_el)
        node.set_threshold(0.8)
        node.set_ratio(3.0)
        node.set_enabled(True)
        # node.peak_db, node.rms_db aktualizowane przez callback
    """

    def __init__(self, pipeline, name, band_cfg, on_level=None):
        """
        pipeline  — Gst.Pipeline do którego należą elementy
        name      — unikalna nazwa (prefix dla elementów GST)
        band_cfg  — słownik z MBLIMIT_BANDS[i]
        on_level  — callback(node, rms_db, peak_db) wywoływany z GST bus
        """
        self.pipeline   = pipeline
        self.name       = name
        self.band_cfg   = band_cfg
        self.on_level   = on_level
        self.enabled    = True
        self.peak_db    = -80.0
        self.rms_db     = -80.0
        self.peak_l_db  = -80.0
        self.peak_r_db  = -80.0
        self.rms_l_db   = -80.0
        self.rms_r_db   = -80.0
        self._upstream   = None
        self._downstream = None
        self._injected   = False

        # Buduj elementy GST
        n = name
        self._conv_in  = self._mk("audioconvert",  f"{n}_conv_in")
        # Caps filter wymusza F32LE przez cały łańcuch pasm
        # Eliminuje trzeszczenie z re-negocjacji formatu między audiocheblimit/audiodynamic
        self._caps_f32 = self._mk_caps(f"{n}_capsf32",
            "audio/x-raw,format=F32LE")
        self._filter   = self._build_filter(band_cfg, n)
        self._limiter  = self._mk("audiodynamic",  f"{n}_limiter", {
            "characteristics": "hard-knee",
            "mode":            "compressor",
            "threshold":       float(band_cfg["threshold"]),
            "ratio":           float(band_cfg["ratio"]),
        })
        self._level    = self._mk("level", f"{n}_level", {
            "interval":        50_000_000,   # 50ms → 20 odczytów/s
            "peak-ttl":        300_000_000,
            "peak-falloff":    20.0,
            "post-messages":   True,
        })
        # conv_out usunięty — mixer po stronie MultibandLimiter robi własną konwersję
        # Zachowujemy dla kompatybilności z _all_els() i inject/eject
        self._conv_out = self._mk("audioconvert",  f"{n}_conv_out")

        # Dodaj do pipeline
        for el in [self._conv_in, self._caps_f32, self._filter, self._limiter,
                   self._level, self._conv_out]:
            if el: pipeline.add(el)

        # Połącz wewnętrznie
        self._link_internal()

    def _mk(self, plugin, name, props=None):
        el = Gst.ElementFactory.make(plugin, name)
        if not el:
            print(f"  [BandLimiter] Brak pluginu: {plugin} ({name})")
            return None
        if props:
            for k, v in props.items():
                try: el.set_property(k, float(v) if isinstance(v, float) else v)
                except Exception as e: print(f"    {name}.{k}: {e}")
        return el

    def _mk_caps(self, name, caps_str):
        """Tworzy capsfilter z podanym caps string."""
        el = Gst.ElementFactory.make("capsfilter", name)
        if el:
            el.set_property("caps", Gst.Caps.from_string(caps_str))
        return el

    def _build_filter(self, cfg, prefix):
        """Tworzy odpowiedni filtr pasmowy zależnie od typu pasma."""
        ftype = cfg["filter"]
        if ftype == "lo":
            # Low-pass — przepuszcza tylko niskie
            return self._mk("audiocheblimit", f"{prefix}_filt", {
                "mode": "low-pass", "cutoff": float(cfg["f_hi"]), "poles": 4,
            })
        elif ftype == "hi":
            # High-pass — przepuszcza tylko wysokie
            return self._mk("audiocheblimit", f"{prefix}_filt", {
                "mode": "high-pass", "cutoff": float(cfg["f_lo"]), "poles": 4,
            })
        else:
            # Band-pass przez dwa filtry kaskadowo: hi-pass → lo-pass
            # GStreamer nie ma band-pass w audiocheblimit, więc łączymy dwa
            # Zwracamy lo-pass jako "główny filtr", hi-pass osobno
            hi = self._mk("audiocheblimit", f"{prefix}_filt_hi", {
                "mode": "high-pass", "cutoff": float(cfg["f_lo"]), "poles": 4,
            })
            lo = self._mk("audiocheblimit", f"{prefix}_filt_lo", {
                "mode": "low-pass",  "cutoff": float(cfg["f_hi"]), "poles": 4,
            })
            if hi and lo: self.pipeline.add(hi)   # lo zwracamy, hi dodajemy osobno
            self._band_hi = hi   # zachowaj referencję
            self._band_lo = lo
            return lo            # _link_internal użyje _band_hi jeśli istnieje

    def _link_internal(self):
        """Łączy elementy wewnątrz węzła.
        conv_in → caps_f32(F32LE) → [hi_pass →] filter → limiter → level → conv_out
        caps_f32 wymusza format przed filtrem — eliminuje trzeszczenie.
        """
        def lnk(a, b):
            if a and b:
                if not a.link(b):
                    print(f"  [BandLimiter:{self.name}] link fail: "
                          f"{a.get_name()}→{b.get_name()}")

        # conv_in → F32LE
        lnk(self._conv_in, self._caps_f32)

        hi = getattr(self, "_band_hi", None)
        if hi:
            # band: caps_f32 → hi_pass → lo_pass → limiter → level → conv_out
            lnk(self._caps_f32, hi)
            lnk(hi, self._filter)   # _filter = lo_pass
        else:
            # lo/hi: caps_f32 → filtr → limiter → level → conv_out
            lnk(self._caps_f32, self._filter)

        lnk(self._filter, self._limiter)
        lnk(self._limiter, self._level)
        lnk(self._level, self._conv_out)

    # ── Wstrzyknięcie w pipeline ─────────────────────────────────────────────

    def inject(self, upstream_el, downstream_el):
        """
        Wstrzykuje węzeł między upstream_el a downstream_el.
        Jeśli już wstrzyknięty — najpierw wysuwa się ze starego miejsca.
        """
        if self._injected:
            self.eject()

        self._upstream   = upstream_el
        self._downstream = downstream_el

        # Odepnij bezpośrednie połączenie upstream→downstream jeśli istnieje
        sp = upstream_el.get_static_pad("src")
        if sp and sp.is_linked():
            peer = sp.get_peer()
            if peer and peer.get_parent() == downstream_el:
                sp.unlink(peer)

        # Podłącz: upstream → conv_in ... conv_out → downstream
        if not upstream_el.link(self._conv_in):
            print(f"  [BandLimiter:{self.name}] inject: upstream→conv_in FAIL")
        if not self._conv_out.link(downstream_el):
            print(f"  [BandLimiter:{self.name}] inject: conv_out→downstream FAIL")

        # Synchronizuj stan z pipeline
        for el in self._all_els():
            el.sync_state_with_parent()

        self._injected = True
        print(f"  [BandLimiter:{self.name}] injected: "
              f"{upstream_el.get_name()} → [{self.name}] → {downstream_el.get_name()}")

    def eject(self):
        """Wysuwa węzeł z pipeline, przywraca bezpośrednie połączenie."""
        if not self._injected:
            return
        up, dn = self._upstream, self._downstream

        # Zatrzymaj elementy węzła
        for el in self._all_els():
            el.set_state(Gst.State.NULL)

        # Odepnij
        sp = up.get_static_pad("src")
        if sp and sp.is_linked():
            peer = sp.get_peer(); peer and sp.unlink(peer)

        sk = self._conv_in.get_static_pad("sink")
        if sk and sk.is_linked():
            peer = sk.get_peer(); peer and peer.unlink(sk)

        sp2 = self._conv_out.get_static_pad("src")
        if sp2 and sp2.is_linked():
            peer = sp2.get_peer(); peer and sp2.unlink(peer)

        sk2 = dn.get_static_pad("sink")
        if sk2 and sk2.is_linked():
            peer = sk2.get_peer(); peer and peer.unlink(sk2)

        # Przywróć bezpośrednie połączenie
        if not up.link(dn):
            print(f"  [BandLimiter:{self.name}] eject: restore link FAIL")

        self._injected = False
        print(f"  [BandLimiter:{self.name}] ejected")

    def _all_els(self):
        els = [self._conv_in, self._caps_f32, self._filter, self._limiter, self._level, self._conv_out]
        hi = getattr(self, "_band_hi", None)
        if hi: els.insert(1, hi)
        return [e for e in els if e]

    # ── Kontrola parametrów ─────────────────────────────────────────────────

    def set_threshold(self, v):
        """v: 0.0..1.0"""
        v = max(0.01, min(1.0, float(v)))
        if self._limiter: self._limiter.set_property("threshold", v)

    def set_ratio(self, v):
        """v: 1.0..20.0"""
        v = max(1.0, min(20.0, float(v)))
        if self._limiter: self._limiter.set_property("ratio", v)

    def set_enabled(self, en):
        self.enabled = en
        if en:
            if not self._injected and self._upstream and self._downstream:
                self.inject(self._upstream, self._downstream)
        else:
            if self._injected:
                self.eject()

    # ── Odczyt poziomu z GST bus ────────────────────────────────────────────

    def handle_level_message(self, structure):
        """
        Parsuje wiadomość 'level' z GST bus.
        Element 'level' wysyła rms/peak jako tablice (jedna wartość per kanał).
        Zachowujemy osobno L i R dla poprawnego pomiaru stereo.
        """
        try:
            rms_arr  = structure.get_value("rms")
            peak_arr = structure.get_value("peak")
            # rms_arr/peak_arr to listy dB per kanał: [L_db, R_db]
            if rms_arr and len(rms_arr) >= 1:
                self.rms_db   = max(rms_arr)           # ogólny (do AutoLevels)
                self.rms_l_db = rms_arr[0]
                self.rms_r_db = rms_arr[1] if len(rms_arr) > 1 else rms_arr[0]
            if peak_arr and len(peak_arr) >= 1:
                self.peak_db   = max(peak_arr)
                self.peak_l_db = peak_arr[0]
                self.peak_r_db = peak_arr[1] if len(peak_arr) > 1 else peak_arr[0]
            if self.on_level:
                self.on_level(self, self.rms_db, self.peak_db)
        except Exception as e:
            pass   # ciche — nie zaśmiecaj konsoli per każdą ramkę


class MultibandLimiter:
    """
    Zarządca N instancji BandLimiterNode.
    Wstrzykuje wszystkie między tymi samymi dwoma węzłami pipeline
    przez tee → [node0, node1, ...] → audiomixer.

    Schemat:
        upstream → tee → queue → BandNode0 → mixer
                       → queue → BandNode1 → mixer
                       → ...                       → downstream

    Użycie:
        mbl = MultibandLimiter(pipeline, "mbl_main", MBLIMIT_BANDS)
        mbl.inject(sp_echo, conv_out)
        mbl.set_enabled(True)
        mbl.set_band_threshold(2, 0.7)
        mbl.set_band_ratio(2, 3.0)
        # z on_bus: mbl.handle_bus_message(structure)
    """

    def __init__(self, pipeline, name_prefix, bands_cfg, on_level=None):
        self.pipeline     = pipeline
        self.prefix       = name_prefix
        self.on_level     = on_level
        self.enabled      = False
        self._injected    = False
        self._upstream    = None
        self._downstream  = None

        # AutoInsert state
        self._autoinsert_en     = False
        self._ai_threshold_db   = -12.0
        self._ai_hold_frames    = 4
        self._ai_release_frames = 20
        self._ai_above_frames   = 0
        self._ai_below_frames   = 0
        self._on_ai_state       = None

        # AutoLevels state
        self._autolevels_en = False
        self._al_headroom   = 1.05
        self._al_alpha      = 0.05
        self._al_min_thr    = 0.3
        self._al_max_thr    = 0.98
        self._on_al_update  = None

        # Tee do rozdzielenia sygnału
        self._tee   = Gst.ElementFactory.make("tee",        f"{name_prefix}_tee")
        self._mixer = Gst.ElementFactory.make("audiomixer", f"{name_prefix}_mix")
        # audiomixer: wyłącz normalizację — każde pasmo ma swój poziom
        if self._mixer:
            try: self._mixer.set_property("output-buffer-duration", 10_000_000)
            except: pass
        # caps_out po mikserze — stabilizuje format F32LE przed conv
        self._caps_out = Gst.ElementFactory.make("capsfilter", f"{name_prefix}_caps_out")
        if self._caps_out:
            self._caps_out.set_property("caps", Gst.Caps.from_string("audio/x-raw,format=F32LE"))
        self._conv  = Gst.ElementFactory.make("audioconvert", f"{name_prefix}_conv")
        for el in [self._tee, self._mixer, self._caps_out, self._conv]:
            if el: pipeline.add(el)

        # Kolejki między tee a każdym węzłem (tee wymaga queue)
        self._queues = []
        for i in range(len(bands_cfg)):
            q = Gst.ElementFactory.make("queue", f"{name_prefix}_q{i}")
            if q:
                q.set_property("max-size-buffers", 4)
                q.set_property("max-size-time", 0)
                q.set_property("max-size-bytes", 0)
                pipeline.add(q)
            self._queues.append(q)

        # Utwórz węzły BandLimiterNode
        self.nodes = []
        for i, cfg in enumerate(bands_cfg):
            node = BandLimiterNode(
                pipeline  = pipeline,
                name      = f"{name_prefix}_b{i}",
                band_cfg  = cfg,
                on_level  = self._on_node_level,
            )
            self.nodes.append(node)

        # Połącz wewnętrznie: tee→queue[i]→node[i].conv_in ... node[i].conv_out→mixer
        for i, (q, node) in enumerate(zip(self._queues, self.nodes)):
            if q and self._tee:
                if not self._tee.link(q):
                    print(f"  [MBL] tee→q{i} fail")
            if q and node._conv_in:
                if not q.link(node._conv_in):
                    print(f"  [MBL] q{i}→node fail")
            # node ma już połączone wewnętrzne elementy
            # podłącz conv_out węzła → mixer
            if node._conv_out and self._mixer:
                if not node._conv_out.link(self._mixer):
                    print(f"  [MBL] node{i}→mixer fail")

        # mixer → caps_out → conv → downstream
        if self._mixer and self._caps_out and self._conv:
            self._mixer.link(self._caps_out)
            self._caps_out.link(self._conv)
        elif self._mixer and self._conv:
            self._mixer.link(self._conv)

    def set_enabled(self, en):
        # _injected jest jedynym source of truth — enabled jest tylko alias
        if en == self._injected:
            return
        if en:
            if self._upstream and self._downstream:
                self.inject(self._upstream, self._downstream)
        else:
            self.eject()


    def inject(self, upstream_el, downstream_el):
        """Wstrzykuje cały multiband limiter między dwa elementy."""
        if self._injected:
            return   # już wstrzyknięty — ignoruj
        self._upstream   = upstream_el
        self._downstream = downstream_el

        # Odepnij bezpośrednie połączenie upstream→downstream
        sp = upstream_el.get_static_pad("src")
        if sp and sp.is_linked():
            peer = sp.get_peer()
            if peer: sp.unlink(peer)

        if not upstream_el.link(self._tee):
            print(f"  [MBL] upstream→tee FAIL")
            upstream_el.link(downstream_el)   # przywróć
            return
        if not self._conv.link(downstream_el):
            print(f"  [MBL] conv→downstream FAIL")
            upstream_el.unlink(self._tee)
            upstream_el.link(downstream_el)   # przywróć
            return

        for el in self._all_els():
            el.sync_state_with_parent()

        self._injected = True
        self.enabled   = True
        print(f"  [MBL:{self.prefix}] injected: "
              f"{upstream_el.get_name()} → [MBL x{len(self.nodes)}] → {downstream_el.get_name()}")

    def eject(self):
        if not self._injected:
            return
        import traceback
        print(f"  [MBL:{self.prefix}] eject called from:")
        traceback.print_stack(limit=5)
        up, dn = self._upstream, self._downstream

        for el in self._all_els():
            el.set_state(Gst.State.NULL)

        sp = up.get_static_pad("src")
        if sp and sp.is_linked():
            p = sp.get_peer()
            if p: sp.unlink(p)

        sp2 = self._conv.get_static_pad("src")
        if sp2 and sp2.is_linked():
            p = sp2.get_peer()
            if p: sp2.unlink(p)

        sk = dn.get_static_pad("sink")
        if sk and sk.is_linked():
            p = sk.get_peer()
            if p: p.unlink(sk)

        if not up.link(dn):
            print(f"  [MBL] eject: restore {up.get_name()}→{dn.get_name()} FAIL")

        self._injected = False
        self.enabled   = False
        print(f"  [MBL:{self.prefix}] ejected")

    def _all_els(self):
        """Zwraca wszystkie elementy GST należące do MBL."""
        els = []
        if self._tee:      els.append(self._tee)
        els.extend([q for q in self._queues if q])
        if self._mixer:    els.append(self._mixer)
        if hasattr(self, "_caps_out") and self._caps_out: els.append(self._caps_out)
        if self._conv:     els.append(self._conv)
        for n in self.nodes:
            els.extend(n._all_els())
        return els

    # ── AutoInsert — automatyczne wstrzyknięcie gdy sygnał przekracza próg ───

    def tick_autoinsert(self, rms_db_overall):
        """
        Tryb AutoInsert: MBL włącza się automatycznie gdy poziom ogólny
        przekracza self._ai_threshold_db przez self._ai_hold_frames ramek,
        i wyłącza gdy sygnał opada poniżej przez self._ai_release_frames ramek.

        Wywołuj co ~50ms z głównej pętli lub timera.
        """
        if not self._autoinsert_en:
            return
        if rms_db_overall > self._ai_threshold_db:
            self._ai_above_frames += 1
            self._ai_below_frames  = 0
            if self._ai_above_frames >= self._ai_hold_frames and not self._injected:
                self.set_enabled(True)
                if self._on_ai_state: self._on_ai_state(True)
        else:
            self._ai_below_frames += 1
            self._ai_above_frames  = 0
            if self._ai_below_frames >= self._ai_release_frames and self._injected:
                self.set_enabled(False)
                if self._on_ai_state: self._on_ai_state(False)

    def set_autoinsert(self, en, threshold_db=-12.0, hold_frames=4,
                       release_frames=20, on_state=None):
        """
        Konfiguruje tryb AutoInsert.
        en             — włącz/wyłącz automatykę
        threshold_db   — próg RMS w dB powyżej którego MBL się włącza (-20..-6)
        hold_frames    — ile ramek powyżej progu zanim włączy (debounce)
        release_frames — ile ramek poniżej progu zanim wyłączy
        on_state       — callback(active: bool) dla UI
        """
        self._autoinsert_en      = en
        self._ai_threshold_db    = threshold_db
        self._ai_hold_frames     = hold_frames
        self._ai_release_frames  = release_frames
        self._on_ai_state        = on_state
        self._ai_above_frames    = 0
        self._ai_below_frames    = 0
        if not en and self._injected:
            self.set_enabled(False)

    # ── AutoLevels — automatyczne dostosowanie threshold per pasmo ───────────

    def tick_autolevels(self):
        """
        Tryb AutoLevels: analizuje zmierzone poziomy RMS per pasmo
        i automatycznie przesuwa threshold każdego limitera tak, żeby
        gain reduction był stabilny i proporcjonalny do konfiguracji.

        Algorytm:
        - Cel: threshold = measured_peak * target_headroom
        - Zmiana threshold jest wygładzona (EMA z alpha=0.05)
        - Bounds: zawsze w zakresie [min_thr, max_thr] per pasmo

        Wywołuj co ~200ms (wolniejszy cykl niż AutoInsert).
        """
        if not self._autolevels_en:
            return
        for i, node in enumerate(self.nodes):
            if node.peak_db <= -79:
                continue   # brak sygnału w paśmie — pomiń
            # Zmierz szczytowy poziom (liniowy)
            peak_lin  = 10 ** (node.peak_db / 20.0)
            # Cel: threshold powinien być tuż nad szczytem * headroom
            target_thr = min(1.0, peak_lin * self._al_headroom)
            target_thr = max(self._al_min_thr, min(self._al_max_thr, target_thr))
            # Wygładź (EMA)
            node._al_thr = node._al_thr + self._al_alpha * (target_thr - node._al_thr)
            node.set_threshold(node._al_thr)
            # Powiadom UI
            if self._on_al_update:
                self._on_al_update(i, node._al_thr)

    def set_autolevels(self, en, headroom=1.05, alpha=0.05,
                       min_thr=0.3, max_thr=0.98, on_update=None):
        """
        Konfiguruje tryb AutoLevels.
        en        — włącz/wyłącz
        headroom  — mnożnik nad szczytem (1.05 = 5% margines nad pikiem)
        alpha     — szybkość śledzenia EMA (0.01=wolno .. 0.3=szybko)
        min_thr   — minimalny dopuszczalny threshold (bezpieczeństwo)
        max_thr   — maksymalny threshold (nie relaksuj za bardzo)
        on_update — callback(band_idx, new_thr) dla aktualizacji suwaków UI
        """
        self._autolevels_en = en
        self._al_headroom   = headroom
        self._al_alpha      = alpha
        self._al_min_thr    = min_thr
        self._al_max_thr    = max_thr
        self._on_al_update  = on_update
        # Inicjalizuj stan EMA w węzłach
        for node in self.nodes:
            node._al_thr = node.band_cfg["threshold"]

    def set_band_threshold(self, band_idx, v):
        if 0 <= band_idx < len(self.nodes):
            self.nodes[band_idx].set_threshold(v)

    def set_band_ratio(self, band_idx, v):
        if 0 <= band_idx < len(self.nodes):
            self.nodes[band_idx].set_ratio(v)

    def _on_node_level(self, node, rms_db, peak_db):
        if self.on_level:
            idx = next((i for i,n in enumerate(self.nodes) if n is node), -1)
            self.on_level(idx, rms_db, peak_db)

    def handle_bus_message(self, structure):
        """Sprawdza do którego węzła należy wiadomość level i przekazuje."""
        # GStreamer wysyła ścieżkę elementu np. "carbon/mbl_b0_level"
        # Szukamy po nazwie elementu _level (nie node.name)
        src_name = structure.get_string("GstObject-path") or ""
        if not src_name:
            # Fallback: sprawdź przez msg source (GstObject-name)
            src_name = structure.get_string("GstObject-name") or ""
        for node in self.nodes:
            lvl_name = node._level.get_name() if node._level else ""
            if lvl_name and (lvl_name in src_name or node.name in src_name):
                node.handle_level_message(structure)
                return


# ============================================================================
# MULTIBAND LIMITER WIDGET
# ============================================================================
class MultibandLimiterWidget(QGroupBox):
    """
    Panel UI dla MultibandLimiter z trybami AutoInsert i AutoLevels.
    """
    SS = (
        "QGroupBox{color:#FF8844;border:1px solid #3A2010;"
        "margin-top:10px;font-weight:bold;background:#0C0906}"
        "QLabel{color:#AA6633;font-size:9px}"
        "QSlider::groove:vertical{width:4px;background:#1A1005;border-radius:2px}"
        "QSlider::handle:vertical{background:#FF8844;width:10px;height:10px;"
        "margin:0 -3px;border-radius:5px}"
        "QSlider::groove:horizontal{height:4px;background:#1A1005;border-radius:2px}"
        "QSlider::handle:horizontal{background:#FF8844;width:10px;height:10px;"
        "margin:-3px 0;border-radius:5px}"
        "QCheckBox{color:#FF8844;font-weight:bold;spacing:4px}"
        "QCheckBox::indicator{width:12px;height:12px;border:1px solid #FF6622;"
        "border-radius:2px;background:#0C0906}"
        "QCheckBox::indicator:checked{background:#FF6622}"
        "QPushButton{background:#1A0E08;color:#FF8844;border:1px solid #3A2010;"
        "padding:2px 8px;border-radius:3px;font-size:10px}"
        "QPushButton:checked{background:#3A1A00;color:#FFB060;border-color:#FF8844}"
        "QPushButton:hover{border-color:#FF8844}"
    )

    def __init__(self, parent=None):
        super().__init__("⚡ Multiband Limiter", parent)
        self.setStyleSheet(self.SS)
        self.mbl: MultibandLimiter = None
        self._band_widgets = []   # [(thr_sl, rat_sl, meter), ...]
        self._thr_lbls     = []
        self._overall_rms  = -80.0

        # Timery automatyzacji
        self._ai_timer = QTimer(); self._ai_timer.setInterval(50)
        self._ai_timer.timeout.connect(self._ai_tick)
        self._al_timer = QTimer(); self._al_timer.setInterval(200)
        self._al_timer.timeout.connect(self._al_tick)

        self._build()

    def set_mbl(self, mbl: MultibandLimiter):
        self.mbl = mbl
        for i, (cfg, (thr_sl, rat_sl, _)) in enumerate(
                zip(MBLIMIT_BANDS, self._band_widgets)):
            thr_sl.setValue(int(cfg["threshold"] * 100))
            rat_sl.setValue(int(cfg["ratio"] * 10))
        mbl.on_level = self._on_level

    def update_overall_rms(self, rms_db):
        """Wywoływane z _spectrum() w głównym oknie — ogólny poziom dla AutoInsert."""
        self._overall_rms = rms_db

    # ── Budowa UI ────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 14, 6, 6); root.setSpacing(5)

        # ── Wiersz 1: ACTIVE + status ──────────────────────────────────────
        hdr = QHBoxLayout(); hdr.setSpacing(6)
        self._en = QCheckBox("ACTIVE")
        self._en.clicked.connect(self._toggle_enable)
        hdr.addWidget(self._en)
        self._status_lbl = QLabel("— wyłączony —")
        self._status_lbl.setStyleSheet("color:#555;font-size:9px")
        hdr.addWidget(self._status_lbl); hdr.addStretch()
        root.addLayout(hdr)

        # ── Wiersz 2: AutoInsert controls ─────────────────────────────────
        ai_box = QGroupBox("AutoInsert")
        ai_box.setStyleSheet(
            "QGroupBox{color:#FFAA44;border:1px solid #2A1808;"
            "margin-top:8px;font-size:9px;background:#0E0A06}"
            "QLabel{color:#886633;font-size:9px}"
            "QSlider::groove:horizontal{height:3px;background:#1A1005}"
            "QSlider::handle:horizontal{background:#FFAA44;width:8px;height:8px;margin:-2px 0;border-radius:4px}"
            "QCheckBox{color:#FFAA44;font-size:9px}"
            "QCheckBox::indicator{width:10px;height:10px;border:1px solid #FFAA44;border-radius:2px;background:#0E0A06}"
            "QCheckBox::indicator:checked{background:#FFAA44}")
        ai_v = QVBoxLayout(ai_box); ai_v.setContentsMargins(5,10,5,5); ai_v.setSpacing(3)

        ai_r1 = QHBoxLayout(); ai_r1.setSpacing(6)
        self._ai_en = QCheckBox("Włącz AutoInsert")
        self._ai_en.clicked.connect(self._toggle_ai)
        ai_r1.addWidget(self._ai_en)
        self._ai_indicator = QLabel("◯")
        self._ai_indicator.setStyleSheet("color:#444;font-size:14px")
        ai_r1.addWidget(self._ai_indicator); ai_r1.addStretch()
        ai_v.addLayout(ai_r1)

        ai_r2 = QHBoxLayout(); ai_r2.setSpacing(4)
        ai_r2.addWidget(QLabel("Próg RMS:"))
        self._ai_thr_sl = QSlider(Qt.Orientation.Horizontal)
        self._ai_thr_sl.setRange(-40, -3); self._ai_thr_sl.setValue(-12)
        self._ai_thr_lbl = QLabel("-12 dB"); self._ai_thr_lbl.setFixedWidth(44)
        self._ai_thr_sl.valueChanged.connect(
            lambda v: (self._ai_thr_lbl.setText(f"{v} dB"),
                       self.mbl and self.mbl._autoinsert_en and
                       self.mbl.set_autoinsert(True, threshold_db=float(v))))
        ai_r2.addWidget(self._ai_thr_sl); ai_r2.addWidget(self._ai_thr_lbl)
        ai_v.addLayout(ai_r2)
        root.addWidget(ai_box)

        # ── Wiersz 3: AutoLevels controls ─────────────────────────────────
        al_box = QGroupBox("AutoLevels")
        al_box.setStyleSheet(
            "QGroupBox{color:#44FFAA;border:1px solid #082A18;"
            "margin-top:8px;font-size:9px;background:#060E0A}"
            "QLabel{color:#336655;font-size:9px}"
            "QSlider::groove:horizontal{height:3px;background:#051A0A}"
            "QSlider::handle:horizontal{background:#44FFAA;width:8px;height:8px;margin:-2px 0;border-radius:4px}"
            "QCheckBox{color:#44FFAA;font-size:9px}"
            "QCheckBox::indicator{width:10px;height:10px;border:1px solid #44FFAA;border-radius:2px;background:#060E0A}"
            "QCheckBox::indicator:checked{background:#44FFAA}")
        al_v = QVBoxLayout(al_box); al_v.setContentsMargins(5,10,5,5); al_v.setSpacing(3)

        al_r1 = QHBoxLayout(); al_r1.setSpacing(6)
        self._al_en = QCheckBox("Włącz AutoLevels")
        self._al_en.clicked.connect(self._toggle_al)
        al_r1.addWidget(self._al_en); al_r1.addStretch()
        al_v.addLayout(al_r1)

        al_r2 = QHBoxLayout(); al_r2.setSpacing(4)
        al_r2.addWidget(QLabel("Szybkość:"))
        self._al_speed_sl = QSlider(Qt.Orientation.Horizontal)
        self._al_speed_sl.setRange(1, 30); self._al_speed_sl.setValue(5)
        self._al_speed_lbl = QLabel("α=0.05"); self._al_speed_lbl.setFixedWidth(44)
        self._al_speed_sl.valueChanged.connect(
            lambda v: (self._al_speed_lbl.setText(f"α={v/100:.2f}"),
                       self.mbl and self.mbl._autolevels_en and
                       setattr(self.mbl, '_al_alpha', v/100)))
        al_r2.addWidget(self._al_speed_sl); al_r2.addWidget(self._al_speed_lbl)
        al_v.addLayout(al_r2)
        root.addWidget(al_box)

        # ── Wiersz 4: Per-pasmo metr + suwaki ──────────────────────────────
        grid = QHBoxLayout(); grid.setSpacing(8)
        for i, cfg in enumerate(MBLIMIT_BANDS):
            col = QVBoxLayout(); col.setSpacing(2)

            name_lbl = QLabel(cfg["name"])
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            name_lbl.setStyleSheet(
                f"color:{cfg['color']};font-weight:bold;font-size:10px")
            col.addWidget(name_lbl)

            meter = BandMeter(cfg["color"])
            meter.setFixedSize(28, 90)
            col.addWidget(meter, alignment=Qt.AlignmentFlag.AlignHCenter)

            thr_lbl = QLabel(f"THR\n{cfg['threshold']:.2f}")
            thr_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            thr_lbl.setFixedWidth(36)
            col.addWidget(thr_lbl)
            thr_sl = QSlider(Qt.Orientation.Vertical)
            thr_sl.setRange(10, 100); thr_sl.setValue(int(cfg["threshold"] * 100))
            thr_sl.setFixedHeight(55); thr_sl.setFixedWidth(20)
            thr_sl.valueChanged.connect(lambda v, idx=i, lbl=thr_lbl:
                (lbl.setText(f"THR\n{v/100:.2f}"),
                 self.mbl and self.mbl.set_band_threshold(idx, v/100)))
            col.addWidget(thr_sl, alignment=Qt.AlignmentFlag.AlignHCenter)

            rat_lbl = QLabel(f"RAT\n{cfg['ratio']:.1f}")
            rat_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            rat_lbl.setFixedWidth(36)
            col.addWidget(rat_lbl)
            rat_sl = QSlider(Qt.Orientation.Vertical)
            rat_sl.setRange(10, 200); rat_sl.setValue(int(cfg["ratio"] * 10))
            rat_sl.setFixedHeight(40); rat_sl.setFixedWidth(20)
            rat_sl.valueChanged.connect(lambda v, idx=i, lbl=rat_lbl:
                (lbl.setText(f"RAT\n{v/10:.1f}"),
                 self.mbl and self.mbl.set_band_ratio(idx, v/10)))
            col.addWidget(rat_sl, alignment=Qt.AlignmentFlag.AlignHCenter)

            self._band_widgets.append((thr_sl, rat_sl, meter))
            self._thr_lbls.append(thr_lbl)
            grid.addLayout(col)

        root.addLayout(grid)

    # ── Callbacki UI ────────────────────────────────────────────────────────

    def _toggle_enable(self, en):
        if self.mbl:
            # Guard: nie wywoluj jesli MBL juz w zadanym stanie
            if en == self.mbl._injected:
                return
            self.mbl.set_enabled(en)
        txt = "● AKTYWNY" if en else "— wyłączony —"
        col = "#FF8844" if en else "#555"
        self._status_lbl.setText(txt)
        self._status_lbl.setStyleSheet(f"color:{col};font-size:9px")

    def _toggle_ai(self, en):
        if not self.mbl: return
        thr = float(self._ai_thr_sl.value())
        self.mbl.set_autoinsert(en, threshold_db=thr,
                                on_state=self._on_ai_state_change)
        if en:
            self._ai_timer.start()
        else:
            self._ai_timer.stop()
            self._ai_indicator.setText("◯")
            self._ai_indicator.setStyleSheet("color:#444;font-size:14px")

    def _toggle_al(self, en):
        if not self.mbl: return
        alpha = self._al_speed_sl.value() / 100.0
        self.mbl.set_autolevels(en, alpha=alpha,
                                on_update=self._on_al_thr_update)
        if en:
            self._al_timer.start()
            # AutoLevels wymaga żeby MBL był aktywny — włącz bez pętli
            if not self.mbl._injected:
                self._en.blockSignals(True)
                self._en.setChecked(True)
                self._en.blockSignals(False)
                self.mbl.set_enabled(True)
                self._status_lbl.setText("● AKTYWNY")
                self._status_lbl.setStyleSheet("color:#FF8844;font-size:9px")
        else:
            self._al_timer.stop()

    def _ai_tick(self):
        if self.mbl:
            self.mbl.tick_autoinsert(self._overall_rms)

    def _al_tick(self):
        if self.mbl:
            self.mbl.tick_autolevels()

    def _on_ai_state_change(self, active):
        """Callback z AutoInsert — aktualizuje wskaźnik LED."""
        GLib.idle_add(self._update_ai_indicator, active)

    def _update_ai_indicator(self, active):
        if active:
            self._ai_indicator.setText("●")
            self._ai_indicator.setStyleSheet("color:#FF4400;font-size:14px")
            # Automatycznie włącz checkbox ACTIVE jeśli nie jest
            if not self._en.isChecked():
                self._en.blockSignals(True)
                self._en.setChecked(True)
                self._en.blockSignals(False)
                self._status_lbl.setText("● AKTYWNY (Auto)")
                self._status_lbl.setStyleSheet("color:#FF8844;font-size:9px")
        else:
            self._ai_indicator.setText("◯")
            self._ai_indicator.setStyleSheet("color:#444;font-size:14px")
            if self._en.isChecked():
                self._en.blockSignals(True)
                self._en.setChecked(False)
                self._en.blockSignals(False)
                self._status_lbl.setText("— wyłączony (Auto) —")
                self._status_lbl.setStyleSheet("color:#555;font-size:9px")

    def _on_al_thr_update(self, band_idx, new_thr):
        """Callback z AutoLevels — przesuwa suwaki threshold w UI."""
        if 0 <= band_idx < len(self._band_widgets):
            thr_sl, _, _ = self._band_widgets[band_idx]
            thr_sl.blockSignals(True)
            thr_sl.setValue(int(new_thr * 100))
            thr_sl.blockSignals(False)
            if band_idx < len(self._thr_lbls):
                self._thr_lbls[band_idx].setText(f"THR\n{new_thr:.2f}")

    def _on_level(self, band_idx, rms_db, peak_db):
        """Wywoływany z MultibandLimiter gdy przychodzi wiadomość level."""
        if 0 <= band_idx < len(self._band_widgets):
            _, _, meter = self._band_widgets[band_idx]
            node = self.mbl.nodes[band_idx] if self.mbl else None
            if node:
                GLib.idle_add(meter.update_level, rms_db, peak_db,
                              node.rms_l_db, node.rms_r_db,
                              node.peak_l_db, node.peak_r_db)
            else:
                GLib.idle_add(meter.update_level, rms_db, peak_db)


class BandMeter(QWidget):
    """
    Pionowy metr poziomu dla jednego pasma MBL.
    Pokazuje osobno kanał L (lewy słupek) i R (prawy słupek)
    dla weryfikacji separacji stereo.
    """

    def __init__(self, color="#FF8844", parent=None):
        super().__init__(parent)
        self._color     = QColor(color)
        self._rms_l     = -80.0
        self._rms_r     = -80.0
        self._peak_l    = -80.0
        self._peak_r    = -80.0
        self._ph_l      = -80.0   # peak hold L
        self._ph_r      = -80.0   # peak hold R
        self._ph_timer  = 0

    def update_level(self, rms_db, peak_db, rms_l=None, rms_r=None,
                     peak_l=None, peak_r=None):
        """Przyjmuje poziomy per kanał L/R lub fallback na mono."""
        self._rms_l  = max(-80.0, min(0.0, rms_l  if rms_l  is not None else rms_db))
        self._rms_r  = max(-80.0, min(0.0, rms_r  if rms_r  is not None else rms_db))
        self._peak_l = max(-80.0, min(0.0, peak_l if peak_l is not None else peak_db))
        self._peak_r = max(-80.0, min(0.0, peak_r if peak_r is not None else peak_db))
        pk = max(self._peak_l, self._peak_r)
        if pk > max(self._ph_l, self._ph_r):
            self._ph_l     = self._peak_l
            self._ph_r     = self._peak_r
            self._ph_timer = 35
        else:
            self._ph_timer -= 1
            if self._ph_timer <= 0:
                fall = 1.5
                self._ph_l = max(self._ph_l - fall, self._rms_l)
                self._ph_r = max(self._ph_r - fall, self._rms_r)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#080604"))

        def db_to_y(db):
            return int(h * (1.0 - (max(-80.0, db) + 80.0) / 80.0))

        # Gradient wspólny
        grad = QLinearGradient(0, h, 0, 0)
        grad.setColorAt(0.00, QColor("#006622"))
        grad.setColorAt(0.55, QColor("#888800"))
        grad.setColorAt(0.80, self._color)
        grad.setColorAt(1.00, QColor("#FF1111"))
        brush = QBrush(grad)

        # Słupki L i R — dwie kolumny z przerwą 2px
        gap  = 2
        half = (w - gap) // 2

        for col, rms, peak_h in [
            (0,    self._rms_l, self._ph_l),
            (half + gap, self._rms_r, self._ph_r),
        ]:
            y = db_to_y(rms)
            p.fillRect(col, y, half, h - y, brush)
            # Peak hold
            if peak_h > -79:
                py = db_to_y(peak_h)
                p.fillRect(col, py, half, 1, QBrush(QColor("#FFFFFF")))

        # Skala dB (ciemne linie)
        p.setPen(QPen(QColor("#222"), 1))
        for db in [-60, -40, -20, -6]:
            y = db_to_y(db)
            p.drawLine(0, y, w, y)

        # Etykieta kanałów (bardzo mała)
        p.setPen(QPen(QColor("#444")))
        f = p.font(); f.setPixelSize(6); p.setFont(f)
        p.drawText(1, h-1, "L")
        p.drawText(half + gap + 1, h-1, "R")

        p.end()


# ============================================================================
# LIMITER ROUTER — wielopunktowe wstrzykiwanie MBL w pipeline
# ============================================================================
# Zdefiniowane punkty wstrzyknięcia w pipeline CarbonX:
#
#   INPUT    — zaraz po audioconvert wejściowym (przed Tape)
#              idealny do: ochrony przed przesterowaniem na wejściu
#
#   POST_EQ  — po EQ, przed Spatial (po kształtowaniu widma)
#              idealny do: limitowania po korekcji barwy
#
#   POST_FX  — po całym łańcuchu DSP, przed wyjściem (conv_out → hw_sink)
#              idealny do: finalny limiter master, zabezpieczenie wyjścia
#
#   POST_MON — w torze monitora (opcjonalnie, niezależnie od main)

LIMITER_POINTS = {
    "INPUT":   {"label": "Wejście",    "color": "#FF4444",
                "desc":  "Przed Tape — ochrona wejścia"},
    "POST_EQ": {"label": "Po EQ",      "color": "#FFAA00",
                "desc":  "Po EQ/Spatial — kształtowanie widma"},
    "POST_FX": {"label": "Master Out", "color": "#00FFCC",
                "desc":  "Wyjście master — finalny limit"},
}


class LimiterRouter:
    """
    Zarządza wieloma instancjami MultibandLimiter w różnych punktach pipeline.
    Każdy punkt ma własną instancję MBL z niezależnymi ustawieniami.

    Użycie:
        router = LimiterRouter(pipeline)
        router.register("POST_FX", mbl_instance, conv_out, hw_sink)
        router.enable("POST_FX", True)
        router.get("POST_FX").set_band_threshold(0, 0.8)
    """

    def __init__(self):
        self._points = {}   # point_id -> {"mbl": MBL, "up": el, "dn": el}

    def register(self, point_id, mbl, upstream_el, downstream_el):
        """
        Rejestruje punkt wstrzyknięcia.
        mbl musi być już skonstruowane z tymi samymi elementami pipeline.
        upstream/downstream to elementy GST między którymi MBL zostanie wstrzyknięty.
        """
        mbl._upstream   = upstream_el
        mbl._downstream = downstream_el
        self._points[point_id] = {
            "mbl": mbl, "up": upstream_el, "dn": downstream_el
        }
        print(f"  [Router] zarejestrowano punkt: {point_id} "
              f"({upstream_el.get_name()} → {downstream_el.get_name()})")

    def enable(self, point_id, en):
        """Włącza/wyłącza MBL w danym punkcie."""
        pt = self._points.get(point_id)
        if pt:
            pt["mbl"].set_enabled(en)

    def enable_all(self, en):
        """Włącza/wyłącza wszystkie punkty jednocześnie."""
        for pt in self._points.values():
            pt["mbl"].set_enabled(en)

    def get(self, point_id):
        """Zwraca instancję MultibandLimiter dla danego punktu."""
        pt = self._points.get(point_id)
        return pt["mbl"] if pt else None

    def active_points(self):
        """Zwraca listę aktywnych (wstrzykniętych) punktów."""
        return [pid for pid, pt in self._points.items()
                if pt["mbl"]._injected]

    def registered_points(self):
        return list(self._points.keys())


class LimiterRouterWidget(QGroupBox):
    """
    Panel UI dla LimiterRouter.
    Pokazuje wszystkie zarejestrowane punkty wstrzyknięcia z:
    - checkboxem włącz/wyłącz per punkt
    - mini-metrem pokazującym aktywność
    - przyciskiem do otwarcia szczegółowego widgetu MBL per punkt
    """
    SS = (
        "QGroupBox{color:#FF6622;border:1px solid #3A1800;"
        "margin-top:10px;font-weight:bold;background:#0A0600}"
        "QLabel{color:#884422;font-size:9px}"
        "QCheckBox{color:#FF8844;font-size:10px;spacing:4px}"
        "QCheckBox::indicator{width:12px;height:12px;border:1px solid #FF6622;"
        "border-radius:2px;background:#0A0600}"
        "QCheckBox::indicator:checked{background:#FF4400}"
        "QPushButton{background:#150800;color:#FF8844;border:1px solid #3A1800;"
        "padding:2px 6px;border-radius:3px;font-size:9px}"
        "QPushButton:hover{border-color:#FF8844}"
    )

    def __init__(self, parent=None):
        super().__init__("⚡ Limiter Points", parent)
        self.setStyleSheet(self.SS)
        self.router: LimiterRouter = None
        self._point_widgets = {}   # point_id -> {"cb": QCheckBox, "btn": QPushButton}
        self._detail_widgets = {}  # point_id -> MultibandLimiterWidget (tworzone lazily)
        self._build()

    def set_router(self, router: LimiterRouter):
        self.router = router
        # Dodaj wiersz per każdy zarejestrowany punkt
        for pid in router.registered_points():
            self._add_point_row(pid)

    def _build(self):
        self._root_v = QVBoxLayout(self)
        self._root_v.setContentsMargins(6, 14, 6, 6)
        self._root_v.setSpacing(4)

        # Nagłówek
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Punkt wstrzyknięcia"))
        hdr.addStretch()
        all_btn = QPushButton("Wszystkie ON")
        all_btn.clicked.connect(lambda: self.router and self.router.enable_all(True))
        none_btn = QPushButton("Wszystkie OFF")
        none_btn.clicked.connect(lambda: self.router and self.router.enable_all(False))
        hdr.addWidget(all_btn); hdr.addWidget(none_btn)
        self._root_v.addLayout(hdr)

        self._points_layout = QVBoxLayout()
        self._points_layout.setSpacing(3)
        self._root_v.addLayout(self._points_layout)
        self._root_v.addStretch()

    def _add_point_row(self, point_id):
        cfg = LIMITER_POINTS.get(point_id, {"label": point_id,
                                             "color": "#888",
                                             "desc": ""})
        row = QHBoxLayout(); row.setSpacing(6)

        # Kolorowy marker
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{cfg['color']};font-size:12px")
        dot.setFixedWidth(16)
        row.addWidget(dot)

        # Nazwa i opis
        lbl = QLabel(f"{cfg['label']}  {cfg['desc']}")
        lbl.setStyleSheet(f"color:{cfg['color']};font-size:9px")
        row.addWidget(lbl, 1)

        # Checkbox
        cb = QCheckBox()
        cb.setToolTip(f"Włącz MBL w punkcie: {point_id}")
        cb.clicked.connect(lambda en, pid=point_id: self._on_toggle(pid, en))
        row.addWidget(cb)

        # Przycisk szczegółów
        btn = QPushButton("Edytuj")
        btn.setFixedWidth(48)
        btn.clicked.connect(lambda _, pid=point_id: self._open_detail(pid))
        row.addWidget(btn)

        self._point_widgets[point_id] = {"cb": cb, "btn": btn, "dot": dot}
        self._points_layout.addLayout(row)

    def _on_toggle(self, point_id, en):
        if not self.router:
            return
        mbl = self.router.get(point_id)
        if mbl and en == mbl._injected:
            return  # guard — Qt może wysłać sygnał przy inicjalizacji
        if self.router:
            self.router.enable(point_id, en)

    def _open_detail(self, point_id):
        """Otwiera okno szczegółów MBL dla danego punktu."""
        if point_id not in self._detail_widgets:
            w = MultibandLimiterWidget()
            mbl = self.router.get(point_id) if self.router else None
            if mbl:
                w.set_mbl(mbl)
            self._detail_widgets[point_id] = w

        dlg = self._detail_widgets[point_id]
        cfg = LIMITER_POINTS.get(point_id, {"label": point_id})
        dlg.setWindowTitle(f"MBL — {cfg['label']}")
        dlg.setWindowFlags(Qt.WindowType.Window)
        dlg.resize(460, 520)
        dlg.show()
        dlg.raise_()

    def update_point_state(self, point_id, active):
        """Aktualizuje wygląd wiersza przy zmianie stanu (np. z AutoInsert)."""
        pw = self._point_widgets.get(point_id)
        if pw:
            pw["dot"].setStyleSheet(
                f"color:{'#FF2200' if active else '#333'};font-size:12px")



# ============================================================================
# DSP AUTO-RESOLVER
# ============================================================================
# Każdy moduł ma:
#   "group"    — kategoria DSP (decyduje o priorytecie kolejności)
#   "caps_in"  — wymagany format wejściowy (None = dowolny)
#   "caps_out" — format wyjściowy po module
#   "needs_conv_before" — czy koniecznie potrzebuje audioconvert PRZED sobą
#   "needs_conv_after"  — czy koniecznie potrzebuje audioconvert PO sobie
#
# Grupy DSP i ich naturalna kolejność (niższy nr = wcześniej w łańcuchu):
#   10 PHASE     — inwersja fazy (przed wszystkim)
#   20 DYNAMICS  — gate, compressor, expander (przed EQ)
#   30 FILTER    — hi/lo pass, notch (formowanie widma)
#   40 SPATIAL   — panorama, karaoke (prosta stereo manipulacja)
#   50 TIME      — chorus/echo (czas i modulacja)
#   60 REVERB    — pogłos (na końcu efektów czasowych)
#   70 STEREO    — stereo widening (potrzebuje float stereo)
#   80 GAIN      — trim / wzmocnienie końcowe
#
# audioconvert jest wstawiany automatycznie gdy:
#   - moduł wymaga float (freeverb, stereo)
#   - moduł zmienia format caps który następny moduł nie akceptuje

DSP_META = {
    "phase_inv":  {"group": 10, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "gate":       {"group": 20, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "compressor": {"group": 20, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "expander":   {"group": 20, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "hi_pass":    {"group": 30, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "lo_pass":    {"group": 30, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "notch":      {"group": 30, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "panorama":   {"group": 40, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "karaoke":    {"group": 40, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "chorus":     {"group": 50, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "reverb":     {"group": 60, "needs_conv_before": True,  "needs_conv_after": True,
                   "float_required": True},   # freeverb wymaga F32 stereo
    "stereo_fx":  {"group": 70, "needs_conv_before": True,  "needs_conv_after": True,
                   "float_required": True},   # plugin 'stereo' wymaga F32
    "trim":       {"group": 80, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
}

# Reguły DSP: które efekty NIE powinny być po sobie (reorder hint)
# Format: (A, B) => B powinno być PRZED A jeśli oba aktywne
DSP_REORDER_RULES = [
    # Nie filtruj PO dodaniu pogłosu — straty naturalności
    ("reverb",    "hi_pass"),
    ("reverb",    "lo_pass"),
    ("reverb",    "notch"),
    # Kompresja po EQ/filtrach (nie przed)
    ("hi_pass",   "compressor"),
    ("lo_pass",   "compressor"),
    # Gate powinien być pierwszy w dynamice
    ("compressor","gate"),
    ("expander",  "gate"),
    # Karaoke przed panoramą (karaoke operuje na mid/side)
    ("panorama",  "karaoke"),
    # Stereo widening po pogłosie (szerzej brzmi po reverb)
    ("stereo_fx", "reverb"),
    # Trim zawsze ostatni
    ("trim",      "reverb"),
    ("trim",      "stereo_fx"),
    ("trim",      "chorus"),
]


class DSPAutoResolver:
    """
    Wyznacza optymalną kolejność DSP i przebudowuje fragment pipeline
    między entry_el a exit_el.

    Strategia przebudowy:
    - Pipeline musi być w stanie NULL przed relinkingiem (GStreamer wymaga)
    - Wszystkie elementy chain są w pipeline od startu (dodane w _gst_init)
    - Rebuild tylko odpina/podpina połączenia — nie usuwa ani nie dodaje elementów
    - Konwertery (max 4 stałe sloty) też są w pipeline od startu
    """

    # Stałe sloty konwerterów — tyle ile może być potrzebnych naraz
    CONV_SLOTS = 4

    def __init__(self, pipeline, entry_el, exit_el, name_prefix="ar"):
        self.pipeline      = pipeline
        self.entry_el      = entry_el
        self.exit_el       = exit_el
        self.name_prefix   = name_prefix
        self.chain_els     = {}          # {mid: Gst.Element}
        self._convs        = []          # stałe sloty audioconvert (dodane do pipeline)
        self._current_order = None       # None = nie zbuildowane jeszcze
        self._initialized  = False

    def set_chain_elements(self, chain_els):
        self.chain_els = chain_els

    def init_convs(self):
        """Tworzy i dodaje do pipeline stałą pulę konwerterów. Wywołać po set_chain_elements."""
        for i in range(self.CONV_SLOTS):
            name = f"{self.name_prefix}_conv{i}"
            el = Gst.ElementFactory.make("audioconvert", name)
            if el:
                self.pipeline.add(el)
                self._convs.append(el)
        self._initialized = True
        # Ustaw pustą kolejność — dzięki temu rebuild([]) będzie zawsze pomijany
        # gdy nie ma aktywnych modułów (direct link jest zrobiony przez _gst_init)
        self._current_order = []

    # ── Sortowanie DSP ───────────────────────────────────────────────────────

    def resolve_order(self, enabled_mids):
        if not enabled_mids:
            return []
        ordered = sorted(enabled_mids, key=lambda m: DSP_META.get(m, {}).get("group", 99))
        changed = True
        passes = 0
        while changed and passes < 20:
            changed = False; passes += 1
            for (after, before) in DSP_REORDER_RULES:
                if after in ordered and before in ordered:
                    ia, ib = ordered.index(after), ordered.index(before)
                    if ib > ia:
                        ordered[ia], ordered[ib] = ordered[ib], ordered[ia]
                        changed = True
        return ordered

    # ── Główna metoda rebuild ────────────────────────────────────────────────

    def rebuild(self, enabled_mids):
        if not self._initialized:
            self.init_convs()

        optimal = self.resolve_order(enabled_mids)

        if optimal == self._current_order:
            return optimal

        print(f"[AutoResolver:{self.name_prefix}] {self._current_order} → {optimal}")
        self._current_order = optimal

        pipe = self.pipeline

        # ── 1. Zapamiętaj stan pipeline ───────────────────────────────────────
        _, cur_state, _ = pipe.get_state(0)
        was_playing = (cur_state == Gst.State.PLAYING)
        was_paused  = (cur_state == Gst.State.PAUSED)

        # ── 2. Ustaw elementy chain i konwertery w READY (nie cały pipeline) ──
        # READY pozwala na relinkowanie bez zatrzymywania src/sink
        all_chain_els = list(self.chain_els.values()) + self._convs
        for el in all_chain_els:
            if el:
                el.set_state(Gst.State.NULL)

        # ── 3. Odepnij segment entry→exit ────────────────────────────────────
        # srcpad entry_el
        sp = self.entry_el.get_static_pad("src")
        if sp and sp.is_linked():
            peer = sp.get_peer()
            if peer: sp.unlink(peer)

        # Wszystkie chain + conv: odepnij srcpad i sinkpad
        for el in all_chain_els:
            if not el: continue
            sp2 = el.get_static_pad("src")
            if sp2 and sp2.is_linked():
                peer = sp2.get_peer()
                if peer: sp2.unlink(peer)
            sk2 = el.get_static_pad("sink")
            if sk2 and sk2.is_linked():
                peer = sk2.get_peer()
                if peer: peer.unlink(sk2)

        # sinkpad exit_el
        sk = self.exit_el.get_static_pad("sink")
        if sk and sk.is_linked():
            peer = sk.get_peer()
            if peer: peer.unlink(sk)

        # ── 4. Zbuduj sekwencję elementów z konwerterami ─────────────────────
        sequence = []
        conv_idx  = 0
        prev_meta = None

        for i, mid in enumerate(optimal):
            meta = DSP_META.get(mid, {})
            el   = self.chain_els.get(mid)
            if not el:
                continue

            need_pre = meta.get("needs_conv_before", False)
            if not need_pre and prev_meta and prev_meta.get("needs_conv_after", False):
                need_pre = True

            if need_pre and conv_idx < len(self._convs):
                sequence.append(self._convs[conv_idx]); conv_idx += 1

            sequence.append(el)

            if meta.get("needs_conv_after", False):
                next_mid  = optimal[i+1] if i+1 < len(optimal) else None
                next_meta = DSP_META.get(next_mid, {}) if next_mid else {}
                if not next_meta.get("float_required", False):
                    if conv_idx < len(self._convs):
                        sequence.append(self._convs[conv_idx]); conv_idx += 1

            prev_meta = meta

        # ── 5. Podłącz: entry → [sequence] → exit ────────────────────────────
        chain = [self.entry_el] + sequence + [self.exit_el]

        # Ustaw NULL → READY przed linkowaniem (tylko elementy w środku)
        for el in sequence:
            el.set_state(Gst.State.NULL)
            el.set_state(Gst.State.READY)

        ok = True
        for a, b in zip(chain, chain[1:]):
            if not a.link(b):
                print(f"  [AutoResolver] BŁĄD link: {a.get_name()} → {b.get_name()}")
                ok = False

        if ok:
            print(f"  łańcuch: {' → '.join(e.get_name() for e in chain)}")

        # ── 6. Synchronizuj elementy ze stanem pipeline (bez zatrzymywania src) ─
        for el in sequence:
            el.sync_state_with_parent()

        return optimal

    def get_current_order(self):
        return list(self._current_order) if self._current_order else []

    def format_chain_info(self):
        if not self._current_order:
            return "— brak aktywnych —"
        return " → ".join(CHAIN_DEFS.get(m,(m,))[0] for m in self._current_order)

# ============================================================================
# UTILITIES
# ============================================================================
def create_virtual_sink():
    import subprocess
    try:
        r=subprocess.run(['pactl','list','sinks','short'],
                         capture_output=True,text=True)
        if VIRTUAL_SINK in r.stdout: return True
    except: pass
    try:
        subprocess.run(['pactl','load-module','module-null-sink',
                        f'sink_name={VIRTUAL_SINK}',
                        'sink_properties=device.description="Carbon_Monitor"'],
                       check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        return True
    except Exception as e:
        print(f"Virtual sink: {e}"); return False

def cleanup_virtual_sink():
    import subprocess
    try:
        r=subprocess.run(['pactl','list','modules','short'],
                         capture_output=True,text=True)
        for line in r.stdout.split('\n'):
            if VIRTUAL_SINK in line:
                subprocess.run(['pactl','unload-module',line.split()[0]])
    except: pass

def mkgst(plugin, name, props=None):
    el=Gst.ElementFactory.make(plugin,name)
    if not el:
        print(f"  [!] Cannot create gst element: {plugin} ({name})")
        return None
    if props:
        for k,v in props.items():
            try:
                # Jawna konwersja float — unikamy problemów z locale (przecinek vs kropka)
                el.set_property(k, float(v) if isinstance(v, float) else v)
            except Exception as e: print(f"  prop {name}.{k}: {e}")
    return el

def get_metadata(uri, fn):
    p,t,a=None,fn,"Unknown"
    if uri.startswith("file://") and EYE3D_OK:
        path=uri[7:].replace("/",os.sep)
        if os.path.exists(path):
            try:
                f=eyed3.load(path)
                if f and f.tag:
                    t=f.tag.title or t; a=f.tag.artist or a
                    if f.tag.images:
                        p=QPixmap.fromImage(QImage.fromData(f.tag.images[0].image_data))
            except: pass
    for tag,artist,strip in [("[Radio]","Internet Radio","[Radio] "),
                               ("[TV]","TV Channel","[TV] "),
                               ("[Monitor]","Monitor","[Monitor] ")]:
        if tag in fn: a=artist; t=fn.replace(strip,"")
    return (p,t,a)

def blur_pixmap(p,s):
    if not p: return None
    img=p.scaled(s.width()//20,s.height()//20,
                 Qt.AspectRatioMode.IgnoreAspectRatio,
                 Qt.TransformationMode.SmoothTransformation).toImage()
    b=img.scaled(s,Qt.AspectRatioMode.IgnoreAspectRatio,
                 Qt.TransformationMode.SmoothTransformation)
    pt=QPainter(b); pt.fillRect(b.rect(),QColor(0,0,0,160)); pt.end()
    return QPixmap.fromImage(b)

def parse_m3u(fp):
    entries=[]; cur=None
    try:
        with open(fp,'r',encoding='utf-8',errors='replace') as f:
            for line in f:
                line=line.strip()
                if line.startswith('#EXTINF:'):
                    parts=line.split(',',1)
                    cur=parts[1].strip() if len(parts)>1 else None
                elif line and not line.startswith('#'):
                    name=cur or line.split('/')[-1]
                    tag="[TV]" if cur else "[Stream]"
                    entries.append((line,f"{tag} {name}")); cur=None
    except Exception as e: print(f"M3U: {e}")
    return entries

# ============================================================================
# RADIO SEARCH
# ============================================================================
class RadioSearchDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent); self.setWindowTitle("Radio Search")
        self.setModal(True); self.setMinimumSize(600,440)
        self.setStyleSheet("QDialog{background:#1a1a1e}QLabel{color:#ddd}"
            "QLineEdit,QSpinBox{background:#2a2a30;color:#eee;border:1px solid #444;padding:4px}"
            "QPushButton{background:#2a2a30;color:#eee;border:1px solid #444;padding:5px 12px}"
            "QPushButton:hover{border-color:#00AAAA}"
            "QListWidget{background:#18181c;color:#ddd;border:1px solid #333}"
            "QListWidget::item:selected{background:#0088CC}")
        self._build()

    def _build(self):
        lo=QVBoxLayout(self); lo.setSpacing(6)
        fg=QGroupBox("Filters")
        fg.setStyleSheet("QGroupBox{color:#00AAAA;border:1px solid #444;margin-top:8px;padding-top:8px}")
        fl=QVBoxLayout(fg)
        for lb,attr,ph in [("Name:","name_e","BBC, NPR..."),("Tag:","tag_e","jazz, rock..."),
                            ("Country:","country_e","Poland, USA..."),("Language:","lang_e","polish...")]:
            row=QHBoxLayout(); row.addWidget(QLabel(lb))
            w=QLineEdit(); w.setPlaceholderText(ph); setattr(self,attr,w); row.addWidget(w)
            fl.addLayout(row)
        lr=QHBoxLayout(); lr.addWidget(QLabel("Max:"))
        self.lim=QSpinBox(); self.lim.setRange(5,100); self.lim.setValue(30)
        self.lim.setFixedWidth(65); lr.addWidget(self.lim); lr.addStretch()
        fl.addLayout(lr); lo.addWidget(fg)
        sb=QPushButton("Search"); sb.setStyleSheet("background:#0088CC;font-weight:bold")
        sb.clicked.connect(self._search); lo.addWidget(sb)
        self.rl=QListWidget()
        self.rl.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        lo.addWidget(self.rl)
        self.sl=QLabel("Enter criteria and search")
        self.sl.setStyleSheet("color:#888;font-style:italic"); lo.addWidget(self.sl)
        br=QHBoxLayout(); br.addStretch()
        self.ab=QPushButton("Add Selected"); self.ab.setEnabled(False)
        self.ab.setStyleSheet("background:#00AA00"); self.ab.clicked.connect(self.accept)
        br.addWidget(self.ab)
        cb=QPushButton("Cancel"); cb.clicked.connect(self.reject); br.addWidget(cb)
        lo.addLayout(br)
        self.rl.itemSelectionChanged.connect(
            lambda: self.ab.setEnabled(len(self.rl.selectedItems())>0))

    def _search(self):
        if not PYRADIOS_OK: self.sl.setText("pyradios not installed"); return
        self.rl.clear(); self.sl.setText("Searching...")
        QApplication.processEvents()
        try:
            rb=RadioBrowser(); params={"limit":self.lim.value()}
            for attr,key in [("name_e","name"),("tag_e","tag"),
                              ("country_e","country"),("lang_e","language")]:
                v=getattr(self,attr).text().strip()
                if v: params[key]=v
            if len(params)<=1: self.sl.setText("Enter at least one filter"); return
            for s in (rb.search(**params) or []):
                n=s.get('name','?').strip(); u=s.get('url_resolved')
                if not(n and u): continue
                d=n
                if s.get('country'): d+=f" [{s['country']}]"
                if s.get('bitrate'):  d+=f" {s['bitrate']}kbps"
                item=QListWidgetItem(d); item.setData(Qt.ItemDataRole.UserRole,(u,n))
                self.rl.addItem(item)
            self.sl.setText(f"Found {self.rl.count()} stations")
        except Exception as e: self.sl.setText(f"Error: {e}")

    def get_selected(self):
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.rl.selectedItems()]

# ============================================================================
# MATRIX VISUALIZER
# ============================================================================
class MatrixVisualizer(QWidget):
    # Renderujemy na offscreen QPixmap i blitujemy — eliminuje migotanie
    # Timer kontroluje FPS (33ms = 30fps), spectrum tylko zapisuje dane bez update()
    TARGET_FPS = 30

    def __init__(self,parent=None):
        super().__init__(parent); self.setMinimumHeight(180)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)  # brak tła Qt
        self.ad=[0.0]*64; self.bl=0.0; self.ph=0.0
        self.dc=(None,"",""); self.dp=(None,"",""); self.dn=(None,"","")
        self.bg=None; self.phaser_mode="linear"; self.phase_speed=0.03; self.parts=[]
        self._cache = None   # offscreen pixmap
        self._dirty = True   # czy trzeba przerysować
        self.presets={
            "Cyberpunk":{"layers":["grid_3d","spectrum_bars","digital_rain"],"c":("#00FFFF","#FF00FF","#050010")},
            "Solar":    {"layers":["starfield","pulse_orb","flux_wave"],"c":("#FFDD00","#FF4400","#100500")},
            "Ocean":    {"layers":["flux_wave","bubbles","mirror_spectrum"],"c":("#0088FF","#00FF88","#001020")},
            "Matrix":   {"layers":["digital_rain","spectrum_bars"],"c":("#00FF00","#008800","#000000")},
            "Neon":     {"layers":["grid_3d","pulse_orb","mirror_spectrum"],"c":("#FF0055","#5500FF","#101010")},
        }
        self.curr="Cyberpunk"
        # Jeden timer — 30fps zamiast 60fps + dodatkowych update() z spectrum
        self.tm=QTimer(); self.tm.timeout.connect(self._tick); self.tm.start(1000//self.TARGET_FPS)

    def set_preset(self,n): self.curr=n; self.parts=[]; self._dirty=True
    def set_covers_data(self,p,c,n):
        self.dp=p; self.dc=c; self.dn=n
        self.bg=blur_pixmap(c[0],self.size()) if c[0] else None
        self._dirty=True
    def update_data(self,d):
        # Tylko zapisujemy dane — NIE wołamy update() — timer zrobi to co 33ms
        if d:
            self.ad=d
            self.bl=self.bl*0.8+(sum(d[:5])/5)*0.2
            self._dirty=True
    def _tick(self):
        self.ph+=self.phase_speed
        self._dirty=True   # animacja zawsze wymaga odświeżenia
        self.update()      # jeden update() per tick, nie więcej

    def paintEvent(self,event):
        w,h=self.width(),self.height()
        if w<=0 or h<=0: return
        # Rysuj na offscreen pixmap jeśli dirty lub rozmiar się zmienił
        if (self._cache is None or
                self._cache.width()!=w or self._cache.height()!=h or
                self._dirty):
            self._cache = QPixmap(w, h)
            self._render_to(self._cache, w, h)
            self._dirty = False
        # Blit z cache na ekran — bardzo szybkie
        scrn = QPainter(self)
        scrn.drawPixmap(0, 0, self._cache)
        scrn.end()

    def _render_to(self, pm, w, h):
        p=QPainter(pm)
        # Antialiasing tylko dla linii/okręgów, nie dla prostokątów
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pr=self.presets.get(self.curr,self.presets["Cyberpunk"]); c=pr["c"]
        if self.bg: p.drawPixmap(0,0,self.bg.scaled(w,h,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.FastTransformation))
        else: p.fillRect(0,0,w,h,QColor(c[2]))
        for layer in pr["layers"]:
            fn = getattr(self,f"_draw_{layer}",None)
            if fn:
                if layer in ("flux_wave","pulse_orb","digital_rain","bubbles","starfield"):
                    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                else:
                    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                fn(p,w,h,c)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self._draw_sidebar(p,w,h)
        p.end()

    def _draw_spectrum_bars(self,p,w,h,c):
        bw=w/64
        for i,v in enumerate(self.ad):
            bh=max(1,int(v*h*0.8)); x=int(i*bw)
            g=QLinearGradient(x,h,x,h-bh); g.setColorAt(0,QColor(c[0])); g.setColorAt(1,QColor(c[1]))
            p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(x+1,h-bh,max(1,int(bw)-2),bh)

    def _draw_mirror_spectrum(self,p,w,h,c):
        bw=w/64; cy=h//2
        for i,v in enumerate(self.ad):
            bh=max(1,int(v*cy*0.9)); x=int(i*bw)
            p.fillRect(x+1,cy-bh,max(1,int(bw)-2),bh*2,QColor(c[0]))

    def _draw_grid_3d(self,p,w,h,c):
        p.setPen(QPen(QColor(c[0]),1)); p.setOpacity(0.2+self.bl*0.3)
        for i in range(0,w,30): p.drawLine(i,0,i,h)
        for j in range(0,h,20): p.drawLine(0,j,w,j)
        p.setOpacity(1.0)

    def _draw_digital_rain(self,p,w,h,c):
        if len(self.parts)<40: self.parts.append([random.randint(0,w),random.randint(-h,0),random.uniform(1,4),random.randint(6,14)])
        p.setPen(QColor(c[0])); act=[]
        for pt in self.parts:
            pt[1]+=pt[2]; p.setFont(QFont("Consolas",pt[3]))
            p.drawText(int(pt[0]),int(pt[1]),chr(random.randint(33,126)))
            if pt[1]<h: act.append(pt)
        self.parts=act

    def _draw_flux_wave(self,p,w,h,c):
        p.setPen(QPen(QColor(c[0]),2)); pts=[]
        for i in range(129):
            x=i*w/128; idx=min(63,int(i*64/128))
            y=h/2+math.sin(self.ph+i*0.2)*self.ad[idx]*h*0.4
            pts.append(QPointF(x,y))
        for i in range(len(pts)-1): p.drawLine(pts[i],pts[i+1])

    def _draw_bubbles(self,p,w,h,c):
        if len(self.parts)<20: self.parts.append([random.uniform(0,w),random.uniform(0,h),random.uniform(2,8),random.uniform(1,3)])
        p.setBrush(QColor(c[0])); p.setPen(Qt.PenStyle.NoPen); act=[]
        for pt in self.parts:
            pt[1]-=pt[3]; xw=math.sin(self.ph+pt[1]*0.1)*3
            if pt[1]>-20: p.drawEllipse(QPointF(pt[0]+xw,pt[1]),pt[2],pt[2]); act.append(pt)
        self.parts=act

    def _draw_starfield(self,p,w,h,c):
        cx,cy=w/2,h/2
        if len(self.parts)<100: self.parts.append([random.uniform(0,6.28),random.uniform(10,50)])
        p.setPen(QColor(c[0])); act=[]
        for pt in self.parts:
            pt[1]*=1.05+self.bl*0.1; r=pt[1]
            x=cx+math.cos(pt[0])*r; y=cy+math.sin(pt[0])*r
            if 0<x<w and 0<y<h: p.drawEllipse(QPointF(x,y),2,2); act.append(pt)
        self.parts=act

    def _draw_pulse_orb(self,p,w,h,c):
        cx,cy=w/2,h/2; r=50+self.bl*150
        rd=QRadialGradient(cx,cy,r*1.5)
        C1=QColor(c[1]); C1.setAlpha(0); C2=QColor(c[0]); C2.setAlpha(120)
        rd.setColorAt(0,C1); rd.setColorAt(0.5,C2); rd.setColorAt(1,C1)
        p.setBrush(rd); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx,cy),r*1.5,r*1.5)
        p.setBrush(QColor(c[0])); p.drawEllipse(QPointF(cx,cy),r*0.5,r*0.5)

    def _draw_sidebar(self,p,w,h):
        sw=int(w*0.25); sx=w-sw; sy=h//3
        p.fillRect(sx,0,sw,h,QColor(0,0,0,110))
        p.setPen(QColor(255,255,255,25)); p.drawLine(sx,0,sx,h)
        self._ditm(p,self.dp,QRect(sx,0,sw,sy),0.45,"PREV")
        rc=QRect(sx,sy,sw,sy); p.fillRect(rc,QColor(255,255,255,8))
        self._ditm(p,self.dc,rc,1.0,"NOW")
        self._ditm(p,self.dn,QRect(sx,sy*2,sw,h-sy*2),0.45,"NEXT")

    def _ditm(self,p,d,r,o,l):
        px,t,a=d; p.setOpacity(o); m=8; ir=r.adjusted(m,m,-m,-m-28)
        tr=QRect(r.left()+m,ir.bottom()+2,r.width()-2*m,28)
        if px:
            s=px.scaled(ir.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
            cx2=ir.left()+(ir.width()-s.width())//2; cy2=ir.top()+(ir.height()-s.height())//2
            p.drawPixmap(cx2,cy2,s)
        else:
            p.setPen(QColor(255,255,255,25)); p.drawRect(ir)
            p.drawText(ir,Qt.AlignmentFlag.AlignCenter,l)
        p.setPen(QColor(255,255,255,255 if o==1 else 140))
        f=p.font(); f.setBold(True); p.setFont(f)
        fm=QFontMetrics(f)
        p.drawText(tr.left(),tr.top()+13,fm.elidedText(t,Qt.TextElideMode.ElideRight,tr.width()))
        f.setBold(False); f.setPointSize(max(6,f.pointSize()-1)); p.setFont(f)
        p.drawText(tr.left(),tr.top()+26,fm.elidedText(a,Qt.TextElideMode.ElideRight,tr.width()))
        p.setOpacity(1.0)

    def resizeEvent(self,e):
        if self.dc[0]: self.bg=blur_pixmap(self.dc[0],self.size())
        super().resizeEvent(e)

# ============================================================================
# SMART EQ
# ============================================================================
class SmartEQProcessor:
    def __init__(self,eq):
        self.eq=eq; self.active=False; self.geo_active=True
        self.depth=0.5; self.pm="linear"; self.ph=0.0; self.ps=0.03
        self.exposure_mode="Flat"
        self.tgt=[0.65]*10; self.base=[0.0]*10; self.curr=[0.0]*10; self.sm=0.9

    def set_base(self,i,v): self.base[i]=float(v)
    def set_all_base(self,vals): self.base=[float(v) for v in vals]

    def process(self,spec):
        if not spec: return
        self.ph+=self.ps; chunk=len(spec)//10
        for i in range(10):
            gm=0.0
            if self.geo_active:
                if self.pm=="linear":    gm=math.sin(self.ph+i*0.5)*2
                elif self.pm=="diverge": gm=math.sin(self.ph-abs(4.5-i)*0.5)*3
                elif self.pm=="converge":gm=math.sin(self.ph+abs(4.5-i)*0.5)*3
                elif self.pm=="rise":    gm=math.sin(self.ph+i*0.8)*4*(i/10)
                elif self.pm=="fall":    gm=math.sin(self.ph-i*0.8)*4*((10-i)/10)
                elif self.pm=="chaos":   gm=(random.random()-0.5)*4
            exp=0.0
            if   self.exposure_mode=="Gora":  exp=-3+(i*0.8)
            elif self.exposure_mode=="Dol":   exp=5-(i*0.8)
            elif self.exposure_mode=="Srodek":exp=5-abs(4.5-i)*1.5
            dc=0.0
            if self.active:
                s=i*chunk; ea=sum(spec[s:s+chunk])/chunk if chunk else 0
                dc=(self.tgt[i]-ea)*20*self.depth
            des=max(-12,min(12,self.base[i]+gm+dc+exp))
            self.curr[i]=self.curr[i]*self.sm+des*(1-self.sm)
            self.eq.update_vis(i,self.curr[i])

class EqualizerWidget(QGroupBox):
    def __init__(self,parent=None):
        super().__init__("Equalizer & Smart DSP",parent)
        self.setStyleSheet("""
            QGroupBox{color:#BBB;border:1px solid #333;margin-top:10px;font-weight:bold;background:#0E0E10}
            QSlider::groove:vertical{width:4px;background:#222}
            QSlider::handle:vertical{background:#00AAAA;height:10px;margin:0 -3px;border-radius:5px}
            QCheckBox{color:#00FFFF} QLabel{color:#666;font-size:9px}
            QComboBox{background:#1A1A1E;color:#EEE;border:1px solid #333;border-radius:3px}
        """)
        self.gst=None; self._mon_gst=None; self.sl=[]
        self.proc=SmartEQProcessor(self); self.prog_upd=False
        m=QVBoxLayout(self); m.setContentsMargins(5,15,5,5); m.setSpacing(4)
        pl=QHBoxLayout()
        self.chk=QCheckBox("DYNAMIC"); self.chk.toggled.connect(lambda a:setattr(self.proc,'active',a))
        self.chk_g=QCheckBox("PHASE"); self.chk_g.setChecked(True)
        self.chk_g.toggled.connect(lambda a:setattr(self.proc,'geo_active',a))
        self.exp_cb=QComboBox(); self.exp_cb.addItems(["Flat","Dol","Srodek","Gora"])
        self.exp_cb.currentTextChanged.connect(lambda v:setattr(self.proc,'exposure_mode',v))
        self.cb=QComboBox(); self.cb.addItems(list(EQ_PRESETS.keys()))
        self.cb.currentTextChanged.connect(self.app_pre)
        pl.addWidget(self.chk); pl.addWidget(self.chk_g); pl.addStretch()
        pl.addWidget(QLabel("EXP:")); pl.addWidget(self.exp_cb); pl.addWidget(self.cb)
        m.addLayout(pl)
        bl=QHBoxLayout(); bl.setSpacing(2)
        for i,f in enumerate(["32","64","125","250","500","1k","2k","4k","8k","16k"]):
            v=QVBoxLayout(); s=QSlider(Qt.Orientation.Vertical)
            s.setRange(-12,12); s.setValue(0)
            s.valueChanged.connect(lambda val,x=i:self.usr_chg(x,val))
            self.sl.append(s)
            v.addWidget(s,1,Qt.AlignmentFlag.AlignHCenter)
            v.addWidget(QLabel(f),0,Qt.AlignmentFlag.AlignHCenter); bl.addLayout(v)
        m.addLayout(bl)

    def set_gst(self,el,mon_el=None): self.gst=el; self._mon_gst=mon_el
    def usr_chg(self,i,v):
        if not self.prog_upd: self.proc.set_base(i,v); self.set_b(i,v)
    def update_vis(self,i,v):
        self.prog_upd=True; self.sl[i].setValue(int(v)); self.prog_upd=False; self.set_b(i,v)
    def set_b(self,i,v):
        for el in [self.gst,self._mon_gst]:
            if el:
                try: el.set_property(f"band{i}",float(v))
                except: pass
    def app_pre(self,n):
        if n in EQ_PRESETS:
            self.proc.set_all_base(EQ_PRESETS[n])
            if not self.proc.active and not self.proc.geo_active:
                for i,v in enumerate(EQ_PRESETS[n]): self.sl[i].setValue(v)

# ============================================================================
# ANALOG TAPE WIDGET
# ============================================================================
# ============================================================================
# PHANTOM STEREO MODULE
# ============================================================================
# Tryby Phantom Stereo realizowane przez kombinację dostępnych pluginów GST:
#
#   CROSSFEED    — symulacja odsłuchu głośnikowego na słuchawkach
#                  L' = L + α*R,  R' = R + α*L  (α = blend 5-25%)
#                  Realizacja: dwa audioecho z bardzo krótkim delay
#
#   MS_EXPAND    — Mid/Side processing: separacja M i S, boost S
#                  M = (L+R)/2,  S = (L-R)/2,  S*=gain
#                  Realizacja: audioinvert + audiomixer + trim
#
#   HAAS_WIDE    — Haas effect: lekkie opóźnienie jednego kanału
#                  Realizacja: audioecho (delay L lub R)
#
#   MONO_EXPAND  — wykrycie mono i sztuczne rozszerzenie
#                  Realizacja: audiodynamic + stereo + Haas
#
# W GStreamer nie ma natywnego Mid/Side processora,
# więc wszystkie tryby budujemy z dostępnych prymitywów.


class BandLimiterNode:
    """
    Samowystarczalny węzeł limitera jednopasmowego.
    Można go wstrzyknąć między dowolne dwa elementy GST w pipeline.

    Wewnętrzna struktura jednej instancji:
        [sink_pad] → audioconvert → filtr_pasmowy → audiodynamic(limiter)
                   → level → audioconvert → [src_pad]

    Użycie:
        node = BandLimiterNode(pipeline, "band0", band_cfg, bus_callback)
        node.inject(upstream_el, downstream_el)
        node.set_threshold(0.8)
        node.set_ratio(3.0)
        node.set_enabled(True)
        # node.peak_db, node.rms_db aktualizowane przez callback
    """

    def __init__(self, pipeline, name, band_cfg, on_level=None):
        """
        pipeline  — Gst.Pipeline do którego należą elementy
        name      — unikalna nazwa (prefix dla elementów GST)
        band_cfg  — słownik z MBLIMIT_BANDS[i]
        on_level  — callback(node, rms_db, peak_db) wywoływany z GST bus
        """
        self.pipeline   = pipeline
        self.name       = name
        self.band_cfg   = band_cfg
        self.on_level   = on_level
        self.enabled    = True
        self.peak_db    = -80.0
        self.rms_db     = -80.0
        self.peak_l_db  = -80.0
        self.peak_r_db  = -80.0
        self.rms_l_db   = -80.0
        self.rms_r_db   = -80.0
        self._upstream   = None
        self._downstream = None
        self._injected   = False

        # Buduj elementy GST
        n = name
        self._conv_in  = self._mk("audioconvert",  f"{n}_conv_in")
        # Caps filter wymusza F32LE przez cały łańcuch pasm
        # Eliminuje trzeszczenie z re-negocjacji formatu między audiocheblimit/audiodynamic
        self._caps_f32 = self._mk_caps(f"{n}_capsf32",
            "audio/x-raw,format=F32LE")
        self._filter   = self._build_filter(band_cfg, n)
        self._limiter  = self._mk("audiodynamic",  f"{n}_limiter", {
            "characteristics": "hard-knee",
            "mode":            "compressor",
            "threshold":       float(band_cfg["threshold"]),
            "ratio":           float(band_cfg["ratio"]),
        })
        self._level    = self._mk("level", f"{n}_level", {
            "interval":        50_000_000,   # 50ms → 20 odczytów/s
            "peak-ttl":        300_000_000,
            "peak-falloff":    20.0,
            "post-messages":   True,
        })
        # conv_out usunięty — mixer po stronie MultibandLimiter robi własną konwersję
        # Zachowujemy dla kompatybilności z _all_els() i inject/eject
        self._conv_out = self._mk("audioconvert",  f"{n}_conv_out")

        # Dodaj do pipeline
        for el in [self._conv_in, self._caps_f32, self._filter, self._limiter,
                   self._level, self._conv_out]:
            if el: pipeline.add(el)

        # Połącz wewnętrznie
        self._link_internal()

    def _mk(self, plugin, name, props=None):
        el = Gst.ElementFactory.make(plugin, name)
        if not el:
            print(f"  [BandLimiter] Brak pluginu: {plugin} ({name})")
            return None
        if props:
            for k, v in props.items():
                try: el.set_property(k, float(v) if isinstance(v, float) else v)
                except Exception as e: print(f"    {name}.{k}: {e}")
        return el

    def _mk_caps(self, name, caps_str):
        """Tworzy capsfilter z podanym caps string."""
        el = Gst.ElementFactory.make("capsfilter", name)
        if el:
            el.set_property("caps", Gst.Caps.from_string(caps_str))
        return el

    def _build_filter(self, cfg, prefix):
        """Tworzy odpowiedni filtr pasmowy zależnie od typu pasma."""
        ftype = cfg["filter"]
        if ftype == "lo":
            # Low-pass — przepuszcza tylko niskie
            return self._mk("audiocheblimit", f"{prefix}_filt", {
                "mode": "low-pass", "cutoff": float(cfg["f_hi"]), "poles": 4,
            })
        elif ftype == "hi":
            # High-pass — przepuszcza tylko wysokie
            return self._mk("audiocheblimit", f"{prefix}_filt", {
                "mode": "high-pass", "cutoff": float(cfg["f_lo"]), "poles": 4,
            })
        else:
            # Band-pass przez dwa filtry kaskadowo: hi-pass → lo-pass
            # GStreamer nie ma band-pass w audiocheblimit, więc łączymy dwa
            # Zwracamy lo-pass jako "główny filtr", hi-pass osobno
            hi = self._mk("audiocheblimit", f"{prefix}_filt_hi", {
                "mode": "high-pass", "cutoff": float(cfg["f_lo"]), "poles": 4,
            })
            lo = self._mk("audiocheblimit", f"{prefix}_filt_lo", {
                "mode": "low-pass",  "cutoff": float(cfg["f_hi"]), "poles": 4,
            })
            if hi and lo: self.pipeline.add(hi)   # lo zwracamy, hi dodajemy osobno
            self._band_hi = hi   # zachowaj referencję
            self._band_lo = lo
            return lo            # _link_internal użyje _band_hi jeśli istnieje

    def _link_internal(self):
        """Łączy elementy wewnątrz węzła.
        conv_in → caps_f32(F32LE) → [hi_pass →] filter → limiter → level → conv_out
        caps_f32 wymusza format przed filtrem — eliminuje trzeszczenie.
        """
        def lnk(a, b):
            if a and b:
                if not a.link(b):
                    print(f"  [BandLimiter:{self.name}] link fail: "
                          f"{a.get_name()}→{b.get_name()}")

        # conv_in → F32LE
        lnk(self._conv_in, self._caps_f32)

        hi = getattr(self, "_band_hi", None)
        if hi:
            # band: caps_f32 → hi_pass → lo_pass → limiter → level → conv_out
            lnk(self._caps_f32, hi)
            lnk(hi, self._filter)   # _filter = lo_pass
        else:
            # lo/hi: caps_f32 → filtr → limiter → level → conv_out
            lnk(self._caps_f32, self._filter)

        lnk(self._filter, self._limiter)
        lnk(self._limiter, self._level)
        lnk(self._level, self._conv_out)

    # ── Wstrzyknięcie w pipeline ─────────────────────────────────────────────

    def inject(self, upstream_el, downstream_el):
        """
        Wstrzykuje węzeł między upstream_el a downstream_el.
        Jeśli już wstrzyknięty — najpierw wysuwa się ze starego miejsca.
        """
        if self._injected:
            self.eject()

        self._upstream   = upstream_el
        self._downstream = downstream_el

        # Odepnij bezpośrednie połączenie upstream→downstream jeśli istnieje
        sp = upstream_el.get_static_pad("src")
        if sp and sp.is_linked():
            peer = sp.get_peer()
            if peer and peer.get_parent() == downstream_el:
                sp.unlink(peer)

        # Podłącz: upstream → conv_in ... conv_out → downstream
        if not upstream_el.link(self._conv_in):
            print(f"  [BandLimiter:{self.name}] inject: upstream→conv_in FAIL")
        if not self._conv_out.link(downstream_el):
            print(f"  [BandLimiter:{self.name}] inject: conv_out→downstream FAIL")

        # Synchronizuj stan z pipeline
        for el in self._all_els():
            el.sync_state_with_parent()

        self._injected = True
        print(f"  [BandLimiter:{self.name}] injected: "
              f"{upstream_el.get_name()} → [{self.name}] → {downstream_el.get_name()}")

    def eject(self):
        """Wysuwa węzeł z pipeline, przywraca bezpośrednie połączenie."""
        if not self._injected:
            return
        up, dn = self._upstream, self._downstream

        # Zatrzymaj elementy węzła
        for el in self._all_els():
            el.set_state(Gst.State.NULL)

        # Odepnij
        sp = up.get_static_pad("src")
        if sp and sp.is_linked():
            peer = sp.get_peer(); peer and sp.unlink(peer)

        sk = self._conv_in.get_static_pad("sink")
        if sk and sk.is_linked():
            peer = sk.get_peer(); peer and peer.unlink(sk)

        sp2 = self._conv_out.get_static_pad("src")
        if sp2 and sp2.is_linked():
            peer = sp2.get_peer(); peer and sp2.unlink(peer)

        sk2 = dn.get_static_pad("sink")
        if sk2 and sk2.is_linked():
            peer = sk2.get_peer(); peer and peer.unlink(sk2)

        # Przywróć bezpośrednie połączenie
        if not up.link(dn):
            print(f"  [BandLimiter:{self.name}] eject: restore link FAIL")

        self._injected = False
        print(f"  [BandLimiter:{self.name}] ejected")

    def _all_els(self):
        els = [self._conv_in, self._caps_f32, self._filter, self._limiter, self._level, self._conv_out]
        hi = getattr(self, "_band_hi", None)
        if hi: els.insert(1, hi)
        return [e for e in els if e]

    # ── Kontrola parametrów ─────────────────────────────────────────────────

    def set_threshold(self, v):
        """v: 0.0..1.0"""
        v = max(0.01, min(1.0, float(v)))
        if self._limiter: self._limiter.set_property("threshold", v)

    def set_ratio(self, v):
        """v: 1.0..20.0"""
        v = max(1.0, min(20.0, float(v)))
        if self._limiter: self._limiter.set_property("ratio", v)

    def set_enabled(self, en):
        self.enabled = en
        if en:
            if not self._injected and self._upstream and self._downstream:
                self.inject(self._upstream, self._downstream)
        else:
            if self._injected:
                self.eject()

    # ── Odczyt poziomu z GST bus ────────────────────────────────────────────

    def handle_level_message(self, structure):
        """
        Parsuje wiadomość 'level' z GST bus.
        Element 'level' wysyła rms/peak jako tablice (jedna wartość per kanał).
        Zachowujemy osobno L i R dla poprawnego pomiaru stereo.
        """
        try:
            rms_arr  = structure.get_value("rms")
            peak_arr = structure.get_value("peak")
            # rms_arr/peak_arr to listy dB per kanał: [L_db, R_db]
            if rms_arr and len(rms_arr) >= 1:
                self.rms_db   = max(rms_arr)           # ogólny (do AutoLevels)
                self.rms_l_db = rms_arr[0]
                self.rms_r_db = rms_arr[1] if len(rms_arr) > 1 else rms_arr[0]
            if peak_arr and len(peak_arr) >= 1:
                self.peak_db   = max(peak_arr)
                self.peak_l_db = peak_arr[0]
                self.peak_r_db = peak_arr[1] if len(peak_arr) > 1 else peak_arr[0]
            if self.on_level:
                self.on_level(self, self.rms_db, self.peak_db)
        except Exception as e:
            pass   # ciche — nie zaśmiecaj konsoli per każdą ramkę


class MultibandLimiter:
    """
    Zarządca N instancji BandLimiterNode.
    Wstrzykuje wszystkie między tymi samymi dwoma węzłami pipeline
    przez tee → [node0, node1, ...] → audiomixer.

    Schemat:
        upstream → tee → queue → BandNode0 → mixer
                       → queue → BandNode1 → mixer
                       → ...                       → downstream

    Użycie:
        mbl = MultibandLimiter(pipeline, "mbl_main", MBLIMIT_BANDS)
        mbl.inject(sp_echo, conv_out)
        mbl.set_enabled(True)
        mbl.set_band_threshold(2, 0.7)
        mbl.set_band_ratio(2, 3.0)
        # z on_bus: mbl.handle_bus_message(structure)
    """

    def __init__(self, pipeline, name_prefix, bands_cfg, on_level=None):
        self.pipeline     = pipeline
        self.prefix       = name_prefix
        self.on_level     = on_level
        self.enabled      = False
        self._injected    = False
        self._upstream    = None
        self._downstream  = None

        # AutoInsert state
        self._autoinsert_en     = False
        self._user_forced       = False   # True = użytkownik ręcznie ustawił stan, AI nie nadpisuje
        self._ai_owns_inject    = False   # True = AI samo wstrzyknęło, może sam wysunąć
        self._ai_threshold_db   = -12.0
        self._ai_hold_frames    = 4
        self._ai_release_frames = 20
        self._ai_above_frames   = 0
        self._ai_below_frames   = 0
        self._on_ai_state       = None

        # AutoLevels state
        self._autolevels_en = False
        self._al_headroom   = 1.05
        self._al_alpha      = 0.05
        self._al_min_thr    = 0.3
        self._al_max_thr    = 0.98
        self._on_al_update  = None

        # Tee do rozdzielenia sygnału
        self._tee   = Gst.ElementFactory.make("tee",        f"{name_prefix}_tee")
        self._mixer = Gst.ElementFactory.make("audiomixer", f"{name_prefix}_mix")
        # audiomixer: wyłącz normalizację — każde pasmo ma swój poziom
        if self._mixer:
            try: self._mixer.set_property("output-buffer-duration", 10_000_000)
            except: pass
        # caps_out po mikserze — stabilizuje format F32LE przed conv
        self._caps_out = Gst.ElementFactory.make("capsfilter", f"{name_prefix}_caps_out")
        if self._caps_out:
            self._caps_out.set_property("caps", Gst.Caps.from_string("audio/x-raw,format=F32LE"))
        self._conv  = Gst.ElementFactory.make("audioconvert", f"{name_prefix}_conv")
        for el in [self._tee, self._mixer, self._caps_out, self._conv]:
            if el: pipeline.add(el)

        # Kolejki między tee a każdym węzłem (tee wymaga queue)
        self._queues = []
        for i in range(len(bands_cfg)):
            q = Gst.ElementFactory.make("queue", f"{name_prefix}_q{i}")
            if q:
                q.set_property("max-size-buffers", 4)
                q.set_property("max-size-time", 0)
                q.set_property("max-size-bytes", 0)
                pipeline.add(q)
            self._queues.append(q)

        # Utwórz węzły BandLimiterNode
        self.nodes = []
        for i, cfg in enumerate(bands_cfg):
            node = BandLimiterNode(
                pipeline  = pipeline,
                name      = f"{name_prefix}_b{i}",
                band_cfg  = cfg,
                on_level  = self._on_node_level,
            )
            self.nodes.append(node)

        # Połącz wewnętrznie: tee→queue[i]→node[i].conv_in ... node[i].conv_out→mixer
        for i, (q, node) in enumerate(zip(self._queues, self.nodes)):
            if q and self._tee:
                if not self._tee.link(q):
                    print(f"  [MBL] tee→q{i} fail")
            if q and node._conv_in:
                if not q.link(node._conv_in):
                    print(f"  [MBL] q{i}→node fail")
            # node ma już połączone wewnętrzne elementy
            # podłącz conv_out węzła → mixer
            if node._conv_out and self._mixer:
                if not node._conv_out.link(self._mixer):
                    print(f"  [MBL] node{i}→mixer fail")

        # mixer → caps_out → conv → downstream
        if self._mixer and self._caps_out and self._conv:
            self._mixer.link(self._caps_out)
            self._caps_out.link(self._conv)
        elif self._mixer and self._conv:
            self._mixer.link(self._conv)

    def set_enabled(self, en, _from_autoinsert=False):
        # _injected jest jedynym source of truth — enabled jest tylko alias
        if en == self._injected:
            return
        # Jeśli autoinsert próbuje zmienić stan który użytkownik ręcznie ustawił — ignoruj
        if _from_autoinsert and self._user_forced:
            return
        if not _from_autoinsert:
            self._user_forced = True   # użytkownik ręcznie ustawił — blokuj autoinsert
            self._ai_owns_inject = False  # AI nie jest właścicielem tego stanu
        if en:
            if self._upstream and self._downstream:
                self.inject(self._upstream, self._downstream)
        else:
            self.eject()


    def inject(self, upstream_el, downstream_el):
        """Wstrzykuje cały multiband limiter między dwa elementy."""
        if self._injected:
            return   # już wstrzyknięty — ignoruj
        self._upstream   = upstream_el
        self._downstream = downstream_el

        # Odepnij bezpośrednie połączenie upstream→downstream
        sp = upstream_el.get_static_pad("src")
        if sp and sp.is_linked():
            peer = sp.get_peer()
            if peer: sp.unlink(peer)

        if not upstream_el.link(self._tee):
            print(f"  [MBL] upstream→tee FAIL")
            upstream_el.link(downstream_el)   # przywróć
            return
        if not self._conv.link(downstream_el):
            print(f"  [MBL] conv→downstream FAIL")
            upstream_el.unlink(self._tee)
            upstream_el.link(downstream_el)   # przywróć
            return

        for el in self._all_els():
            el.sync_state_with_parent()

        self._injected = True
        self.enabled   = True
        print(f"  [MBL:{self.prefix}] injected: "
              f"{upstream_el.get_name()} → [MBL x{len(self.nodes)}] → {downstream_el.get_name()}")

    def eject(self):
        if not self._injected:
            return
        print(f"  [MBL:{self.prefix}] eject called")
        up, dn = self._upstream, self._downstream

        for el in self._all_els():
            el.set_state(Gst.State.NULL)

        sp = up.get_static_pad("src")
        if sp and sp.is_linked():
            p = sp.get_peer()
            if p: sp.unlink(p)

        sp2 = self._conv.get_static_pad("src")
        if sp2 and sp2.is_linked():
            p = sp2.get_peer()
            if p: sp2.unlink(p)

        sk = dn.get_static_pad("sink")
        if sk and sk.is_linked():
            p = sk.get_peer()
            if p: p.unlink(sk)

        if not up.link(dn):
            print(f"  [MBL] eject: restore {up.get_name()}→{dn.get_name()} FAIL")

        self._injected = False
        self.enabled   = False
        print(f"  [MBL:{self.prefix}] ejected")

    def _all_els(self):
        """Zwraca wszystkie elementy GST należące do MBL."""
        els = []
        if self._tee:      els.append(self._tee)
        els.extend([q for q in self._queues if q])
        if self._mixer:    els.append(self._mixer)
        if hasattr(self, "_caps_out") and self._caps_out: els.append(self._caps_out)
        if self._conv:     els.append(self._conv)
        for n in self.nodes:
            els.extend(n._all_els())
        return els

    # ── AutoInsert — automatyczne wstrzyknięcie gdy sygnał przekracza próg ───

    def tick_autoinsert(self, rms):
        # Nie rób nic jeśli AutoInsert nie jest włączony
        if not self._autoinsert_en:
            return

        # Inicjalizacja zmiennych dla cooldownu (wykona się tylko raz)
        if not hasattr(self, '_last_toggle_time'):
            self._last_toggle_time = time.time()  # cooldown aktywny od razu przy starcie
            self._cooldown_seconds = 2.0  # Wtyczka nie zmieni stanu częściej niż co 2 sekundy

        now = time.time()
        
        # Jeśli jesteśmy w okresie blokady (cooldown), nie rób nic
        if (now - self._last_toggle_time) < self._cooldown_seconds:
            return

        # Ustalenie histerezy - DOSTOSUJ TE WARTOŚCI DO SWOJEGO PROGRAMU
        # threshold_on to próg włączenia (np. sygnał wyższy niż -12 dB)
        # threshold_off to próg wyłączenia (np. sygnał niższy niż -25 dB)
        threshold_on = -12.0  
        threshold_off = -25.0 

        is_enabled = self.enabled  # odczyt aktualnego stanu

        if rms > threshold_on and not is_enabled:
            self._ai_owns_inject = True
            self.set_enabled(True, _from_autoinsert=True)
            self._last_toggle_time = now
        elif rms < threshold_off and is_enabled and self._ai_owns_inject:
            # AI ejectuje tylko to co sam wstrzyknął — nie nadpisuje ręcznego stanu
            self._ai_owns_inject = False
            self.set_enabled(False, _from_autoinsert=True)
            self._last_toggle_time = now

    def set_autoinsert(self, en, threshold_db=-12.0, hold_frames=4,
                       release_frames=20, on_state=None):
        """
        Konfiguruje tryb AutoInsert.
        en             — włącz/wyłącz automatykę
        threshold_db   — próg RMS w dB powyżej którego MBL się włącza (-20..-6)
        hold_frames    — ile ramek powyżej progu zanim włączy (debounce)
        release_frames — ile ramek poniżej progu zanim wyłączy
        on_state       — callback(active: bool) dla UI
        """
        self._autoinsert_en      = en
        if en:
            self._user_forced = False    # AI przejmuje kontrolę
            self._ai_owns_inject = False # zresetuj — AI zacznie od nowa
        self._ai_threshold_db    = threshold_db
        self._ai_hold_frames     = hold_frames
        self._ai_release_frames  = release_frames
        self._on_ai_state        = on_state
        self._ai_above_frames    = 0
        self._ai_below_frames    = 0
        if not en and self._injected:
            self.set_enabled(False)

    # ── AutoLevels — automatyczne dostosowanie threshold per pasmo ───────────

    def tick_autolevels(self):
        """
        Tryb AutoLevels: analizuje zmierzone poziomy RMS per pasmo
        i automatycznie przesuwa threshold każdego limitera tak, żeby
        gain reduction był stabilny i proporcjonalny do konfiguracji.

        Algorytm:
        - Cel: threshold = measured_peak * target_headroom
        - Zmiana threshold jest wygładzona (EMA z alpha=0.05)
        - Bounds: zawsze w zakresie [min_thr, max_thr] per pasmo

        Wywołuj co ~200ms (wolniejszy cykl niż AutoInsert).
        """
        if not self._autolevels_en:
            return
        for i, node in enumerate(self.nodes):
            if node.peak_db <= -79:
                continue   # brak sygnału w paśmie — pomiń
            # Zmierz szczytowy poziom (liniowy)
            peak_lin  = 10 ** (node.peak_db / 20.0)
            # Cel: threshold powinien być tuż nad szczytem * headroom
            target_thr = min(1.0, peak_lin * self._al_headroom)
            target_thr = max(self._al_min_thr, min(self._al_max_thr, target_thr))
            # Wygładź (EMA)
            node._al_thr = node._al_thr + self._al_alpha * (target_thr - node._al_thr)
            node.set_threshold(node._al_thr)
            # Powiadom UI
            if self._on_al_update:
                self._on_al_update(i, node._al_thr)

    def set_autolevels(self, en, headroom=1.05, alpha=0.05,
                       min_thr=0.3, max_thr=0.98, on_update=None):
        """
        Konfiguruje tryb AutoLevels.
        en        — włącz/wyłącz
        headroom  — mnożnik nad szczytem (1.05 = 5% margines nad pikiem)
        alpha     — szybkość śledzenia EMA (0.01=wolno .. 0.3=szybko)
        min_thr   — minimalny dopuszczalny threshold (bezpieczeństwo)
        max_thr   — maksymalny threshold (nie relaksuj za bardzo)
        on_update — callback(band_idx, new_thr) dla aktualizacji suwaków UI
        """
        self._autolevels_en = en
        self._al_headroom   = headroom
        self._al_alpha      = alpha
        self._al_min_thr    = min_thr
        self._al_max_thr    = max_thr
        self._on_al_update  = on_update
        # Inicjalizuj stan EMA w węzłach
        for node in self.nodes:
            node._al_thr = node.band_cfg["threshold"]

    def set_band_threshold(self, band_idx, v):
        if 0 <= band_idx < len(self.nodes):
            self.nodes[band_idx].set_threshold(v)

    def set_band_ratio(self, band_idx, v):
        if 0 <= band_idx < len(self.nodes):
            self.nodes[band_idx].set_ratio(v)

    def _on_node_level(self, node, rms_db, peak_db):
        if self.on_level:
            idx = next((i for i,n in enumerate(self.nodes) if n is node), -1)
            self.on_level(idx, rms_db, peak_db)

    def handle_bus_message(self, structure):
        """Sprawdza do którego węzła należy wiadomość level i przekazuje."""
        # GStreamer wysyła ścieżkę elementu np. "carbon/mbl_b0_level"
        # Szukamy po nazwie elementu _level (nie node.name)
        src_name = structure.get_string("GstObject-path") or ""
        if not src_name:
            # Fallback: sprawdź przez msg source (GstObject-name)
            src_name = structure.get_string("GstObject-name") or ""
        for node in self.nodes:
            lvl_name = node._level.get_name() if node._level else ""
            if lvl_name and (lvl_name in src_name or node.name in src_name):
                node.handle_level_message(structure)
                return


# ============================================================================
# MULTIBAND LIMITER WIDGET
# ============================================================================
class MultibandLimiterWidget(QGroupBox):
    """
    Panel UI dla MultibandLimiter z trybami AutoInsert i AutoLevels.
    """
    SS = (
        "QGroupBox{color:#FF8844;border:1px solid #3A2010;"
        "margin-top:10px;font-weight:bold;background:#0C0906}"
        "QLabel{color:#AA6633;font-size:9px}"
        "QSlider::groove:vertical{width:4px;background:#1A1005;border-radius:2px}"
        "QSlider::handle:vertical{background:#FF8844;width:10px;height:10px;"
        "margin:0 -3px;border-radius:5px}"
        "QSlider::groove:horizontal{height:4px;background:#1A1005;border-radius:2px}"
        "QSlider::handle:horizontal{background:#FF8844;width:10px;height:10px;"
        "margin:-3px 0;border-radius:5px}"
        "QCheckBox{color:#FF8844;font-weight:bold;spacing:4px}"
        "QCheckBox::indicator{width:12px;height:12px;border:1px solid #FF6622;"
        "border-radius:2px;background:#0C0906}"
        "QCheckBox::indicator:checked{background:#FF6622}"
        "QPushButton{background:#1A0E08;color:#FF8844;border:1px solid #3A2010;"
        "padding:2px 8px;border-radius:3px;font-size:10px}"
        "QPushButton:checked{background:#3A1A00;color:#FFB060;border-color:#FF8844}"
        "QPushButton:hover{border-color:#FF8844}"
    )

    def __init__(self, parent=None):
        super().__init__("⚡ Multiband Limiter", parent)
        self.setStyleSheet(self.SS)
        self.mbl: MultibandLimiter = None
        self._band_widgets = []   # [(thr_sl, rat_sl, meter), ...]
        self._thr_lbls     = []
        self._overall_rms  = -80.0

        # Timery automatyzacji
        self._ai_timer = QTimer(); self._ai_timer.setInterval(50)
        self._ai_timer.timeout.connect(self._ai_tick)
        self._al_timer = QTimer(); self._al_timer.setInterval(200)
        self._al_timer.timeout.connect(self._al_tick)

        self._build()

    def set_mbl(self, mbl: MultibandLimiter):
        self.mbl = mbl
        for i, (cfg, (thr_sl, rat_sl, _)) in enumerate(
                zip(MBLIMIT_BANDS, self._band_widgets)):
            thr_sl.setValue(int(cfg["threshold"] * 100))
            rat_sl.setValue(int(cfg["ratio"] * 10))
        mbl.on_level = self._on_level
        QTimer.singleShot(500, self._connect_mbl_signals)

    def _connect_mbl_signals(self):
        """Podpina sygnały akcyjne po inicjalizacji — unika spurious clicked."""
        self._en.clicked.connect(self._toggle_enable)
        self._ai_en.clicked.connect(self._toggle_ai)
        self._al_en.clicked.connect(self._toggle_al)

    def update_overall_rms(self, rms_db):
        """Wywoływane z _spectrum() w głównym oknie — ogólny poziom dla AutoInsert."""
        self._overall_rms = rms_db

    # ── Budowa UI ────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 14, 6, 6); root.setSpacing(5)

        # ── Wiersz 1: ACTIVE + status ──────────────────────────────────────
        hdr = QHBoxLayout(); hdr.setSpacing(6)
        self._en = QCheckBox("ACTIVE")
        # clicked podpięty dopiero po set_mbl przez _connect_mbl_signals
        hdr.addWidget(self._en)
        self._status_lbl = QLabel("— wyłączony —")
        self._status_lbl.setStyleSheet("color:#555;font-size:9px")
        hdr.addWidget(self._status_lbl); hdr.addStretch()
        root.addLayout(hdr)

        # ── Wiersz 2: AutoInsert controls ─────────────────────────────────
        ai_box = QGroupBox("AutoInsert")
        ai_box.setStyleSheet(
            "QGroupBox{color:#FFAA44;border:1px solid #2A1808;"
            "margin-top:8px;font-size:9px;background:#0E0A06}"
            "QLabel{color:#886633;font-size:9px}"
            "QSlider::groove:horizontal{height:3px;background:#1A1005}"
            "QSlider::handle:horizontal{background:#FFAA44;width:8px;height:8px;margin:-2px 0;border-radius:4px}"
            "QCheckBox{color:#FFAA44;font-size:9px}"
            "QCheckBox::indicator{width:10px;height:10px;border:1px solid #FFAA44;border-radius:2px;background:#0E0A06}"
            "QCheckBox::indicator:checked{background:#FFAA44}")
        ai_v = QVBoxLayout(ai_box); ai_v.setContentsMargins(5,10,5,5); ai_v.setSpacing(3)

        ai_r1 = QHBoxLayout(); ai_r1.setSpacing(6)
        self._ai_en = QCheckBox("Włącz AutoInsert")
        # clicked podpięty dopiero po set_mbl
        ai_r1.addWidget(self._ai_en)
        self._ai_indicator = QLabel("◯")
        self._ai_indicator.setStyleSheet("color:#444;font-size:14px")
        ai_r1.addWidget(self._ai_indicator); ai_r1.addStretch()
        ai_v.addLayout(ai_r1)

        ai_r2 = QHBoxLayout(); ai_r2.setSpacing(4)
        ai_r2.addWidget(QLabel("Próg RMS:"))
        self._ai_thr_sl = QSlider(Qt.Orientation.Horizontal)
        self._ai_thr_sl.setRange(-40, -3); self._ai_thr_sl.setValue(-12)
        self._ai_thr_lbl = QLabel("-12 dB"); self._ai_thr_lbl.setFixedWidth(44)
        self._ai_thr_sl.valueChanged.connect(
            lambda v: (self._ai_thr_lbl.setText(f"{v} dB"),
                       self.mbl and self.mbl._autoinsert_en and
                       self.mbl.set_autoinsert(True, threshold_db=float(v))))
        ai_r2.addWidget(self._ai_thr_sl); ai_r2.addWidget(self._ai_thr_lbl)
        ai_v.addLayout(ai_r2)
        root.addWidget(ai_box)

        # ── Wiersz 3: AutoLevels controls ─────────────────────────────────
        al_box = QGroupBox("AutoLevels")
        al_box.setStyleSheet(
            "QGroupBox{color:#44FFAA;border:1px solid #082A18;"
            "margin-top:8px;font-size:9px;background:#060E0A}"
            "QLabel{color:#336655;font-size:9px}"
            "QSlider::groove:horizontal{height:3px;background:#051A0A}"
            "QSlider::handle:horizontal{background:#44FFAA;width:8px;height:8px;margin:-2px 0;border-radius:4px}"
            "QCheckBox{color:#44FFAA;font-size:9px}"
            "QCheckBox::indicator{width:10px;height:10px;border:1px solid #44FFAA;border-radius:2px;background:#060E0A}"
            "QCheckBox::indicator:checked{background:#44FFAA}")
        al_v = QVBoxLayout(al_box); al_v.setContentsMargins(5,10,5,5); al_v.setSpacing(3)

        al_r1 = QHBoxLayout(); al_r1.setSpacing(6)
        self._al_en = QCheckBox("Włącz AutoLevels")
        # clicked podpięty dopiero po set_mbl
        al_r1.addWidget(self._al_en); al_r1.addStretch()
        al_v.addLayout(al_r1)

        al_r2 = QHBoxLayout(); al_r2.setSpacing(4)
        al_r2.addWidget(QLabel("Szybkość:"))
        self._al_speed_sl = QSlider(Qt.Orientation.Horizontal)
        self._al_speed_sl.setRange(1, 30); self._al_speed_sl.setValue(5)
        self._al_speed_lbl = QLabel("α=0.05"); self._al_speed_lbl.setFixedWidth(44)
        self._al_speed_sl.valueChanged.connect(
            lambda v: (self._al_speed_lbl.setText(f"α={v/100:.2f}"),
                       self.mbl and self.mbl._autolevels_en and
                       setattr(self.mbl, '_al_alpha', v/100)))
        al_r2.addWidget(self._al_speed_sl); al_r2.addWidget(self._al_speed_lbl)
        al_v.addLayout(al_r2)
        root.addWidget(al_box)

        # ── Wiersz 4: Per-pasmo metr + suwaki ──────────────────────────────
        grid = QHBoxLayout(); grid.setSpacing(8)
        for i, cfg in enumerate(MBLIMIT_BANDS):
            col = QVBoxLayout(); col.setSpacing(2)

            name_lbl = QLabel(cfg["name"])
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            name_lbl.setStyleSheet(
                f"color:{cfg['color']};font-weight:bold;font-size:10px")
            col.addWidget(name_lbl)

            meter = BandMeter(cfg["color"])
            meter.setFixedSize(28, 90)
            col.addWidget(meter, alignment=Qt.AlignmentFlag.AlignHCenter)

            thr_lbl = QLabel(f"THR\n{cfg['threshold']:.2f}")
            thr_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            thr_lbl.setFixedWidth(36)
            col.addWidget(thr_lbl)
            thr_sl = QSlider(Qt.Orientation.Vertical)
            thr_sl.setRange(10, 100); thr_sl.setValue(int(cfg["threshold"] * 100))
            thr_sl.setFixedHeight(55); thr_sl.setFixedWidth(20)
            thr_sl.valueChanged.connect(lambda v, idx=i, lbl=thr_lbl:
                (lbl.setText(f"THR\n{v/100:.2f}"),
                 self.mbl and self.mbl.set_band_threshold(idx, v/100)))
            col.addWidget(thr_sl, alignment=Qt.AlignmentFlag.AlignHCenter)

            rat_lbl = QLabel(f"RAT\n{cfg['ratio']:.1f}")
            rat_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            rat_lbl.setFixedWidth(36)
            col.addWidget(rat_lbl)
            rat_sl = QSlider(Qt.Orientation.Vertical)
            rat_sl.setRange(10, 200); rat_sl.setValue(int(cfg["ratio"] * 10))
            rat_sl.setFixedHeight(40); rat_sl.setFixedWidth(20)
            rat_sl.valueChanged.connect(lambda v, idx=i, lbl=rat_lbl:
                (lbl.setText(f"RAT\n{v/10:.1f}"),
                 self.mbl and self.mbl.set_band_ratio(idx, v/10)))
            col.addWidget(rat_sl, alignment=Qt.AlignmentFlag.AlignHCenter)

            self._band_widgets.append((thr_sl, rat_sl, meter))
            self._thr_lbls.append(thr_lbl)
            grid.addLayout(col)

        root.addLayout(grid)

    # ── Callbacki UI ────────────────────────────────────────────────────────

    def _toggle_enable(self, en):
        if self.mbl:
            # Guard: nie wywoluj jesli MBL juz w zadanym stanie
            if en == self.mbl._injected:
                return
            self.mbl.set_enabled(en)
        txt = "● AKTYWNY" if en else "— wyłączony —"
        col = "#FF8844" if en else "#555"
        self._status_lbl.setText(txt)
        self._status_lbl.setStyleSheet(f"color:{col};font-size:9px")

    def _toggle_ai(self, en):
        if not self.mbl: return
        thr = float(self._ai_thr_sl.value())
        self.mbl.set_autoinsert(en, threshold_db=thr,
                                on_state=self._on_ai_state_change)
        if en:
            self._ai_timer.start()
        else:
            self._ai_timer.stop()
            self._ai_indicator.setText("◯")
            self._ai_indicator.setStyleSheet("color:#444;font-size:14px")

    def _toggle_al(self, en):
        if not self.mbl: return
        alpha = self._al_speed_sl.value() / 100.0
        self.mbl.set_autolevels(en, alpha=alpha,
                                on_update=self._on_al_thr_update)
        if en:
            self._al_timer.start()
            # AutoLevels wymaga żeby MBL był aktywny — włącz tylko jeśli AI nie jest aktywny
            if not self.mbl._injected and not self._ai_timer.isActive():
                self._en.blockSignals(True)
                self._en.setChecked(True)
                self._en.blockSignals(False)
                self.mbl.set_enabled(True)
                self._status_lbl.setText("● AKTYWNY")
                self._status_lbl.setStyleSheet("color:#FF8844;font-size:9px")
        else:
            self._al_timer.stop()

    def _ai_tick(self):
        if self.mbl:
            self.mbl.tick_autoinsert(self._overall_rms)

    def _al_tick(self):
        if self.mbl:
            self.mbl.tick_autolevels()

    def _on_ai_state_change(self, active):
        """Callback z AutoInsert — aktualizuje wskaźnik LED."""
        GLib.idle_add(self._update_ai_indicator, active)

    def _update_ai_indicator(self, active):
        if active:
            self._ai_indicator.setText("●")
            self._ai_indicator.setStyleSheet("color:#FF4400;font-size:14px")
            # Automatycznie włącz checkbox ACTIVE jeśli nie jest
            if not self._en.isChecked():
                self._en.blockSignals(True)
                self._en.setChecked(True)
                self._en.blockSignals(False)
                self._status_lbl.setText("● AKTYWNY (Auto)")
                self._status_lbl.setStyleSheet("color:#FF8844;font-size:9px")
        else:
            self._ai_indicator.setText("◯")
            self._ai_indicator.setStyleSheet("color:#444;font-size:14px")
            if self._en.isChecked():
                self._en.blockSignals(True)
                self._en.setChecked(False)
                self._en.blockSignals(False)
                self._status_lbl.setText("— wyłączony (Auto) —")
                self._status_lbl.setStyleSheet("color:#555;font-size:9px")

    def _on_al_thr_update(self, band_idx, new_thr):
        """Callback z AutoLevels — przesuwa suwaki threshold w UI."""
        if 0 <= band_idx < len(self._band_widgets):
            thr_sl, _, _ = self._band_widgets[band_idx]
            thr_sl.blockSignals(True)
            thr_sl.setValue(int(new_thr * 100))
            thr_sl.blockSignals(False)
            if band_idx < len(self._thr_lbls):
                self._thr_lbls[band_idx].setText(f"THR\n{new_thr:.2f}")

    def _on_level(self, band_idx, rms_db, peak_db):
        """Wywoływany z MultibandLimiter gdy przychodzi wiadomość level."""
        if 0 <= band_idx < len(self._band_widgets):
            _, _, meter = self._band_widgets[band_idx]
            node = self.mbl.nodes[band_idx] if self.mbl else None
            if node:
                GLib.idle_add(meter.update_level, rms_db, peak_db,
                              node.rms_l_db, node.rms_r_db,
                              node.peak_l_db, node.peak_r_db)
            else:
                GLib.idle_add(meter.update_level, rms_db, peak_db)


class BandMeter(QWidget):
    """
    Pionowy metr poziomu dla jednego pasma MBL.
    Pokazuje osobno kanał L (lewy słupek) i R (prawy słupek)
    dla weryfikacji separacji stereo.
    """

    def __init__(self, color="#FF8844", parent=None):
        super().__init__(parent)
        self._color     = QColor(color)
        self._rms_l     = -80.0
        self._rms_r     = -80.0
        self._peak_l    = -80.0
        self._peak_r    = -80.0
        self._ph_l      = -80.0   # peak hold L
        self._ph_r      = -80.0   # peak hold R
        self._ph_timer  = 0

    def update_level(self, rms_db, peak_db, rms_l=None, rms_r=None,
                     peak_l=None, peak_r=None):
        """Przyjmuje poziomy per kanał L/R lub fallback na mono."""
        self._rms_l  = max(-80.0, min(0.0, rms_l  if rms_l  is not None else rms_db))
        self._rms_r  = max(-80.0, min(0.0, rms_r  if rms_r  is not None else rms_db))
        self._peak_l = max(-80.0, min(0.0, peak_l if peak_l is not None else peak_db))
        self._peak_r = max(-80.0, min(0.0, peak_r if peak_r is not None else peak_db))
        pk = max(self._peak_l, self._peak_r)
        if pk > max(self._ph_l, self._ph_r):
            self._ph_l     = self._peak_l
            self._ph_r     = self._peak_r
            self._ph_timer = 35
        else:
            self._ph_timer -= 1
            if self._ph_timer <= 0:
                fall = 1.5
                self._ph_l = max(self._ph_l - fall, self._rms_l)
                self._ph_r = max(self._ph_r - fall, self._rms_r)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#080604"))

        def db_to_y(db):
            return int(h * (1.0 - (max(-80.0, db) + 80.0) / 80.0))

        # Gradient wspólny
        grad = QLinearGradient(0, h, 0, 0)
        grad.setColorAt(0.00, QColor("#006622"))
        grad.setColorAt(0.55, QColor("#888800"))
        grad.setColorAt(0.80, self._color)
        grad.setColorAt(1.00, QColor("#FF1111"))
        brush = QBrush(grad)

        # Słupki L i R — dwie kolumny z przerwą 2px
        gap  = 2
        half = (w - gap) // 2

        for col, rms, peak_h in [
            (0,    self._rms_l, self._ph_l),
            (half + gap, self._rms_r, self._ph_r),
        ]:
            y = db_to_y(rms)
            p.fillRect(col, y, half, h - y, brush)
            # Peak hold
            if peak_h > -79:
                py = db_to_y(peak_h)
                p.fillRect(col, py, half, 1, QBrush(QColor("#FFFFFF")))

        # Skala dB (ciemne linie)
        p.setPen(QPen(QColor("#222"), 1))
        for db in [-60, -40, -20, -6]:
            y = db_to_y(db)
            p.drawLine(0, y, w, y)

        # Etykieta kanałów (bardzo mała)
        p.setPen(QPen(QColor("#444")))
        f = p.font(); f.setPixelSize(6); p.setFont(f)
        p.drawText(1, h-1, "L")
        p.drawText(half + gap + 1, h-1, "R")

        p.end()


# ============================================================================
# LIMITER ROUTER — wielopunktowe wstrzykiwanie MBL w pipeline
# ============================================================================
# Zdefiniowane punkty wstrzyknięcia w pipeline CarbonX:
#
#   INPUT    — zaraz po audioconvert wejściowym (przed Tape)
#              idealny do: ochrony przed przesterowaniem na wejściu
#
#   POST_EQ  — po EQ, przed Spatial (po kształtowaniu widma)
#              idealny do: limitowania po korekcji barwy
#
#   POST_FX  — po całym łańcuchu DSP, przed wyjściem (conv_out → hw_sink)
#              idealny do: finalny limiter master, zabezpieczenie wyjścia
#
#   POST_MON — w torze monitora (opcjonalnie, niezależnie od main)

LIMITER_POINTS = {
    "INPUT":   {"label": "Wejście",    "color": "#FF4444",
                "desc":  "Przed Tape — ochrona wejścia"},
    "POST_EQ": {"label": "Po EQ",      "color": "#FFAA00",
                "desc":  "Po EQ/Spatial — kształtowanie widma"},
    "POST_FX": {"label": "Master Out", "color": "#00FFCC",
                "desc":  "Wyjście master — finalny limit"},
}


class LimiterRouter:
    """
    Zarządza wieloma instancjami MultibandLimiter w różnych punktach pipeline.
    Każdy punkt ma własną instancję MBL z niezależnymi ustawieniami.

    Użycie:
        router = LimiterRouter(pipeline)
        router.register("POST_FX", mbl_instance, conv_out, hw_sink)
        router.enable("POST_FX", True)
        router.get("POST_FX").set_band_threshold(0, 0.8)
    """

    def __init__(self):
        self._points = {}   # point_id -> {"mbl": MBL, "up": el, "dn": el}

    def register(self, point_id, mbl, upstream_el, downstream_el):
        """
        Rejestruje punkt wstrzyknięcia.
        mbl musi być już skonstruowane z tymi samymi elementami pipeline.
        upstream/downstream to elementy GST między którymi MBL zostanie wstrzyknięty.
        """
        mbl._upstream   = upstream_el
        mbl._downstream = downstream_el
        self._points[point_id] = {
            "mbl": mbl, "up": upstream_el, "dn": downstream_el
        }
        print(f"  [Router] zarejestrowano punkt: {point_id} "
              f"({upstream_el.get_name()} → {downstream_el.get_name()})")

    def enable(self, point_id, en):
        """Włącza/wyłącza MBL w danym punkcie."""
        pt = self._points.get(point_id)
        if pt:
            pt["mbl"].set_enabled(en)

    def enable_all(self, en):
        """Włącza/wyłącza wszystkie punkty jednocześnie."""
        for pt in self._points.values():
            pt["mbl"].set_enabled(en)

    def get(self, point_id):
        """Zwraca instancję MultibandLimiter dla danego punktu."""
        pt = self._points.get(point_id)
        return pt["mbl"] if pt else None

    def active_points(self):
        """Zwraca listę aktywnych (wstrzykniętych) punktów."""
        return [pid for pid, pt in self._points.items()
                if pt["mbl"]._injected]

    def registered_points(self):
        return list(self._points.keys())


class LimiterRouterWidget(QGroupBox):
    """
    Panel UI dla LimiterRouter.
    Pokazuje wszystkie zarejestrowane punkty wstrzyknięcia z:
    - checkboxem włącz/wyłącz per punkt
    - mini-metrem pokazującym aktywność
    - przyciskiem do otwarcia szczegółowego widgetu MBL per punkt
    """
    SS = (
        "QGroupBox{color:#FF6622;border:1px solid #3A1800;"
        "margin-top:10px;font-weight:bold;background:#0A0600}"
        "QLabel{color:#884422;font-size:9px}"
        "QCheckBox{color:#FF8844;font-size:10px;spacing:4px}"
        "QCheckBox::indicator{width:12px;height:12px;border:1px solid #FF6622;"
        "border-radius:2px;background:#0A0600}"
        "QCheckBox::indicator:checked{background:#FF4400}"
        "QPushButton{background:#150800;color:#FF8844;border:1px solid #3A1800;"
        "padding:2px 6px;border-radius:3px;font-size:9px}"
        "QPushButton:hover{border-color:#FF8844}"
    )

    def __init__(self, parent=None):
        super().__init__("⚡ Limiter Points", parent)
        self.setStyleSheet(self.SS)
        self.router: LimiterRouter = None
        self._ready = False   # blokada przed spurious Qt clicked przy starcie
        self._point_widgets = {}   # point_id -> {"cb": QCheckBox, "btn": QPushButton}
        self._detail_widgets = {}  # point_id -> MultibandLimiterWidget (tworzone lazily)
        self._build()

    def _unlock(self):
        self._ready = True

    def set_router(self, router: LimiterRouter):
        self.router = router
        # Dodaj wiersz per każdy zarejestrowany punkt
        for pid in router.registered_points():
            self._add_point_row(pid)
        # Podepnij sygnały dopiero po zakończeniu renderowania (unika spurious clicked)
        QTimer.singleShot(500, self._connect_signals)

    def _connect_signals(self):
        """Podpina sygnały akcyjne po zakończeniu inicjalizacji Qt."""
        if hasattr(self, '_signals_connected'):
            return
        self._signals_connected = True
        if hasattr(self, '_all_btn'):
            self._all_btn.clicked.connect(self._on_all_on)
        if hasattr(self, '_none_btn'):
            self._none_btn.clicked.connect(self._on_all_off)
        for pid, pw in self._point_widgets.items():
            cb = pw["cb"]
            if hasattr(cb, '_pid'):
                cb.clicked.connect(lambda checked, p=pid: self._on_toggle(p, checked))
        self._ready = True  # odblokuj dopiero po podpięciu sygnałów i odczekaniu 500ms

    def _on_all_on(self):
        if not self._ready or not self.router: return
        self.router.enable_all(True)
        self._sync_checkboxes()

    def _on_all_off(self):
        if not self._ready or not self.router: return
        self.router.enable_all(False)
        self._sync_checkboxes()

    def _sync_checkboxes(self):
        """Synchronizuje stan checkboxów z aktualnym stanem MBL."""
        if not self.router:
            return
        for pid, pw in self._point_widgets.items():
            mbl = self.router.get(pid)
            if mbl:
                cb = pw["cb"]
                cb.blockSignals(True)
                cb.setChecked(mbl._injected)
                cb.blockSignals(False)

    def _build(self):
        self._root_v = QVBoxLayout(self)
        self._root_v.setContentsMargins(6, 14, 6, 6)
        self._root_v.setSpacing(4)

        # Nagłówek
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Punkt wstrzyknięcia"))
        hdr.addStretch()
        all_btn = QPushButton("Wszystkie ON")
        self._all_btn = all_btn   # podpięcie sygnału odroczone do set_router
        none_btn = QPushButton("Wszystkie OFF")
        self._none_btn = none_btn
        hdr.addWidget(all_btn); hdr.addWidget(none_btn)
        self._root_v.addLayout(hdr)

        self._points_layout = QVBoxLayout()
        self._points_layout.setSpacing(3)
        self._root_v.addLayout(self._points_layout)
        self._root_v.addStretch()

    def _add_point_row(self, point_id):
        cfg = LIMITER_POINTS.get(point_id, {"label": point_id,
                                             "color": "#888",
                                             "desc": ""})
        row = QHBoxLayout(); row.setSpacing(6)

        # Kolorowy marker
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{cfg['color']};font-size:12px")
        dot.setFixedWidth(16)
        row.addWidget(dot)

        # Nazwa i opis
        lbl = QLabel(f"{cfg['label']}  {cfg['desc']}")
        lbl.setStyleSheet(f"color:{cfg['color']};font-size:9px")
        row.addWidget(lbl, 1)

        # Checkbox
        cb = QCheckBox()
        cb.setToolTip(f"Włącz MBL w punkcie: {point_id}")
        cb._pid = point_id   # podpięcie sygnału odroczone do set_router
        row.addWidget(cb)

        # Przycisk szczegółów
        btn = QPushButton("Edytuj")
        btn.setFixedWidth(48)
        btn.clicked.connect(lambda _, pid=point_id: self._open_detail(pid))
        row.addWidget(btn)

        self._point_widgets[point_id] = {"cb": cb, "btn": btn, "dot": dot}
        self._points_layout.addLayout(row)

    def _on_toggle(self, point_id, en):
        if not self.router:
            return
        mbl = self.router.get(point_id)
        if mbl and en == mbl._injected:
            return  # guard — Qt może wysłać sygnał przy inicjalizacji
        if self.router:
            self.router.enable(point_id, en)
            self._sync_checkboxes()

    def _open_detail(self, point_id):
        """Otwiera okno szczegółów MBL dla danego punktu."""
        if point_id not in self._detail_widgets:
            w = MultibandLimiterWidget()
            mbl = self.router.get(point_id) if self.router else None
            if mbl:
                w.set_mbl(mbl)
            self._detail_widgets[point_id] = w

        dlg = self._detail_widgets[point_id]
        cfg = LIMITER_POINTS.get(point_id, {"label": point_id})
        dlg.setWindowTitle(f"MBL — {cfg['label']}")
        dlg.setWindowFlags(Qt.WindowType.Window)
        dlg.resize(460, 520)
        dlg.show()
        dlg.raise_()

    def update_point_state(self, point_id, active):
        """Aktualizuje wygląd wiersza przy zmianie stanu (np. z AutoInsert)."""
        pw = self._point_widgets.get(point_id)
        if pw:
            pw["dot"].setStyleSheet(
                f"color:{'#FF2200' if active else '#333'};font-size:12px")



# ============================================================================
# DSP AUTO-RESOLVER
# ============================================================================
# Każdy moduł ma:
#   "group"    — kategoria DSP (decyduje o priorytecie kolejności)
#   "caps_in"  — wymagany format wejściowy (None = dowolny)
#   "caps_out" — format wyjściowy po module
#   "needs_conv_before" — czy koniecznie potrzebuje audioconvert PRZED sobą
#   "needs_conv_after"  — czy koniecznie potrzebuje audioconvert PO sobie
#
# Grupy DSP i ich naturalna kolejność (niższy nr = wcześniej w łańcuchu):
#   10 PHASE     — inwersja fazy (przed wszystkim)
#   20 DYNAMICS  — gate, compressor, expander (przed EQ)
#   30 FILTER    — hi/lo pass, notch (formowanie widma)
#   40 SPATIAL   — panorama, karaoke (prosta stereo manipulacja)
#   50 TIME      — chorus/echo (czas i modulacja)
#   60 REVERB    — pogłos (na końcu efektów czasowych)
#   70 STEREO    — stereo widening (potrzebuje float stereo)
#   80 GAIN      — trim / wzmocnienie końcowe
#
# audioconvert jest wstawiany automatycznie gdy:
#   - moduł wymaga float (freeverb, stereo)
#   - moduł zmienia format caps który następny moduł nie akceptuje

DSP_META = {
    "phase_inv":  {"group": 10, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "gate":       {"group": 20, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "compressor": {"group": 20, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "expander":   {"group": 20, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "hi_pass":    {"group": 30, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "lo_pass":    {"group": 30, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "notch":      {"group": 30, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "panorama":   {"group": 40, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "karaoke":    {"group": 40, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "chorus":     {"group": 50, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
    "reverb":     {"group": 60, "needs_conv_before": True,  "needs_conv_after": True,
                   "float_required": True},   # freeverb wymaga F32 stereo
    "stereo_fx":  {"group": 70, "needs_conv_before": True,  "needs_conv_after": True,
                   "float_required": True},   # plugin 'stereo' wymaga F32
    "trim":       {"group": 80, "needs_conv_before": False, "needs_conv_after": False,
                   "float_required": False},
}

# Reguły DSP: które efekty NIE powinny być po sobie (reorder hint)
# Format: (A, B) => B powinno być PRZED A jeśli oba aktywne
DSP_REORDER_RULES = [
    # Nie filtruj PO dodaniu pogłosu — straty naturalności
    ("reverb",    "hi_pass"),
    ("reverb",    "lo_pass"),
    ("reverb",    "notch"),
    # Kompresja po EQ/filtrach (nie przed)
    ("hi_pass",   "compressor"),
    ("lo_pass",   "compressor"),
    # Gate powinien być pierwszy w dynamice
    ("compressor","gate"),
    ("expander",  "gate"),
    # Karaoke przed panoramą (karaoke operuje na mid/side)
    ("panorama",  "karaoke"),
    # Stereo widening po pogłosie (szerzej brzmi po reverb)
    ("stereo_fx", "reverb"),
    # Trim zawsze ostatni
    ("trim",      "reverb"),
    ("trim",      "stereo_fx"),
    ("trim",      "chorus"),
]


class DSPAutoResolver:
    """
    Wyznacza optymalną kolejność DSP i przebudowuje fragment pipeline
    między entry_el a exit_el.

    Strategia przebudowy:
    - Pipeline musi być w stanie NULL przed relinkingiem (GStreamer wymaga)
    - Wszystkie elementy chain są w pipeline od startu (dodane w _gst_init)
    - Rebuild tylko odpina/podpina połączenia — nie usuwa ani nie dodaje elementów
    - Konwertery (max 4 stałe sloty) też są w pipeline od startu
    """

    # Stałe sloty konwerterów — tyle ile może być potrzebnych naraz
    CONV_SLOTS = 4

    def __init__(self, pipeline, entry_el, exit_el, name_prefix="ar"):
        self.pipeline      = pipeline
        self.entry_el      = entry_el
        self.exit_el       = exit_el
        self.name_prefix   = name_prefix
        self.chain_els     = {}          # {mid: Gst.Element}
        self._convs        = []          # stałe sloty audioconvert (dodane do pipeline)
        self._current_order = None       # None = nie zbuildowane jeszcze
        self._initialized  = False
        self.limiter_router = None       # opcjonalnie: LimiterRouter — eject/re-inject wokół rebuild
        
        # --- DODANE: Zmienne do cooldownu ---
        self._last_rebuild_time = 0.0
        self._rebuild_cooldown  = 1.5  # Zablokuj przebudowę na 1.5 sekundy

    def set_chain_elements(self, chain_els):
        self.chain_els = chain_els

    def init_convs(self):
        """Tworzy i dodaje do pipeline stałą pulę konwerterów. Wywołać po set_chain_elements."""
        for i in range(self.CONV_SLOTS):
            name = f"{self.name_prefix}_conv{i}"
            el = Gst.ElementFactory.make("audioconvert", name)
            if el:
                self.pipeline.add(el)
                self._convs.append(el)
        self._initialized = True
        # Ustaw pustą kolejność — dzięki temu rebuild([]) będzie zawsze pomijany
        # gdy nie ma aktywnych modułów (direct link jest zrobiony przez _gst_init)
        self._current_order = []

    # ── Sortowanie DSP ───────────────────────────────────────────────────────

    def resolve_order(self, enabled_mids):
        if not enabled_mids:
            return []
        ordered = sorted(enabled_mids, key=lambda m: DSP_META.get(m, {}).get("group", 99))
        changed = True
        passes = 0
        while changed and passes < 20:
            changed = False; passes += 1
            for (after, before) in DSP_REORDER_RULES:
                if after in ordered and before in ordered:
                    ia, ib = ordered.index(after), ordered.index(before)
                    if ib > ia:
                        ordered[ia], ordered[ib] = ordered[ib], ordered[ia]
                        changed = True
        return ordered

    # ── Główna metoda rebuild ────────────────────────────────────────────────

    def rebuild(self, enabled_mids):
        if not self._initialized:
            self.init_convs()

        optimal = self.resolve_order(enabled_mids)

        if optimal == self._current_order:
            return optimal

        # ─── DODANE: Ochrona przed thrashingiem (Cooldown) ───────────────────
        now = time.time()
        
        # Jeśli upłynęło za mało czasu od ostatniej przebudowy, odrzucamy żądanie.
        # Wyjątek: Zawsze pozwalamy na całkowite opróżnienie łańcucha (optimal == []).
        if (now - self._last_rebuild_time) < self._rebuild_cooldown and len(optimal) > 0:
            return self._current_order
            
        self._last_rebuild_time = now
        # ─────────────────────────────────────────────────────────────────────────

        print(f"[AutoResolver:{self.name_prefix}] {self._current_order} → {optimal}")
        self._current_order = optimal

        # ── Tymczasowo wysuń aktywne MBL żeby rebuild nie zerwał ich połączeń ──
        _mbl_to_reinject = []
        if self.limiter_router:
            for pid in self.limiter_router.registered_points():
                mbl = self.limiter_router.get(pid)
                if mbl and mbl._injected:
                    mbl.eject()
                    _mbl_to_reinject.append(mbl)

        pipe = self.pipeline
        # ── 1. Zapamiętaj stan pipeline ───────────────────────────────────────
        _, cur_state, _ = pipe.get_state(0)
        was_playing = (cur_state == Gst.State.PLAYING)
        was_paused  = (cur_state == Gst.State.PAUSED)

        # ── 2. Ustaw elementy chain i konwertery w READY (nie cały pipeline) ──
        # READY pozwala na relinkowanie bez zatrzymywania src/sink
        all_chain_els = list(self.chain_els.values()) + self._convs
        for el in all_chain_els:
            if el:
                el.set_state(Gst.State.NULL)

        # ── 3. Odepnij segment entry→exit ────────────────────────────────────
        # srcpad entry_el
        sp = self.entry_el.get_static_pad("src")
        if sp and sp.is_linked():
            peer = sp.get_peer()
            if peer: sp.unlink(peer)

        # Wszystkie chain + conv: odepnij srcpad i sinkpad
        for el in all_chain_els:
            if not el: continue
            sp2 = el.get_static_pad("src")
            if sp2 and sp2.is_linked():
                peer = sp2.get_peer()
                if peer: sp2.unlink(peer)
            sk2 = el.get_static_pad("sink")
            if sk2 and sk2.is_linked():
                peer = sk2.get_peer()
                if peer: peer.unlink(sk2)

        # sinkpad exit_el
        sk = self.exit_el.get_static_pad("sink")
        if sk and sk.is_linked():
            peer = sk.get_peer()
            if peer: peer.unlink(sk)

        # ── 4. Zbuduj sekwencję elementów z konwerterami ─────────────────────
        sequence = []
        conv_idx  = 0
        prev_meta = None

        for i, mid in enumerate(optimal):
            meta = DSP_META.get(mid, {})
            el   = self.chain_els.get(mid)
            if not el:
                continue

            need_pre = meta.get("needs_conv_before", False)
            if not need_pre and prev_meta and prev_meta.get("needs_conv_after", False):
                need_pre = True

            if need_pre and conv_idx < len(self._convs):
                sequence.append(self._convs[conv_idx]); conv_idx += 1

            sequence.append(el)

            if meta.get("needs_conv_after", False):
                next_mid  = optimal[i+1] if i+1 < len(optimal) else None
                next_meta = DSP_META.get(next_mid, {}) if next_mid else {}
                if not next_meta.get("float_required", False):
                    if conv_idx < len(self._convs):
                        sequence.append(self._convs[conv_idx]); conv_idx += 1

            prev_meta = meta

        # ── 5. Podłącz: entry → [sequence] → exit ────────────────────────────
        chain = [self.entry_el] + sequence + [self.exit_el]

        # Ustaw NULL → READY przed linkowaniem (tylko elementy w środku)
        for el in sequence:
            el.set_state(Gst.State.NULL)
            el.set_state(Gst.State.READY)

        ok = True
        for a, b in zip(chain, chain[1:]):
            if not a.link(b):
                print(f"  [AutoResolver] BŁĄD link: {a.get_name()} → {b.get_name()}")
                ok = False

        if ok:
            print(f"  łańcuch: {' → '.join(e.get_name() for e in chain)}")

        # ── 6. Synchronizuj elementy ze stanem pipeline (bez zatrzymywania src) ─
        for el in sequence:
            el.sync_state_with_parent()

        # ── Re-wstrzyknij MBL po przebudowie ─────────────────────────────────
        for mbl in _mbl_to_reinject:
            if mbl._upstream and mbl._downstream:
                mbl.inject(mbl._upstream, mbl._downstream)

        return optimal

    def get_current_order(self):
        return list(self._current_order) if self._current_order else []

    def format_chain_info(self):
        if not self._current_order:
            return "— brak aktywnych —"
        return " → ".join(CHAIN_DEFS.get(m,(m,))[0] for m in self._current_order)

# ============================================================================
# UTILITIES
# ============================================================================
def create_virtual_sink():
    import subprocess
    try:
        r=subprocess.run(['pactl','list','sinks','short'],
                         capture_output=True,text=True)
        if VIRTUAL_SINK in r.stdout: return True
    except: pass
    try:
        subprocess.run(['pactl','load-module','module-null-sink',
                        f'sink_name={VIRTUAL_SINK}',
                        'sink_properties=device.description="Carbon_Monitor"'],
                       check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        return True
    except Exception as e:
        print(f"Virtual sink: {e}"); return False

def cleanup_virtual_sink():
    import subprocess
    try:
        r=subprocess.run(['pactl','list','modules','short'],
                         capture_output=True,text=True)
        for line in r.stdout.split('\n'):
            if VIRTUAL_SINK in line:
                subprocess.run(['pactl','unload-module',line.split()[0]])
    except: pass

def mkgst(plugin, name, props=None):
    el=Gst.ElementFactory.make(plugin,name)
    if not el:
        print(f"  [!] Cannot create gst element: {plugin} ({name})")
        return None
    if props:
        for k,v in props.items():
            try:
                # Jawna konwersja float — unikamy problemów z locale (przecinek vs kropka)
                el.set_property(k, float(v) if isinstance(v, float) else v)
            except Exception as e: print(f"  prop {name}.{k}: {e}")
    return el

def get_metadata(uri, fn):
    p,t,a=None,fn,"Unknown"
    if uri.startswith("file://") and EYE3D_OK:
        path=uri[7:].replace("/",os.sep)
        if os.path.exists(path):
            try:
                f=eyed3.load(path)
                if f and f.tag:
                    t=f.tag.title or t; a=f.tag.artist or a
                    if f.tag.images:
                        p=QPixmap.fromImage(QImage.fromData(f.tag.images[0].image_data))
            except: pass
    for tag,artist,strip in [("[Radio]","Internet Radio","[Radio] "),
                               ("[TV]","TV Channel","[TV] "),
                               ("[Monitor]","Monitor","[Monitor] ")]:
        if tag in fn: a=artist; t=fn.replace(strip,"")
    return (p,t,a)

def blur_pixmap(p,s):
    if not p: return None
    img=p.scaled(s.width()//20,s.height()//20,
                 Qt.AspectRatioMode.IgnoreAspectRatio,
                 Qt.TransformationMode.SmoothTransformation).toImage()
    b=img.scaled(s,Qt.AspectRatioMode.IgnoreAspectRatio,
                 Qt.TransformationMode.SmoothTransformation)
    pt=QPainter(b); pt.fillRect(b.rect(),QColor(0,0,0,160)); pt.end()
    return QPixmap.fromImage(b)

def parse_m3u(fp):
    entries=[]; cur=None
    try:
        with open(fp,'r',encoding='utf-8',errors='replace') as f:
            for line in f:
                line=line.strip()
                if line.startswith('#EXTINF:'):
                    parts=line.split(',',1)
                    cur=parts[1].strip() if len(parts)>1 else None
                elif line and not line.startswith('#'):
                    name=cur or line.split('/')[-1]
                    tag="[TV]" if cur else "[Stream]"
                    entries.append((line,f"{tag} {name}")); cur=None
    except Exception as e: print(f"M3U: {e}")
    return entries

# ============================================================================
# RADIO SEARCH
# ============================================================================
class RadioSearchDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent); self.setWindowTitle("Radio Search")
        self.setModal(True); self.setMinimumSize(600,440)
        self.setStyleSheet("QDialog{background:#1a1a1e}QLabel{color:#ddd}"
            "QLineEdit,QSpinBox{background:#2a2a30;color:#eee;border:1px solid #444;padding:4px}"
            "QPushButton{background:#2a2a30;color:#eee;border:1px solid #444;padding:5px 12px}"
            "QPushButton:hover{border-color:#00AAAA}"
            "QListWidget{background:#18181c;color:#ddd;border:1px solid #333}"
            "QListWidget::item:selected{background:#0088CC}")
        self._build()

    def _build(self):
        lo=QVBoxLayout(self); lo.setSpacing(6)
        fg=QGroupBox("Filters")
        fg.setStyleSheet("QGroupBox{color:#00AAAA;border:1px solid #444;margin-top:8px;padding-top:8px}")
        fl=QVBoxLayout(fg)
        for lb,attr,ph in [("Name:","name_e","BBC, NPR..."),("Tag:","tag_e","jazz, rock..."),
                            ("Country:","country_e","Poland, USA..."),("Language:","lang_e","polish...")]:
            row=QHBoxLayout(); row.addWidget(QLabel(lb))
            w=QLineEdit(); w.setPlaceholderText(ph); setattr(self,attr,w); row.addWidget(w)
            fl.addLayout(row)
        lr=QHBoxLayout(); lr.addWidget(QLabel("Max:"))
        self.lim=QSpinBox(); self.lim.setRange(5,100); self.lim.setValue(30)
        self.lim.setFixedWidth(65); lr.addWidget(self.lim); lr.addStretch()
        fl.addLayout(lr); lo.addWidget(fg)
        sb=QPushButton("Search"); sb.setStyleSheet("background:#0088CC;font-weight:bold")
        sb.clicked.connect(self._search); lo.addWidget(sb)
        self.rl=QListWidget()
        self.rl.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        lo.addWidget(self.rl)
        self.sl=QLabel("Enter criteria and search")
        self.sl.setStyleSheet("color:#888;font-style:italic"); lo.addWidget(self.sl)
        br=QHBoxLayout(); br.addStretch()
        self.ab=QPushButton("Add Selected"); self.ab.setEnabled(False)
        self.ab.setStyleSheet("background:#00AA00"); self.ab.clicked.connect(self.accept)
        br.addWidget(self.ab)
        cb=QPushButton("Cancel"); cb.clicked.connect(self.reject); br.addWidget(cb)
        lo.addLayout(br)
        self.rl.itemSelectionChanged.connect(
            lambda: self.ab.setEnabled(len(self.rl.selectedItems())>0))

    def _search(self):
        if not PYRADIOS_OK: self.sl.setText("pyradios not installed"); return
        self.rl.clear(); self.sl.setText("Searching...")
        QApplication.processEvents()
        try:
            rb=RadioBrowser(); params={"limit":self.lim.value()}
            for attr,key in [("name_e","name"),("tag_e","tag"),
                              ("country_e","country"),("lang_e","language")]:
                v=getattr(self,attr).text().strip()
                if v: params[key]=v
            if len(params)<=1: self.sl.setText("Enter at least one filter"); return
            for s in (rb.search(**params) or []):
                n=s.get('name','?').strip(); u=s.get('url_resolved')
                if not(n and u): continue
                d=n
                if s.get('country'): d+=f" [{s['country']}]"
                if s.get('bitrate'):  d+=f" {s['bitrate']}kbps"
                item=QListWidgetItem(d); item.setData(Qt.ItemDataRole.UserRole,(u,n))
                self.rl.addItem(item)
            self.sl.setText(f"Found {self.rl.count()} stations")
        except Exception as e: self.sl.setText(f"Error: {e}")

    def get_selected(self):
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.rl.selectedItems()]

# ============================================================================
# MATRIX VISUALIZER
# ============================================================================
class MatrixVisualizer(QWidget):
    # Renderujemy na offscreen QPixmap i blitujemy — eliminuje migotanie
    # Timer kontroluje FPS (33ms = 30fps), spectrum tylko zapisuje dane bez update()
    TARGET_FPS = 30

    def __init__(self,parent=None):
        super().__init__(parent); self.setMinimumHeight(180)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)  # brak tła Qt
        self.ad=[0.0]*64; self.bl=0.0; self.ph=0.0
        self.dc=(None,"",""); self.dp=(None,"",""); self.dn=(None,"","")
        self.bg=None; self.phaser_mode="linear"; self.phase_speed=0.03; self.parts=[]
        self._cache = None   # offscreen pixmap
        self._dirty = True   # czy trzeba przerysować
        self.presets={
            "Cyberpunk":{"layers":["grid_3d","spectrum_bars","digital_rain"],"c":("#00FFFF","#FF00FF","#050010")},
            "Solar":    {"layers":["starfield","pulse_orb","flux_wave"],"c":("#FFDD00","#FF4400","#100500")},
            "Ocean":    {"layers":["flux_wave","bubbles","mirror_spectrum"],"c":("#0088FF","#00FF88","#001020")},
            "Matrix":   {"layers":["digital_rain","spectrum_bars"],"c":("#00FF00","#008800","#000000")},
            "Neon":     {"layers":["grid_3d","pulse_orb","mirror_spectrum"],"c":("#FF0055","#5500FF","#101010")},
        }
        self.curr="Cyberpunk"
        # Jeden timer — 30fps zamiast 60fps + dodatkowych update() z spectrum
        self.tm=QTimer(); self.tm.timeout.connect(self._tick); self.tm.start(1000//self.TARGET_FPS)

    def set_preset(self,n): self.curr=n; self.parts=[]; self._dirty=True
    def set_covers_data(self,p,c,n):
        self.dp=p; self.dc=c; self.dn=n
        self.bg=blur_pixmap(c[0],self.size()) if c[0] else None
        self._dirty=True
    def update_data(self,d):
        # Tylko zapisujemy dane — NIE wołamy update() — timer zrobi to co 33ms
        if d:
            self.ad=d
            self.bl=self.bl*0.8+(sum(d[:5])/5)*0.2
            self._dirty=True
    def _tick(self):
        self.ph+=self.phase_speed
        self._dirty=True   # animacja zawsze wymaga odświeżenia
        self.update()      # jeden update() per tick, nie więcej

    def paintEvent(self,event):
        w,h=self.width(),self.height()
        if w<=0 or h<=0: return
        # Rysuj na offscreen pixmap jeśli dirty lub rozmiar się zmienił
        if (self._cache is None or
                self._cache.width()!=w or self._cache.height()!=h or
                self._dirty):
            self._cache = QPixmap(w, h)
            self._render_to(self._cache, w, h)
            self._dirty = False
        # Blit z cache na ekran — bardzo szybkie
        scrn = QPainter(self)
        scrn.drawPixmap(0, 0, self._cache)
        scrn.end()

    def _render_to(self, pm, w, h):
        p=QPainter(pm)
        # Antialiasing tylko dla linii/okręgów, nie dla prostokątów
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pr=self.presets.get(self.curr,self.presets["Cyberpunk"]); c=pr["c"]
        if self.bg: p.drawPixmap(0,0,self.bg.scaled(w,h,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.FastTransformation))
        else: p.fillRect(0,0,w,h,QColor(c[2]))
        for layer in pr["layers"]:
            fn = getattr(self,f"_draw_{layer}",None)
            if fn:
                if layer in ("flux_wave","pulse_orb","digital_rain","bubbles","starfield"):
                    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                else:
                    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                fn(p,w,h,c)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self._draw_sidebar(p,w,h)
        p.end()

    def _draw_spectrum_bars(self,p,w,h,c):
        bw=w/64
        for i,v in enumerate(self.ad):
            bh=max(1,int(v*h*0.8)); x=int(i*bw)
            g=QLinearGradient(x,h,x,h-bh); g.setColorAt(0,QColor(c[0])); g.setColorAt(1,QColor(c[1]))
            p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(x+1,h-bh,max(1,int(bw)-2),bh)

    def _draw_mirror_spectrum(self,p,w,h,c):
        bw=w/64; cy=h//2
        for i,v in enumerate(self.ad):
            bh=max(1,int(v*cy*0.9)); x=int(i*bw)
            p.fillRect(x+1,cy-bh,max(1,int(bw)-2),bh*2,QColor(c[0]))

    def _draw_grid_3d(self,p,w,h,c):
        p.setPen(QPen(QColor(c[0]),1)); p.setOpacity(0.2+self.bl*0.3)
        for i in range(0,w,30): p.drawLine(i,0,i,h)
        for j in range(0,h,20): p.drawLine(0,j,w,j)
        p.setOpacity(1.0)

    def _draw_digital_rain(self,p,w,h,c):
        if len(self.parts)<40: self.parts.append([random.randint(0,w),random.randint(-h,0),random.uniform(1,4),random.randint(6,14)])
        p.setPen(QColor(c[0])); act=[]
        for pt in self.parts:
            pt[1]+=pt[2]; p.setFont(QFont("Consolas",pt[3]))
            p.drawText(int(pt[0]),int(pt[1]),chr(random.randint(33,126)))
            if pt[1]<h: act.append(pt)
        self.parts=act

    def _draw_flux_wave(self,p,w,h,c):
        p.setPen(QPen(QColor(c[0]),2)); pts=[]
        for i in range(129):
            x=i*w/128; idx=min(63,int(i*64/128))
            y=h/2+math.sin(self.ph+i*0.2)*self.ad[idx]*h*0.4
            pts.append(QPointF(x,y))
        for i in range(len(pts)-1): p.drawLine(pts[i],pts[i+1])

    def _draw_bubbles(self,p,w,h,c):
        if len(self.parts)<20: self.parts.append([random.uniform(0,w),random.uniform(0,h),random.uniform(2,8),random.uniform(1,3)])
        p.setBrush(QColor(c[0])); p.setPen(Qt.PenStyle.NoPen); act=[]
        for pt in self.parts:
            pt[1]-=pt[3]; xw=math.sin(self.ph+pt[1]*0.1)*3
            if pt[1]>-20: p.drawEllipse(QPointF(pt[0]+xw,pt[1]),pt[2],pt[2]); act.append(pt)
        self.parts=act

    def _draw_starfield(self,p,w,h,c):
        cx,cy=w/2,h/2
        if len(self.parts)<100: self.parts.append([random.uniform(0,6.28),random.uniform(10,50)])
        p.setPen(QColor(c[0])); act=[]
        for pt in self.parts:
            pt[1]*=1.05+self.bl*0.1; r=pt[1]
            x=cx+math.cos(pt[0])*r; y=cy+math.sin(pt[0])*r
            if 0<x<w and 0<y<h: p.drawEllipse(QPointF(x,y),2,2); act.append(pt)
        self.parts=act

    def _draw_pulse_orb(self,p,w,h,c):
        cx,cy=w/2,h/2; r=50+self.bl*150
        rd=QRadialGradient(cx,cy,r*1.5)
        C1=QColor(c[1]); C1.setAlpha(0); C2=QColor(c[0]); C2.setAlpha(120)
        rd.setColorAt(0,C1); rd.setColorAt(0.5,C2); rd.setColorAt(1,C1)
        p.setBrush(rd); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx,cy),r*1.5,r*1.5)
        p.setBrush(QColor(c[0])); p.drawEllipse(QPointF(cx,cy),r*0.5,r*0.5)

    def _draw_sidebar(self,p,w,h):
        sw=int(w*0.25); sx=w-sw; sy=h//3
        p.fillRect(sx,0,sw,h,QColor(0,0,0,110))
        p.setPen(QColor(255,255,255,25)); p.drawLine(sx,0,sx,h)
        self._ditm(p,self.dp,QRect(sx,0,sw,sy),0.45,"PREV")
        rc=QRect(sx,sy,sw,sy); p.fillRect(rc,QColor(255,255,255,8))
        self._ditm(p,self.dc,rc,1.0,"NOW")
        self._ditm(p,self.dn,QRect(sx,sy*2,sw,h-sy*2),0.45,"NEXT")

    def _ditm(self,p,d,r,o,l):
        px,t,a=d; p.setOpacity(o); m=8; ir=r.adjusted(m,m,-m,-m-28)
        tr=QRect(r.left()+m,ir.bottom()+2,r.width()-2*m,28)
        if px:
            s=px.scaled(ir.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
            cx2=ir.left()+(ir.width()-s.width())//2; cy2=ir.top()+(ir.height()-s.height())//2
            p.drawPixmap(cx2,cy2,s)
        else:
            p.setPen(QColor(255,255,255,25)); p.drawRect(ir)
            p.drawText(ir,Qt.AlignmentFlag.AlignCenter,l)
        p.setPen(QColor(255,255,255,255 if o==1 else 140))
        f=p.font(); f.setBold(True); p.setFont(f)
        fm=QFontMetrics(f)
        p.drawText(tr.left(),tr.top()+13,fm.elidedText(t,Qt.TextElideMode.ElideRight,tr.width()))
        f.setBold(False); f.setPointSize(max(6,f.pointSize()-1)); p.setFont(f)
        p.drawText(tr.left(),tr.top()+26,fm.elidedText(a,Qt.TextElideMode.ElideRight,tr.width()))
        p.setOpacity(1.0)

    def resizeEvent(self,e):
        if self.dc[0]: self.bg=blur_pixmap(self.dc[0],self.size())
        super().resizeEvent(e)

# ============================================================================
# SMART EQ
# ============================================================================
class SmartEQProcessor:
    def __init__(self,eq):
        self.eq=eq; self.active=False; self.geo_active=True
        self.depth=0.5; self.pm="linear"; self.ph=0.0; self.ps=0.03
        self.exposure_mode="Flat"
        self.tgt=[0.65]*10; self.base=[0.0]*10; self.curr=[0.0]*10; self.sm=0.9

    def set_base(self,i,v): self.base[i]=float(v)
    def set_all_base(self,vals): self.base=[float(v) for v in vals]

    def process(self,spec):
        if not spec: return
        self.ph+=self.ps; chunk=len(spec)//10
        for i in range(10):
            gm=0.0
            if self.geo_active:
                if self.pm=="linear":    gm=math.sin(self.ph+i*0.5)*2
                elif self.pm=="diverge": gm=math.sin(self.ph-abs(4.5-i)*0.5)*3
                elif self.pm=="converge":gm=math.sin(self.ph+abs(4.5-i)*0.5)*3
                elif self.pm=="rise":    gm=math.sin(self.ph+i*0.8)*4*(i/10)
                elif self.pm=="fall":    gm=math.sin(self.ph-i*0.8)*4*((10-i)/10)
                elif self.pm=="chaos":   gm=(random.random()-0.5)*4
            exp=0.0
            if   self.exposure_mode=="Gora":  exp=-3+(i*0.8)
            elif self.exposure_mode=="Dol":   exp=5-(i*0.8)
            elif self.exposure_mode=="Srodek":exp=5-abs(4.5-i)*1.5
            dc=0.0
            if self.active:
                s=i*chunk; ea=sum(spec[s:s+chunk])/chunk if chunk else 0
                dc=(self.tgt[i]-ea)*20*self.depth
            des=max(-12,min(12,self.base[i]+gm+dc+exp))
            self.curr[i]=self.curr[i]*self.sm+des*(1-self.sm)
            self.eq.update_vis(i,self.curr[i])

class EqualizerWidget(QGroupBox):
    def __init__(self,parent=None):
        super().__init__("Equalizer & Smart DSP",parent)
        self.setStyleSheet("""
            QGroupBox{color:#BBB;border:1px solid #333;margin-top:10px;font-weight:bold;background:#0E0E10}
            QSlider::groove:vertical{width:4px;background:#222}
            QSlider::handle:vertical{background:#00AAAA;height:10px;margin:0 -3px;border-radius:5px}
            QCheckBox{color:#00FFFF} QLabel{color:#666;font-size:9px}
            QComboBox{background:#1A1A1E;color:#EEE;border:1px solid #333;border-radius:3px}
        """)
        self.gst=None; self._mon_gst=None; self.sl=[]
        self.proc=SmartEQProcessor(self); self.prog_upd=False
        m=QVBoxLayout(self); m.setContentsMargins(5,15,5,5); m.setSpacing(4)
        pl=QHBoxLayout()
        self.chk=QCheckBox("DYNAMIC"); self.chk.toggled.connect(lambda a:setattr(self.proc,'active',a))
        self.chk_g=QCheckBox("PHASE"); self.chk_g.setChecked(True)
        self.chk_g.toggled.connect(lambda a:setattr(self.proc,'geo_active',a))
        self.exp_cb=QComboBox(); self.exp_cb.addItems(["Flat","Dol","Srodek","Gora"])
        self.exp_cb.currentTextChanged.connect(lambda v:setattr(self.proc,'exposure_mode',v))
        self.cb=QComboBox(); self.cb.addItems(list(EQ_PRESETS.keys()))
        self.cb.currentTextChanged.connect(self.app_pre)
        pl.addWidget(self.chk); pl.addWidget(self.chk_g); pl.addStretch()
        pl.addWidget(QLabel("EXP:")); pl.addWidget(self.exp_cb); pl.addWidget(self.cb)
        m.addLayout(pl)
        bl=QHBoxLayout(); bl.setSpacing(2)
        for i,f in enumerate(["32","64","125","250","500","1k","2k","4k","8k","16k"]):
            v=QVBoxLayout(); s=QSlider(Qt.Orientation.Vertical)
            s.setRange(-12,12); s.setValue(0)
            s.valueChanged.connect(lambda val,x=i:self.usr_chg(x,val))
            self.sl.append(s)
            v.addWidget(s,1,Qt.AlignmentFlag.AlignHCenter)
            v.addWidget(QLabel(f),0,Qt.AlignmentFlag.AlignHCenter); bl.addLayout(v)
        m.addLayout(bl)

    def set_gst(self,el,mon_el=None): self.gst=el; self._mon_gst=mon_el
    def usr_chg(self,i,v):
        if not self.prog_upd: self.proc.set_base(i,v); self.set_b(i,v)
    def update_vis(self,i,v):
        self.prog_upd=True; self.sl[i].setValue(int(v)); self.prog_upd=False; self.set_b(i,v)
    def set_b(self,i,v):
        for el in [self.gst,self._mon_gst]:
            if el:
                try: el.set_property(f"band{i}",float(v))
                except: pass
    def app_pre(self,n):
        if n in EQ_PRESETS:
            self.proc.set_all_base(EQ_PRESETS[n])
            if not self.proc.active and not self.proc.geo_active:
                for i,v in enumerate(EQ_PRESETS[n]): self.sl[i].setValue(v)

# ============================================================================
# ANALOG TAPE WIDGET
# ============================================================================
PHANTOM_PRESETS = {
    "Off": {
        "mode": "off", "blend": 0, "width": 5, "delay_ms": 0,
        "desc": "Brak przetwarzania — sygnał oryginalny (5% width = neutral)"
    },
    "Headphones": {
        "mode": "crossfeed", "blend": 8, "width": 5, "delay_ms": 0,
        "desc": "Crossfeed słuchawkowy — subtelny blend 8%, brak sztucznego wide"
    },
    "TV Wide": {
        "mode": "haas", "blend": 0, "width": 12, "delay_ms": 6,
        "desc": "Delikatne rozszerzenie TV — Haas 6ms, width 12%"
    },
    "Podcast Mono": {
        "mode": "haas", "blend": 0, "width": 10, "delay_ms": 8,
        "desc": "Mono naturalnie — subtelny Haas 8ms, zachowuje środek"
    },
    "Concert": {
        "mode": "haas", "blend": 5, "width": 15, "delay_ms": 12,
        "desc": "Lekka scena koncertowa — Haas 12ms, width 15%, blend 5%"
    },
    "Studio": {
        "mode": "crossfeed", "blend": 5, "width": 5, "delay_ms": 2,
        "desc": "Studio reference — minimalne crossfeed 5%, brak koloryzacji"
    },
}


class PhantomStereoWidget(QGroupBox):
    """
    Phantom Stereo Expander — wirtualizacja stereo.
    Wstrzykuje się między dwa punkty pipeline przez BandLimiterNode-style inject.

    Wewnętrzna topologia GST zależy od trybu:
      Crossfeed: audioconvert → [tee → echo_L → mixer, tee → echo_R → mixer] → conv_out
      Haas:      audioconvert → stereo → audioecho → conv_out

    W praktyce: używamy istniejących elementów sp_stereo i sp_echo z Spatial FX
    i dodajemy własne dodatkowe parametry.
    """
    SS = (
        "QGroupBox{color:#BB88FF;border:1px solid #3A2055;"
        "margin-top:10px;font-weight:bold;background:#0C0814}"
        "QLabel{color:#664488;font-size:9px}"
        "QSlider::groove:horizontal{height:3px;background:#180E28;border-radius:1px}"
        "QSlider::handle:horizontal{background:#BB88FF;width:10px;height:10px;"
        "margin:-3px 0;border-radius:5px}"
        "QCheckBox{color:#BB88FF;font-weight:bold;spacing:4px}"
        "QCheckBox::indicator{width:12px;height:12px;border:1px solid #8844CC;"
        "border-radius:2px;background:#0C0814}"
        "QCheckBox::indicator:checked{background:#8844CC}"
        "QComboBox{background:#180E28;color:#BB88FF;border:1px solid #3A2055;"
        "border-radius:3px;padding:3px 6px;font-size:10px}"
        "QComboBox QAbstractItemView{background:#180E28;color:#BB88FF;"
        "selection-background-color:#3A2055}"
        "QPushButton{background:#180E28;color:#BB88FF;border:1px solid #3A2055;"
        "padding:2px 8px;border-radius:3px;font-size:10px}"
        "QPushButton:hover{border-color:#BB88FF}"
    )

    def __init__(self, parent=None):
        super().__init__("👻 Phantom Stereo", parent)
        self.setStyleSheet(self.SS)
        # GST elements (set via set_pipeline)
        self._sw    = None   # stereo element
        self._echo  = None   # audioecho (Haas)
        self._msw   = None   # monitor stereo
        self._mecho = None   # monitor echo
        self._active = False
        self._cur_preset = "Off"
        self._sl = {}        # slider dict dla SceneManager
        self._build()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 14, 8, 6); root.setSpacing(5)

        # Row 1: enable + preset
        r1 = QHBoxLayout(); r1.setSpacing(8)
        self.en = QCheckBox("ENABLE")
        self.en.clicked.connect(self._on_en)
        r1.addWidget(self.en)
        r1.addStretch()
        r1.addWidget(QLabel("Preset:"))
        self.preset_cb = QComboBox()
        self.preset_cb.addItems(list(PHANTOM_PRESETS.keys()))
        self.preset_cb.currentTextChanged.connect(self._apply_preset)
        r1.addWidget(self.preset_cb)
        root.addLayout(r1)

        # Opis presetu
        self._desc_lbl = QLabel("Brak przetwarzania — sygnał oryginalny")
        self._desc_lbl.setStyleSheet("color:#4A3366;font-size:9px;font-style:italic")
        self._desc_lbl.setWordWrap(True)
        root.addWidget(self._desc_lbl)

        # Row 2: tryb
        r2 = QHBoxLayout(); r2.setSpacing(6)
        r2.addWidget(QLabel("Tryb:"))
        self.mode_cb = QComboBox()
        self.mode_cb.addItems(["off", "crossfeed", "haas"])
        self.mode_cb.currentTextChanged.connect(self._on_mode)
        r2.addWidget(self.mode_cb); r2.addStretch()
        root.addLayout(r2)

        # Sliders
        def mk_row(label, key, mn, mx, dv, unit=""):
            h = QHBoxLayout(); h.setSpacing(4)
            lbl = QLabel(label); lbl.setFixedWidth(100)
            h.addWidget(lbl)
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(mn, mx); sl.setValue(dv); sl.setFixedHeight(15)
            vl = QLabel(f"{dv}{unit}")
            vl.setFixedWidth(44); vl.setAlignment(Qt.AlignmentFlag.AlignRight)
            sl.valueChanged.connect(lambda v, l=vl, u=unit, k=key:
                (l.setText(f"{v}{u}"), self._on_param(k, v)))
            h.addWidget(sl); h.addWidget(vl)
            self._sl[key] = sl
            root.addLayout(h)
            return sl

        self._sl_width   = mk_row("Stereo Width:",   "width",   0,  100,   5, "%")
        self._sl_delay   = mk_row("Haas Delay:",      "delay",   0,   20,   0, " ms")
        self._sl_blend   = mk_row("Crossfeed Blend:", "blend",   0,   30,   0, "%")

        # Wskaźnik trybu
        self._mode_lbl = QLabel("● OFF")
        self._mode_lbl.setStyleSheet("color:#333;font-size:10px;font-weight:bold")
        root.addWidget(self._mode_lbl)

    # ── GStreamer ─────────────────────────────────────────────────────────────

    def set_pipeline(self, sw, echo, msw=None, mecho=None):
        """Przypisuje elementy GST z głównego pipeline."""
        self._sw    = sw
        self._echo  = echo
        self._msw   = msw
        self._mecho = mecho
        self._apply_current()

    def _s(self, el, prop, val):
        if el:
            try: el.set_property(prop, val)
            except Exception as e:
                pass  # ciche — niektóre pluginy nie mają wszystkich props

    def _on_en(self, en):
        self._active = en
        if en:
            self._apply_current()
            self._mode_lbl.setStyleSheet("color:#BB88FF;font-size:10px;font-weight:bold")
        else:
            self._bypass()
            self._mode_lbl.setText("● OFF")
            self._mode_lbl.setStyleSheet("color:#333;font-size:10px;font-weight:bold")

    def _bypass(self):
        """Przywraca neutralne wartości."""
        self._s(self._sw,    "stereo",    1.0)
        self._s(self._echo,  "delay",     1)
        self._s(self._echo,  "intensity", 0.0)
        self._s(self._echo,  "feedback",  0.0)
        self._s(self._msw,   "stereo",    1.0)
        self._s(self._mecho, "delay",     1)
        self._s(self._mecho, "intensity", 0.0)
        self._s(self._mecho, "feedback",  0.0)

    def _apply_current(self):
        if not self._active:
            return
        mode  = self.mode_cb.currentText()
        width = self._sl["width"].value() / 100.0    # 0.0..1.0
        delay = self._sl["delay"].value()             # ms
        blend = self._sl["blend"].value() / 100.0    # 0.0..0.30

        if mode == "off":
            self._bypass()

        elif mode == "haas":
            # Haas effect: stereo widening + echo delay na jednym kanale
            # stereo element robi widening, audioecho dodaje Haas opóźnienie
            self._s(self._sw,    "stereo",    max(0.0, min(1.0, width)))
            delay_ns = max(1, delay * 1_000_000)   # ms → ns
            self._s(self._echo,  "delay",     delay_ns)
            self._s(self._echo,  "intensity", 0.15 if delay > 0 else 0.0)
            self._s(self._echo,  "feedback",  0.0)
            # monitor
            self._s(self._msw,   "stereo",    max(0.0, min(1.0, width)))
            self._s(self._mecho, "delay",     delay_ns)
            self._s(self._mecho, "intensity", 0.15 if delay > 0 else 0.0)
            self._s(self._mecho, "feedback",  0.0)
            self._mode_lbl.setText(f"● HAAS  {delay}ms  width={width:.0%}")

        elif mode == "crossfeed":
            # Crossfeed: blend kanałów przez echo z delay ~1ms
            # intensity = blend level (jak dużo przeciwnego kanału)
            self._s(self._sw,    "stereo",    max(0.0, min(1.0, width)))
            self._s(self._echo,  "delay",     1_000_000)   # 1ms (minimalne opóźnienie)
            self._s(self._echo,  "intensity", max(0.0, min(0.4, blend)))
            self._s(self._echo,  "feedback",  0.0)
            self._s(self._msw,   "stereo",    max(0.0, min(1.0, width)))
            self._s(self._mecho, "delay",     1_000_000)
            self._s(self._mecho, "intensity", max(0.0, min(0.4, blend)))
            self._s(self._mecho, "feedback",  0.0)
            self._mode_lbl.setText(f"● CROSSFEED  blend={blend:.0%}  width={width:.0%}")

        self._mode_lbl.setStyleSheet("color:#BB88FF;font-size:10px;font-weight:bold")

    def _on_mode(self, mode):
        self._apply_current()

    def _on_param(self, key, val):
        self._apply_current()

    def _apply_preset(self, name):
        p = PHANTOM_PRESETS.get(name)
        if not p:
            return
        self._cur_preset = name
        self._desc_lbl.setText(p.get("desc", ""))

        # Ustaw kontrolki
        mode_idx = {"off": 0, "crossfeed": 1, "haas": 2}.get(p["mode"], 0)
        self.mode_cb.blockSignals(True)
        self.mode_cb.setCurrentIndex(mode_idx)
        self.mode_cb.blockSignals(False)

        for key, val in [("width", p["width"]), ("delay", p["delay_ms"]),
                          ("blend", p["blend"])]:
            sl = self._sl.get(key)
            if sl:
                sl.blockSignals(True)
                sl.setValue(int(val))
                sl.blockSignals(False)

        self._apply_current()

    # ── SceneManager interface ────────────────────────────────────────────────

    def get_state(self):
        return {
            "active":  self.en.isChecked(),
            "preset":  self._cur_preset,
            "mode":    self.mode_cb.currentText(),
            "width":   self._sl["width"].value(),
            "delay":   self._sl["delay"].value(),
            "blend":   self._sl["blend"].value(),
        }

    def set_state(self, s):
        if not s:
            return
        preset = s.get("preset", "Off")
        if preset in PHANTOM_PRESETS:
            self.preset_cb.blockSignals(True)
            self.preset_cb.setCurrentText(preset)
            self.preset_cb.blockSignals(False)
            self._apply_preset(preset)

        # Nadpisz wartości z state jeśli różne od presetu
        for key in ["width", "delay", "blend"]:
            if key in s:
                sl = self._sl.get(key)
                if sl:
                    sl.blockSignals(True)
                    sl.setValue(int(s[key]))
                    sl.blockSignals(False)

        active = s.get("active", False)
        self.en.blockSignals(True)
        self.en.setChecked(active)
        self.en.blockSignals(False)
        self._on_en(active)


class AnalogTapeWidget(QGroupBox):
    def __init__(self,parent=None):
        super().__init__("ATS-1 Tape Simulation",parent)
        self.setStyleSheet("QGroupBox{color:#FFCC00;border:1px solid #444;"
            "margin-top:10px;font-weight:bold;background:#151515}"
            "QLabel{color:#888;font-size:9px} QDial{background:#111}"
            "QPushButton{background:#330000;color:#555;border:1px solid #444}"
            "QPushButton:checked{background:#CC0000;color:#FFF;border:1px solid #F00}")
        self._main={}; self._mon={}; self._dials=[]
        # Safe limits: DRIVE<=40, WARMTH<=50, COMP<=30
        self._safe_limits = {"DRIVE":40,"WARMTH":50,"COMP":30}
        self._safe_mode = False
        l=QHBoxLayout(self); l.setSpacing(12); l.setContentsMargins(12,15,12,5)
        self.byp=QPushButton("ACTIVE"); self.byp.setCheckable(True)
        self.byp.setChecked(True); self.byp.setFixedWidth(55)
        self.byp.toggled.connect(self._toggle)
        self._knob(l,"DRIVE",self._drive,0,100,50)
        self._knob(l,"WARMTH",self._warmth,0,100,30)
        self._knob(l,"COMP",self._comp,0,100,20)
        l.addStretch()
        safe_b=QPushButton("🛡 Safe")
        safe_b.setCheckable(True)
        safe_b.setToolTip("Ogranicza pokrętła do bezpiecznych wartości\nDRIVE≤40  WARMTH≤50  COMP≤30")
        safe_b.toggled.connect(self._safe_toggle)
        safe_b.setStyleSheet("QPushButton{background:#1A1A00;color:#888;border:1px solid #444;padding:2px 6px}"
                             "QPushButton:checked{background:#444400;color:#FFFF00;border:1px solid #FF0}")
        self._safe_btn=safe_b
        l.addWidget(safe_b); l.addWidget(self.byp)

    def set_pipeline(self,sat,gain,tone,mon_sat=None,mon_gain=None,mon_tone=None):
        self._main={"sat":sat,"gain":gain,"tone":tone}
        self._mon={"sat":mon_sat,"gain":mon_gain,"tone":mon_tone}
        if self.byp.isChecked():
            for d,f in self._dials: f(d.value())

    def _knob(self,lo,name,func,mn,mx,df):
        v=QVBoxLayout(); d=QDial()
        d.setRange(mn,mx); d.setValue(df); d.setNotchesVisible(True); d.setFixedSize(48,48)
        d.valueChanged.connect(func); lb=QLabel(name); lb.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(d); v.addWidget(lb); lo.addLayout(v); self._dials.append((d,func))

    def _s(self,key,prop,val):
        for d in [self._main,self._mon]:
            el=d.get(key)
            if el:
                try: el.set_property(prop, float(val) if isinstance(val,float) else val)
                except: pass

    def _toggle(self,state):
        if not state:
            self._s("sat","ratio",1.0); self._s("sat","threshold",1.0)
            self._s("gain","volume",1.0); self._s("tone","band0",0.0); self._s("tone","band2",0.0)
            self.byp.setText("BYPASS")
        else:
            self.byp.setText("ACTIVE")
            for d,f in self._dials: f(d.value())

    def _safe_toggle(self, checked):
        self._safe_mode = checked
        self._safe_btn.setText("🛡 Safe ON" if checked else "🛡 Safe")
        names = ["DRIVE","WARMTH","COMP"]
        for (d, f), name in zip(self._dials, names):
            if checked:
                lim = self._safe_limits[name]
                if d.value() > lim:
                    d.setValue(lim)

    def _clamp_safe(self, name, v):
        if self._safe_mode:
            lim = self._safe_limits.get(name, 100)
            if v > lim:
                names = ["DRIVE","WARMTH","COMP"]
                idx = names.index(name)
                self._dials[idx][0].setValue(lim)
                return lim
        return v

    def _drive(self,v):
        if not self.byp.isChecked(): return
        v = self._clamp_safe("DRIVE", v)
        self._s("sat","threshold",0.9-(v/100*0.8)); self._s("gain","volume",1+(v/100*0.8))
    def _warmth(self,v):
        if not self.byp.isChecked(): return
        v = self._clamp_safe("WARMTH", v)
        self._s("tone","band0",v/100*4); self._s("tone","band2",-(v/100*3))
    def _comp(self,v):
        if not self.byp.isChecked(): return
        v = self._clamp_safe("COMP", v)
        self._s("sat","ratio",1+(v/100*9))

# ============================================================================
# SPATIAL FX WIDGET  — niezależny od Tape ATS, własne elementy GStreamer
# ============================================================================
class SpatialFXWidget(QGroupBox):
    """
    Spatial FX całkowicie niezależny od Tape ATS.
    Elementy GStreamer przypisywane przez set_pipeline() z pipelinu głównego.
    Bezpieczne zakresy:
      Stereo Width : 50..150  (1.0 = neutral)  -> slider 0..200, safe 50..150
      Haas Delay   : 0..20 ms                  -> slider 0..20,  safe 0..15
      Sat Ratio    : 1.0..3.0 :1               -> slider 10..50, safe 10..30
    """
    # (min, max, default, safe_min, safe_max)
    # Plugin GStreamer 'stereo': property 'stereo' ma zakres 0.0..1.0
    # 0.0 = mono (brak efektu stereo), 1.0 = pełny efekt stereo widening
    # Suwak 0-100 → stereo 0.0-1.0
    RANGES = {
        "width":  (0,   100,  5,   0,   20),   # /100 -> stereo prop; default 5% (delikatne)
        "haas":   (0,   20,   0,   0,   8),    # ms; default 0
        "sat":    (10,  80,   10,  10,  20),   # /10 -> ratio; default 1.0:1 (off)
    }

    def __init__(self, parent=None):
        super().__init__("Spatial FX  (niezależny)", parent)
        self.setStyleSheet(
            "QGroupBox{color:#00FFCC;border:1px solid #1A4433;"
            "margin-top:10px;font-weight:bold;background:#080F0C}"
            "QLabel{color:#558866;font-size:9px}"
            "QSlider::groove:horizontal{height:3px;background:#182818}"
            "QSlider::handle:horizontal{background:#00FFCC;width:9px;height:9px;margin:-3px 0;border-radius:4px}"
            "QCheckBox{color:#00FFCC;font-weight:bold}"
            "QCheckBox::indicator{width:12px;height:12px;border:1px solid #00CCAA;"
            "border-radius:2px;background:#080F0C}"
            "QCheckBox::indicator:checked{background:#00CCAA}"
            "QPushButton{background:#0E1E18;color:#00FFCC;border:1px solid #1A4433;"
            "padding:2px 8px;border-radius:3px;font-size:10px}"
            "QPushButton:hover{background:#1A3A28;border-color:#00FFCC}"
            "QComboBox{background:#0E1E18;color:#EEE;border:1px solid #00AAAA;"
            "border-radius:3px;padding:3px;font-size:10px}")
        # GStreamer elements (main + monitor)
        self._sw=None;  self._echo=None;  self._sat=None
        self._msw=None; self._mecho=None; self._msat=None
        self._safe_mode = False
        self._build()

    # ── build UI ────────────────────────────────────────────────────────────
    def _build(self):
        m = QVBoxLayout(self)
        m.setContentsMargins(8, 14, 8, 6); m.setSpacing(5)

        # Top row: enable + safe + preset
        top = QHBoxLayout()
        self.en = QCheckBox("ENABLE")
        self.en.setChecked(False)
        self.en.toggled.connect(self._on_en)
        top.addWidget(self.en)

        self.safe_btn = QPushButton("🛡 Safe Params")
        self.safe_btn.setCheckable(True)
        self.safe_btn.setToolTip(
            "Zawęża zakresy suwaków do bezpiecznych wartości\n"
            "Stereo: 50–150%  |  Haas: 0–15ms  |  Sat: 1.0–3.0:1")
        self.safe_btn.toggled.connect(self._apply_safe)
        top.addWidget(self.safe_btn)
        top.addStretch()
        top.addWidget(QLabel("Preset:"))
        self.pc = QComboBox()
        self.pc.addItems(["Flat", "Studio", "Wide"])
        self.pc.currentTextChanged.connect(self._preset)
        top.addWidget(self.pc)
        m.addLayout(top)

        # Sliders
        def row(label, attr_sl, attr_lbl, key):
            mn,mx,dv,_,_ = self.RANGES[key]
            r = QHBoxLayout()
            lbl = QLabel(label); lbl.setFixedWidth(88)
            r.addWidget(lbl)
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(mn, mx); s.setValue(dv); s.setFixedHeight(16)
            vl = QLabel(); vl.setFixedWidth(52)
            vl.setAlignment(Qt.AlignmentFlag.AlignRight)
            setattr(self, attr_sl, s); setattr(self, attr_lbl, vl)
            r.addWidget(s); r.addWidget(vl)
            m.addLayout(r)

        row("Stereo Width:", "wsl", "wlb", "width")
        row("Haas Delay:",   "hsl", "hlb", "haas")
        row("Sat Ratio:",    "ssl", "slb", "sat")

        self.wsl.valueChanged.connect(self._ow)
        self.hsl.valueChanged.connect(self._oh)
        self.ssl.valueChanged.connect(self._os)
        self._ow(self.RANGES["width"][2])
        self._oh(self.RANGES["haas"][2])
        self._os(self.RANGES["sat"][2])

    # ── GStreamer set_pipeline ───────────────────────────────────────────────
    def set_pipeline(self, sw, echo, sat, msw=None, mecho=None, msat=None):
        """Przypisuje WYŁĄCZNIE elementy Spatial — nie dotyka Tape."""
        self._sw=sw; self._echo=echo; self._sat=sat
        self._msw=msw; self._mecho=mecho; self._msat=msat
        # Apply current state immediately
        if self.en.isChecked():
            self._ow(self.wsl.value())
            self._oh(self.hsl.value())
            self._os(self.ssl.value())
        else:
            self._bypass_all()

    def _s(self, el, prop, val):
        if el:
            try: el.set_property(prop, float(val))
            except Exception as e: print(f"  Spatial.set {prop}={val}: {e}")

    def _bypass_all(self):
        for sw in [self._sw, self._msw]:   self._s(sw,   "stereo",    1.0)
        for ec in [self._echo, self._mecho]:
            self._s(ec, "intensity", 0.0); self._s(ec, "delay", 1)
        for sa in [self._sat, self._msat]:
            self._s(sa, "ratio", 1.0); self._s(sa, "threshold", 1.0)

    # ── Enable toggle ────────────────────────────────────────────────────────
    def _on_en(self, e):
        if not e:
            self._bypass_all()
        else:
            self._ow(self.wsl.value())
            self._oh(self.hsl.value())
            self._os(self.ssl.value())

    # ── Safe Params ──────────────────────────────────────────────────────────
    def _apply_safe(self, checked):
        self._safe_mode = checked
        self.safe_btn.setText("🛡 Safe  ON" if checked else "🛡 Safe Params")
        for key, sl in [("width", self.wsl), ("haas", self.hsl), ("sat", self.ssl)]:
            mn,mx,dv,smn,smx = self.RANGES[key]
            # Block signals while changing range to avoid glitchy rapid changes
            sl.blockSignals(True)
            cur = sl.value()
            if checked:
                sl.setRange(smn, smx)
                # Clamp current value to safe range
                sl.setValue(max(smn, min(smx, cur)))
            else:
                sl.setRange(mn, mx)
                sl.setValue(cur)
            sl.blockSignals(False)
        # Apply clamped values
        self._ow(self.wsl.value())
        self._oh(self.hsl.value())
        self._os(self.ssl.value())

    # ── Slider handlers ──────────────────────────────────────────────────────
    def _ow(self, v):
        stereo = v / 100.0   # 0.0..1.0  (plugin stereo: 0=mono, 1=full widening)
        self.wlb.setText(f"{v}%")
        if self.en.isChecked():
            for el in [self._sw, self._msw]: self._s(el, "stereo", stereo)

    def _oh(self, v):
        self.hlb.setText(f"{v} ms")
        if self.en.isChecked():
            ns = max(1, v * 1_000_000)
            intensity = 0.0 if v == 0 else 0.35   # zmniejszona intensywność → mniej trzeszczenia
            for el in [self._echo, self._mecho]:
                self._s(el, "delay", ns)
                self._s(el, "intensity", intensity)

    def _os(self, v):
        ratio = v / 10.0   # 1.0..8.0
        self.slb.setText(f"{ratio:.1f}:1")
        if self.en.isChecked():
            threshold = 0.85 if ratio > 1.5 else 1.0   # bezpieczny próg
            for el in [self._sat, self._msat]:
                self._s(el, "ratio", ratio)
                self._s(el, "threshold", threshold)

    # ── Presets ──────────────────────────────────────────────────────────────
    def _preset(self, n):
        # (width 0-100, haas_ms 0-20, sat*10)
        # stereo plugin: 100=pełny efekt, 80=subtelny, 0=mono
        p = {"Flat": (100, 0, 10), "Studio": (85, 8, 15), "Wide": (70, 12, 20)}
        if n in p:
            w, h, s = p[n]
            if self._safe_mode:
                _,_,_,smn_w,smx_w = self.RANGES["width"]
                _,_,_,smn_h,smx_h = self.RANGES["haas"]
                _,_,_,smn_s,smx_s = self.RANGES["sat"]
                w = max(smn_w, min(smx_w, w))
                h = max(smn_h, min(smx_h, h))
                s = max(smn_s, min(smx_s, s))
            self.wsl.setValue(w); self.hsl.setValue(h); self.ssl.setValue(s)

# ============================================================================
# PHASER WIDGET
# ============================================================================
class PhaserWidget(QGroupBox):
    def __init__(self,viz,eq,parent=None):
        super().__init__("Phase Geometry",parent)
        self.setStyleSheet("QGroupBox{color:#8888FF;border:1px solid #333;"
            "margin-top:10px;font-weight:bold;background:#0E0E14}"
            "QPushButton{background:#1A1A2A;color:#888;border:1px solid #333;"
            "padding:3px;border-radius:3px;font-size:10px;min-width:48px}"
            "QPushButton:checked{background:#3333AA;color:#AAF;border-color:#55F}"
            "QLabel{color:#555;font-size:10px}")
        self.viz=viz; self.eq=eq
        l=QHBoxLayout(self); l.setContentsMargins(10,14,10,5); l.setSpacing(6)
        bg=QButtonGroup(self); bg.setExclusive(True)
        for mode in ["linear","diverge","converge","rise","fall","chaos"]:
            b=QPushButton(mode); b.setCheckable(True)
            if mode=="linear": b.setChecked(True)
            b.clicked.connect(lambda _,m=mode:self.set_m(m)); bg.addButton(b); l.addWidget(b)
        l.addWidget(QLabel("Spd:"))
        sl=QSlider(Qt.Orientation.Horizontal); sl.setRange(0,100); sl.setValue(30); sl.setFixedWidth(70)
        sl.valueChanged.connect(lambda v:(setattr(self.viz,'phase_speed',v/1000),setattr(self.eq.proc,'ps',v/1000))); l.addWidget(sl)
    def set_m(self,m): self.viz.phaser_mode=m; self.eq.proc.pm=m

# ============================================================================
# CHAIN MODULE WIDGET
# ============================================================================
class ChainModuleWidget(QFrame):
    def __init__(self,mid,label,accent,params,parent=None):
        super().__init__(parent)
        self.mid=mid; self.accent=accent; self._pd=params
        self.param_sliders={}; self.param_labels={}; self.gst_els=[]
        self.setStyleSheet(f"""
            QFrame{{background:#0E0E12;border:1px solid #252525;
                   border-left:3px solid {accent};border-radius:3px;margin:1px}}
            QLabel{{color:#777;font-size:9px}}
            QSlider::groove:horizontal{{height:3px;background:#1A1A1A;border-radius:1px}}
            QSlider::handle:horizontal{{background:{accent};width:8px;height:8px;margin:-2px 0;border-radius:4px}}
            QCheckBox{{color:{accent};font-size:10px;font-weight:bold;spacing:4px}}
            QCheckBox::indicator{{width:11px;height:11px;border:1px solid {accent};border-radius:2px;background:#0E0E12}}
            QCheckBox::indicator:checked{{background:{accent}}}
        """)
        mv=QVBoxLayout(self); mv.setContentsMargins(5,3,5,3); mv.setSpacing(2)
        hdr=QHBoxLayout()
        self.en=QCheckBox(label); self.en.setChecked(False); self.en.toggled.connect(self._toggle)
        hdr.addWidget(self.en); hdr.addStretch()
        if mid=="phase_inv":
            self.invL=QCheckBox("L"); self.invR=QCheckBox("R")
            for cb in [self.invL,self.invR]:
                cb.setStyleSheet(f"color:{accent};font-size:9px"); cb.toggled.connect(self._phase); hdr.addWidget(cb)
        mv.addLayout(hdr)
        self.pw=QWidget(); pv=QVBoxLayout(self.pw); pv.setContentsMargins(0,0,0,0); pv.setSpacing(2)
        for pn,(pmn,pmx,pdf,psc,pu) in params.items():
            if mid=="phase_inv": continue
            row=QHBoxLayout(); lb=QLabel(pn.replace("-"," ")); lb.setFixedWidth(78); row.addWidget(lb)
            sl=QSlider(Qt.Orientation.Horizontal); sl.setRange(int(pmn*psc),int(pmx*psc))
            sl.setValue(int(pdf*psc)); sl.setFixedHeight(15)
            vl=QLabel(f"{pdf:.2f}{pu}"); vl.setFixedWidth(46); vl.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.param_sliders[pn]=sl; self.param_labels[pn]=vl
            sl.valueChanged.connect(lambda v,n=pn,s=psc,u=pu,l=vl:self._param(n,v/s,u,l))
            row.addWidget(sl); row.addWidget(vl); pv.addLayout(row)
        self.pw.setVisible(False); mv.addWidget(self.pw)

    def add_gst(self,*els):
        for el in els:
            if el and el not in self.gst_els: self.gst_els.append(el)

    def _toggle(self,enabled):
        self.pw.setVisible(enabled)
        if not enabled: self._bypass()
        else:
            if self.mid=="phase_inv": self._phase()
            else:
                for pn,sl in self.param_sliders.items():
                    self._param(pn,sl.value()/self._pd[pn][3],self._pd[pn][4],self.param_labels[pn])

    def _param(self,pn,val,unit,lbl):
        if unit=="Hz":   lbl.setText(f"{val:.0f}Hz")
        elif unit=="ns": lbl.setText(f"{val/1e6:.0f}ms")
        elif unit==":1": lbl.setText(f"{val:.1f}:1")
        else:            lbl.setText(f"{val:.2f}{unit}")
        if not self.en.isChecked(): return
        _,_,pmap=CHAIN_GST.get(self.mid,("",{},""))
        if isinstance(pmap,dict):
            for gp,(_,uiname) in pmap.items():
                if uiname==pn:
                    for el in self.gst_els:
                        try: el.set_property(gp, float(val))
                        except: pass

    def _bypass(self):
        _,neutral,_=CHAIN_GST.get(self.mid,("",{},""))
        for el in self.gst_els:
            for k,v in neutral.items():
                try: el.set_property(k, float(v) if isinstance(v,float) else v)
                except: pass

    def _phase(self):
        if not self.en.isChecked(): return
        d=1.0 if(getattr(self,'invL',None)and(self.invL.isChecked()or self.invR.isChecked())) else 0.0
        for el in self.gst_els:
            try: el.set_property("degree", float(d))
            except: pass

    def get_state(self):
        s={"enabled":self.en.isChecked(),"params":{}}
        if self.mid=="phase_inv":
            s["invL"]=getattr(self,'invL',None)and self.invL.isChecked()
            s["invR"]=getattr(self,'invR',None)and self.invR.isChecked()
        for pn,sl in self.param_sliders.items():
            s["params"][pn]=sl.value()/self._pd[pn][3]
        return s

    def set_state(self,s):
        for pn,val in s.get("params",{}).items():
            if pn in self.param_sliders:
                sc=self._pd[pn][3]
                self.param_sliders[pn].blockSignals(True)
                self.param_sliders[pn].setValue(int(val*sc))
                self.param_sliders[pn].blockSignals(False)
                self.param_labels[pn].setText(f"{val:.2f}{self._pd[pn][4]}")
        if self.mid=="phase_inv":
            if hasattr(self,'invL'): self.invL.setChecked(s.get("invL",False))
            if hasattr(self,'invR'): self.invR.setChecked(s.get("invR",False))
        self.en.setChecked(s.get("enabled",False))

# ============================================================================
# SIGNAL CHAIN PANEL
# ============================================================================
class SignalChainPanel(QGroupBox):
    def __init__(self,parent=None):
        super().__init__("Signal Chain — DSP Modelling",parent)
        self.setStyleSheet("QGroupBox{color:#00FFCC;border:1px solid #1A3A2A;"
            "margin-top:10px;font-weight:bold;background:#090C0A}"
            "QPushButton{background:#0E1A14;color:#00FFCC;border:1px solid #1A4A3A;"
            "padding:3px 8px;border-radius:3px;font-size:10px}"
            "QPushButton:hover{background:#1A3A2A;border-color:#00FFCC}"
            "QPushButton:pressed{background:#00FFCC;color:#000}"
            "QComboBox{background:#0E1A14;color:#00FFCC;border:1px solid #1A4A3A;"
            "border-radius:3px;padding:3px;font-size:10px}"
            "QLineEdit{background:#0E1A14;color:#EEE;border:1px solid #1A4A3A;"
            "border-radius:3px;padding:3px;font-size:10px}"
            "QScrollBar:vertical{background:#0A0A0A;width:7px}"
            "QScrollBar::handle:vertical{background:#1A4A3A;border-radius:3px}")
        self.mws={}
        self._resolver = None   # DSPAutoResolver — przypisywany przez set_resolver()
        self._rebuild_pending = False
        self._rebuild_timer = QTimer()
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.timeout.connect(self._do_rebuild)
        self._build(); self._refresh()

    def set_resolver(self, resolver):
        """Przypisuje DSPAutoResolver — wywoływane z CarbonPhaserPlayer po init pipeline."""
        self._resolver = resolver

    def add_resolver(self, resolver):
        """Dodaje dodatkowy resolver (np. dla pipeline monitora)."""
        if not hasattr(self, '_extra_resolvers'):
            self._extra_resolvers = []
        self._extra_resolvers.append(resolver)

    def _schedule_rebuild(self):
        """Debounce rebuild — czeka 80ms po ostatniej zmianie checkboxa."""
        self._rebuild_timer.start(80)

    def _do_rebuild(self):
        """Wywołuje AutoResolver z aktualną listą aktywnych modułów."""
        if not self._resolver:
            return
        enabled = [mid for mid, w in self.mws.items() if w.en.isChecked()]
        new_order = self._resolver.rebuild(enabled)
        for extra in getattr(self, '_extra_resolvers', []):
            try:
                extra.rebuild(enabled)
            except Exception as e:
                print(f"[AutoResolver extra] Error: {e}")
        self._update_chain_label(new_order)

    def _update_chain_label(self, order):
        if hasattr(self, '_chain_lbl'):
            if not order:
                self._chain_lbl.setText("— brak aktywnych modułów —")
            else:
                labels = [CHAIN_DEFS.get(m,(m,))[0] for m in order]
                txt = " → ".join(labels)
                self._chain_lbl.setText(txt)
                self._chain_lbl.setToolTip(
                    "Kolejność wyznaczona przez AutoResolver DSP\n" +
                    "\n".join(f"  {i+1}. {m}  (gr{DSP_META.get(m,{}).get('group','?')})"
                              for i,m in enumerate(order)))

    def _resync_module_gst_refs(self, new_order):
        """
        Po rebuild, gst_els w każdym ChainModuleWidget dalej wskazują na te same
        obiekty Gst.Element — nie trzeba ich zmieniać, bo AutoResolver nie tworzy nowych
        elementów, tylko zmienia ich kolejność połączeń.
        """
        pass  # gst_els pozostają niezmienione — tylko linkowanie pipeline się zmieniło

    def _build(self):
        outer=QVBoxLayout(self); outer.setContentsMargins(5,14,5,5); outer.setSpacing(4)
        pb=QHBoxLayout(); pb.setSpacing(4); pb.addWidget(QLabel("Preset:"))
        self.pcb=QComboBox(); self.pcb.setFixedWidth(130); pb.addWidget(self.pcb)
        lb=QPushButton("Load"); lb.clicked.connect(self._load); pb.addWidget(lb)
        self.ne=QLineEdit(); self.ne.setPlaceholderText("Name..."); self.ne.setFixedWidth(110); pb.addWidget(self.ne)
        sb=QPushButton("Save"); sb.clicked.connect(self._save); pb.addWidget(sb)
        db=QPushButton("Del"); db.setFixedWidth(32); db.clicked.connect(self._del); pb.addWidget(db)
        pb.addStretch()
        rb=QPushButton("Reset All"); rb.clicked.connect(self._reset); pb.addWidget(rb)
        outer.addLayout(pb)

        # AutoResolver status bar
        ar_row = QHBoxLayout(); ar_row.setSpacing(4)
        ar_icon = QLabel("⚙ AutoResolver DSP:")
        ar_icon.setStyleSheet("color:#00AA88;font-size:9px;font-weight:bold")
        ar_row.addWidget(ar_icon)
        self._chain_lbl = QLabel("— brak aktywnych modułów —")
        self._chain_lbl.setStyleSheet(
            "color:#448866;font-size:9px;font-style:italic;"
            "background:#050E08;border:1px solid #0A2A18;"
            "border-radius:2px;padding:1px 4px")
        self._chain_lbl.setWordWrap(False)
        ar_row.addWidget(self._chain_lbl, 1)
        outer.addLayout(ar_row)

        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFixedHeight(260)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cont=QWidget(); cv=QVBoxLayout(cont); cv.setContentsMargins(2,2,2,2); cv.setSpacing(2)
        for mid in CHAIN_ORDER:
            lb2,acc,params=CHAIN_DEFS[mid]; w=ChainModuleWidget(mid,lb2,acc,params)
            # Podpinamy callback do AutoResolver przy każdej zmianie checkboxa
            w.en.toggled.connect(self._schedule_rebuild)
            self.mws[mid]=w; cv.addWidget(w)
        cv.addStretch(); scroll.setWidget(cont); outer.addWidget(scroll)

    def attach(self,main_els,mon_els=None):
        for mid in CHAIN_ORDER:
            w=self.mws.get(mid)
            if not w: continue
            w.gst_els=[]
            w.en.blockSignals(True)   # blokuj _schedule_rebuild podczas attach
            me=main_els.get(mid)
            if me: w.add_gst(me)
            if mon_els:
                mone=mon_els.get(mid)
                if mone: w.add_gst(mone)
            w.en.blockSignals(False)

    def _read(self):
        try:
            if os.path.exists(CHAIN_FILE):
                with open(CHAIN_FILE,"r",encoding="utf-8") as f: return json.load(f)
        except: pass
        return {}

    def _write(self,d):
        try:
            with open(CHAIN_FILE,"w",encoding="utf-8") as f: json.dump(d,f,indent=2,ensure_ascii=False)
        except Exception as e: print(f"Chain save: {e}")

    def _refresh(self):
        self.pcb.clear()
        for n in self._read(): self.pcb.addItem(n)

    def _load(self):
        n=self.pcb.currentText()
        if not n: return
        d=self._read()
        if n in d:
            for mid,s in d[n].items():
                if mid in self.mws: self.mws[mid].set_state(s)

    def _save(self):
        n=self.ne.text().strip() or f"Preset {self.pcb.count()+1}"
        d=self._read(); d[n]={mid:w.get_state() for mid,w in self.mws.items()}
        self._write(d); self._refresh()
        idx=self.pcb.findText(n)
        if idx>=0: self.pcb.setCurrentIndex(idx)
        self.ne.clear()

    def _del(self):
        n=self.pcb.currentText()
        if not n: return
        d=self._read()
        if n in d: del d[n]; self._write(d); self._refresh()

    def _reset(self):
        for w in self.mws.values(): w.en.setChecked(False)

# ============================================================================
# MAIN WINDOW
# ============================================================================
class CarbonPhaserPlayer(QMainWindow):
    BASE_W=1280; BASE_H=800

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CarbonX Player  v3.0")
        self.scale=1.0
        self.pl=[]; self.idx=-1; self.play=False
        self._mon_pipe=None
        self._mon_resolver=None

        # Calculate 80% of screen at 16:10
        scr=QApplication.primaryScreen().availableGeometry()
        w=int(scr.width()*0.80); h=int(w*10/16)
        self.resize(w,h)

        self._gst_init()
        self._build_ui()
        self._connect_widgets()
        self._auto_load_m3u()

        self.tm=QTimer(); self.tm.timeout.connect(self._poll); self.tm.start(50)

    def closeEvent(self,event):
        self._stop_monitor_pipe()
        if self.ply: self.ply.set_state(Gst.State.NULL)
        cleanup_virtual_sink()
        super().closeEvent(event)

    # ── GST PIPELINE ────────────────────────────────────────────────────
    def _gst_init(self):
        """
        uridecodebin -> audioconvert -> audioresample -> tee
            tee -> queue -> [Tape -> EQ -> Spatial -> Chain modules] -> audioconvert -> autoaudiosink
            tee -> queue -> spectrum -> fakesink
        """
        self.ply=Gst.Pipeline.new("carbon")
        self.src=mkgst("uridecodebin","src")
        if self.src: self.src.connect("pad-added",self._on_pad)
        self.conv_in=mkgst("audioconvert","conv_in")
        self.res_in =mkgst("audioresample","res_in")
        self.tee    =mkgst("tee","tee")

        # FX queue
        self.q_fx=mkgst("queue","q_fx",{"max-size-buffers":0,"max-size-time":0,"max-size-bytes":0})

        # Tape sim
        self.tape_sat =mkgst("audiodynamic","tape_sat",
                              {"characteristics":"soft-knee","mode":"compressor",
                               "threshold":1.0,"ratio":1.0})
        self.tape_gain=mkgst("volume","tape_gain",{"volume":1.0})
        self.tape_tone=mkgst("equalizer-3bands","tape_tone")

        # EQ
        self.eq=mkgst("equalizer-10bands","eq10")

        # Spatial
        # UWAGA: plugin 'stereo' wymaga audioconvert przed i po sobie (inne caps)
        self.sp_sat    = mkgst("audiodynamic","sp_sat",
                               {"characteristics":"hard-knee","mode":"compressor",
                                "threshold":0.0,"ratio":1.0})
        self.sp_conv1  = mkgst("audioconvert","sp_conv1")   # przed stereo
        # Plugin stereo negocjuje format przez sp_conv1 — nie potrzebuje capsfilter
        self.sp_stereo = mkgst("stereo","sp_stereo",{"stereo":1.0})
        self.sp_conv2  = mkgst("audioconvert","sp_conv2")   # po stereo
        self.sp_echo   = mkgst("audioecho","sp_echo",{"delay":1,"intensity":0.0,"feedback":0.0})

        # Signal chain modules — wszystkie tworzone z wartościami neutralnymi
        # AutoResolver zadecyduje o kolejności i konwerterach
        self.chain_els={}
        for mid in CHAIN_ORDER:
            plugin,neutral,_=CHAIN_GST[mid]
            self.chain_els[mid]=mkgst(plugin,f"ch_{mid}",neutral)

        # Output
        self.conv_out=mkgst("audioconvert","conv_out")
        self.hw_sink =mkgst("autoaudiosink","hw_sink",{"sync":True})

        # Spectrum branch
        self.q_sp  =mkgst("queue","q_sp",{"max-size-buffers":0,"max-size-time":0,"max-size-bytes":0})
        self.sp    =mkgst("spectrum","spectrum",
                           {"bands":64,"threshold":-80,"post-messages":True,"message-magnitude":True})
        self.sp_snk=mkgst("fakesink","sp_snk",{"sync":False,"silent":True})

        # Add stałe elementy do pipeline (chain_els dodaje AutoResolver)
        for el in ([self.src,self.conv_in,self.res_in,self.tee,
                    self.q_fx,self.tape_sat,self.tape_gain,self.tape_tone,
                    self.eq,self.sp_sat,self.sp_conv1,self.sp_stereo,self.sp_conv2,self.sp_echo]
                   +list(self.chain_els.values())
                   +[self.conv_out,self.hw_sink,self.q_sp,self.sp,self.sp_snk]):
            if el: self.ply.add(el)

        # Static links (przed chain)
        def lnk(a,b):
            if a and b:
                if not a.link(b): print(f"  [!] link: {a.get_name()} -> {b.get_name()}")
        lnk(self.conv_in,self.res_in); lnk(self.res_in,self.tee)
        lnk(self.tee,self.q_fx)
        prev=self.q_fx
        for el in [self.tape_sat,self.tape_gain,self.tape_tone,
                   self.eq,self.sp_sat,self.sp_conv1,self.sp_stereo,self.sp_conv2,self.sp_echo]:
            if el: lnk(prev,el); prev=el

        # AutoResolver DSP — dynamiczny łańcuch chain
        self.dsp_resolver = DSPAutoResolver(
            pipeline    = self.ply,
            entry_el    = self.sp_echo,
            exit_el     = self.conv_out,
            name_prefix = "main",
        )
        self.dsp_resolver.set_chain_elements(self.chain_els)
        self.dsp_resolver.init_convs()  # tworzy sloty konwerterów w pipeline

        # Domyślne połączenie: sp_echo → conv_out (brak aktywnych modułów chain)
        lnk(self.sp_echo, self.conv_out)

        # MultibandLimiter instances — jeden per punkt wstrzyknięcia
        # POST_FX: między conv_out a hw_sink (master output)
        # INPUT:   między conv_in a res_in (wejście, przed wszystkim)
        # POST_EQ: między eq a sp_sat (po EQ, przed Spatial)
        self._mbl_post_fx = MultibandLimiter(self.ply, "mbl_out",  MBLIMIT_BANDS)
        self._mbl_input   = MultibandLimiter(self.ply, "mbl_in",   MBLIMIT_BANDS)
        self._mbl_post_eq = MultibandLimiter(self.ply, "mbl_eq",   MBLIMIT_BANDS)

        # LimiterRouter — zarządza wszystkimi punktami
        self.limiter_router = LimiterRouter()
        self.limiter_router.register("INPUT",   self._mbl_input,   self.conv_in,  self.res_in)
        self.limiter_router.register("POST_EQ", self._mbl_post_eq, self.eq,       self.sp_sat)
        self.limiter_router.register("POST_FX", self._mbl_post_fx, self.conv_out, self.hw_sink)

        # Podepnij limiter_router do resolvera — eject/re-inject wokół rebuild
        self.dsp_resolver.limiter_router = self.limiter_router

        # Połącz bezpośrednio (MBL domyślnie wyłączone)
        lnk(self.conv_out, self.hw_sink)

        # Spectrum branch
        lnk(self.tee,self.q_sp); lnk(self.q_sp,self.sp); lnk(self.sp,self.sp_snk)

        bus=self.ply.get_bus(); bus.add_signal_watch()
        bus.connect("message",self._on_bus)
        print("Main pipeline built (DSPAutoResolver + MultibandLimiter)")

    def _on_pad(self,src,pad):
        caps=pad.get_current_caps()
        if caps:
            s=caps.get_structure(0)
            if s and not s.get_name().startswith("audio"): return
        if not self.conv_in: return
        sink=self.conv_in.get_static_pad("sink")
        if sink and not sink.is_linked():
            ret=pad.link(sink)
            print(f"Pad link: {ret.value_name}")

    def _on_bus(self,bus,msg):
        t=msg.type
        if t==Gst.MessageType.EOS:
            GLib.idle_add(self._next)
        elif t==Gst.MessageType.ERROR:
            err,dbg=msg.parse_error()
            print(f"GST ERR: {err.message} | {dbg}")
            # HLS/adaptive streams czasem dają not-negotiated przy zmianie bitrate
            # Próbuj wznowić zamiast całkowicie zatrzymywać
            err_str = str(err.message).lower() if err else ""
            dbg_str = str(dbg).lower() if dbg else ""
            is_hls_transient = ("not-negotiated" in dbg_str or
                                "not-linked" in dbg_str or
                                "adaptivedemux" in dbg_str or
                                "hlsdemux" in dbg_str)
            if is_hls_transient and getattr(self, "play", False):
                print(f"  → HLS transient error — retrying in 1s")
                def _retry():
                    if getattr(self, "play", False):
                        self.ply.set_state(Gst.State.NULL)
                        self.ply.set_state(Gst.State.PLAYING)
                GLib.timeout_add(1000, lambda: (_retry(), False)[1])
            else:
                GLib.idle_add(lambda:(self.ply.set_state(Gst.State.NULL),
                                      setattr(self,'play',False),
                                      self.bp.setText("Play")))
        elif t==Gst.MessageType.ELEMENT:
            s=msg.get_structure()
            if not s: return
            if s.get_name()=="spectrum":
                self._spectrum(s)
            elif s.get_name()=="level":
                src_name = msg.src.get_name() if msg.src else ""
                if src_name and hasattr(self,"limiter_router") and self.limiter_router:
                    for pid in self.limiter_router.registered_points():
                        mbl = self.limiter_router.get(pid)
                        if mbl and mbl._injected:
                            for node in mbl.nodes:
                                if node._level and node._level.get_name()==src_name:
                                    node.handle_level_message(s); break
            elif s.get_name()=="level":
                # Routing przez msg.src — przekaż do właściwego node MBL
                src_el = msg.src
                src_name = src_el.get_name() if src_el else ""
                if src_name and hasattr(self, 'limiter_router'):
                    for pid in self.limiter_router.registered_points():
                        mbl = self.limiter_router.get(pid)
                        if mbl and mbl._injected:
                            for node in mbl.nodes:
                                lvl_name = node._level.get_name() if node._level else ""
                                if lvl_name and lvl_name == src_name:
                                    node.handle_level_message(s)
                                    break

    def _spectrum(self,s):
        rm=[]
        try: rm=s.get_value("magnitude")
        except TypeError:
            try:
                m=re.search(r'magnitude=\(float\)\{\s*([^}]+)\s*\}',s.to_string())
                if m: rm=[float(x.strip()) for x in m.group(1).split(',')]
            except: pass
        if rm:
            d=[max(0,min(1,(x+80)/80)) for x in rm]
            self.viz.update_data(d); self.eqw.proc.process(d)
            if hasattr(self,"limiter_router_widget"):
                overall_rms = sum(rm)/len(rm)
                for w in self.limiter_router_widget._detail_widgets.values():
                    try: w.update_overall_rms(overall_rms)
                    except: pass
            # Oblicz ogólny RMS z magnitude i przekaż do MBL AutoInsert
            if hasattr(self,'limiter_router_widget'):
                overall_rms = sum(rm) / len(rm)
                # Przekaż do wszystkich otwartych detail widget MBL
                for w in self.limiter_router_widget._detail_widgets.values():
                    try: w.update_overall_rms(overall_rms)
                    except: pass

    # ── UI BUILD ─────────────────────────────────────────────────────────
    def _build_ui(self):
        self.setStyleSheet("""
            QMainWindow{background:#0D0D10}
            QWidget{color:#DDD;font-family:'Segoe UI',sans-serif;font-size:11px}
            QListWidget{background:#101013;border:none}
            QListWidget::item{padding:5px 8px;border-bottom:1px solid #1A1A1E}
            QListWidget::item:selected{background:#1A4A6A;color:#FFF}
            QPushButton{background:#1A1A22;border:1px solid #2A2A35;
                        padding:4px 10px;border-radius:3px}
            QPushButton:hover{border-color:#00AAAA;color:#00FFFF}
            QPushButton:pressed{background:#003344}
            QComboBox{background:#1A1A22;color:#DDD;border:1px solid #2A2A35;
                      border-radius:3px;padding:3px}
            QScrollBar:vertical{background:#0A0A0D;width:7px}
            QScrollBar::handle:vertical{background:#2A2A35;border-radius:3px}
            QSplitter::handle{background:#1A1A1E;width:4px;height:4px}
            QTabWidget::pane{border:1px solid #2A2A35;background:#0E0E12;top:-1px}
            QTabBar::tab{background:#131318;color:#666;padding:5px 14px;
                         border:1px solid #222;border-bottom:none;border-radius:3px 3px 0 0;margin-right:2px}
            QTabBar::tab:selected{background:#1A1A22;color:#EEE;border-color:#00AAAA}
            QTabBar::tab:hover{color:#AAA}
        """)

        central=QWidget(); self.setCentralWidget(central)
        root=QVBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        self.scene_bar = SceneBar()
        root.addWidget(self.scene_bar)

        # Top bar
        topbar=QFrame(); topbar.setStyleSheet(
            "background:#08080C;border-bottom:1px solid #1A1A22")
        topbar.setFixedHeight(32)
        tb=QHBoxLayout(topbar); tb.setContentsMargins(10,2,10,2); tb.setSpacing(6)
        lbl=QLabel("⬡ CARBONX v3")
        lbl.setStyleSheet("color:#00AAFF;font-weight:bold;font-size:13px;letter-spacing:3px")
        tb.addWidget(lbl); tb.addStretch()
        self.scale_lbl=QLabel("100%")
        self.scale_lbl.setStyleSheet("color:#444;font-size:10px;min-width:36px")
        tb.addWidget(self.scale_lbl)
        for sym,delta in [("−",-.1),("○",0),("+",+.1)]:
            b=QPushButton(sym); b.setFixedSize(22,22)
            b.setStyleSheet("QPushButton{background:#131318;border:1px solid #2A2A35;border-radius:3px;font-weight:bold}"
                            "QPushButton:hover{border-color:#00AAAA;color:#00FFFF}")
            b.clicked.connect(lambda _,d=delta:self._scale(d)); tb.addWidget(b)
        root.addWidget(topbar)

        # Main horizontal splitter
        hsplit=QSplitter(Qt.Orientation.Horizontal)
        hsplit.setHandleWidth(4)

        # ── LEFT: Playlist ──────────────────────────────────────────────
        left=QWidget(); left.setMinimumWidth(240); left.setMaximumWidth(400)
        left.setStyleSheet("background:#0C0C0F")
        lv=QVBoxLayout(left); lv.setContentsMargins(0,0,0,0); lv.setSpacing(0)

        pl_top=QFrame(); pl_top.setFixedHeight(30)
        pl_top.setStyleSheet("background:#08080C;border-bottom:1px solid #1A1A22")
        pth=QHBoxLayout(pl_top); pth.setContentsMargins(10,0,10,0)
        pth.addWidget(QLabel("▶ PLAYLIST")); pth.addStretch()
        lv.addWidget(pl_top)

        self.ls=QListWidget()
        self.ls.itemDoubleClicked.connect(lambda it:self._pl_t(self.ls.row(it)))
        lv.addWidget(self.ls,1)

        # Buttons panel
        btm=QFrame(); btm.setStyleSheet("background:#08080C;border-top:1px solid #1A1A22")
        bv=QVBoxLayout(btm); bv.setContentsMargins(6,5,6,5); bv.setSpacing(4)

        r1=QHBoxLayout(); r1.setSpacing(4)
        for lbl2,fn in [("Add",self._add),("Radio",self._search_radio),
                        ("M3U",self._load_m3u),("Clear",self._clr)]:
            b=QPushButton(lbl2); b.clicked.connect(fn); r1.addWidget(b)
        bv.addLayout(r1)

        r2=QHBoxLayout(); r2.setSpacing(4)
        mon_b=QPushButton("Monitor"); mon_b.clicked.connect(self._start_monitor); r2.addWidget(mon_b)
        r2.addStretch(); bv.addLayout(r2)

        # Transport
        tr=QHBoxLayout(); tr.setSpacing(4)
        for txt,fn in [("⏮",self._prev),("▶",self._pp),("⏭",self._next)]:
            b=QPushButton(txt); b.clicked.connect(fn)
            if txt=="▶": self.bp=b
            tr.addWidget(b)
        tr.addStretch()
        self.vol_sl=QSlider(Qt.Orientation.Horizontal)
        self.vol_sl.setRange(0,100); self.vol_sl.setValue(80); self.vol_sl.setFixedWidth(80)
        self.vol_sl.valueChanged.connect(self._vol)
        tr.addWidget(QLabel("VOL")); tr.addWidget(self.vol_sl); bv.addLayout(tr)

        # Seek + time
        sk_row=QHBoxLayout(); sk_row.setSpacing(4)
        self.sk=QSlider(Qt.Orientation.Horizontal); self.sk.sliderReleased.connect(self._seek)
        self.lm=QLabel("0:00/0:00")
        self.lm.setStyleSheet("color:#00AAFF;font-family:Consolas;font-size:10px;min-width:72px")
        sk_row.addWidget(self.sk); sk_row.addWidget(self.lm); bv.addLayout(sk_row)

        self.lt=QLabel("Ready")
        self.lt.setStyleSheet("color:#FFF;font-weight:bold;padding:2px 0"); self.lt.setWordWrap(True)
        bv.addWidget(self.lt); lv.addWidget(btm)
        hsplit.addWidget(left)

        # ── RIGHT: Visualizer top + FX tabs bottom ──────────────────────
        right=QWidget()
        rv=QVBoxLayout(right); rv.setContentsMargins(0,0,0,0); rv.setSpacing(0)

        vsplit=QSplitter(Qt.Orientation.Vertical); vsplit.setHandleWidth(4)

        # Top: Visualizer
        vw=QWidget(); vw.setStyleSheet("background:#000")
        vl=QVBoxLayout(vw); vl.setContentsMargins(0,0,0,0); vl.setSpacing(0)
        v_top=QFrame(); v_top.setFixedHeight(28)
        v_top.setStyleSheet("background:#050508;border-bottom:1px solid #1A1A22")
        vth=QHBoxLayout(v_top); vth.setContentsMargins(8,2,8,2)
        vth.addWidget(QLabel("SPECTRUM")); vth.addStretch()
        self.viz=MatrixVisualizer()
        vc2=QComboBox(); vc2.addItems(list(self.viz.presets.keys()))
        vc2.currentTextChanged.connect(self.viz.set_preset)
        vth.addWidget(QLabel("Mode:")); vth.addWidget(vc2)
        vl.addWidget(v_top)
        self.dstack=QStackedWidget()
        visc=QWidget(); visl=QVBoxLayout(visc); visl.setContentsMargins(0,0,0,0); visl.addWidget(self.viz)
        self.video_widget=QVideoWidget(); self.video_widget.setStyleSheet("background:#000")
        self.video_player=QMediaPlayer(); self.video_player.setVideoOutput(self.video_widget)
        self.dstack.addWidget(visc); self.dstack.addWidget(self.video_widget)
        self.dstack.setCurrentIndex(0); vl.addWidget(self.dstack,1)
        vsplit.addWidget(vw)

        # Bottom: FX Tabs
        self.tabs=QTabWidget()

        # Tab 1: Tape + Spatial
        t1=QWidget(); t1v=QVBoxLayout(t1); t1v.setContentsMargins(4,4,4,4); t1v.setSpacing(4)
        self.tape_sim=AnalogTapeWidget(); self.tape_spatial=SpatialFXWidget()
        self.phantom_stereo=PhantomStereoWidget()
        t1v.addWidget(self.tape_sim); t1v.addWidget(self.tape_spatial)
        t1v.addWidget(self.phantom_stereo); t1v.addStretch()
        self.tabs.addTab(t1,"🎛 Tape & Spatial")

        # Tab 2: EQ + Phaser
        t2=QWidget(); t2v=QVBoxLayout(t2); t2v.setContentsMargins(4,4,4,4); t2v.setSpacing(4)
        self.eqw=EqualizerWidget(); self.phaser=PhaserWidget(self.viz,self.eqw)
        t2v.addWidget(self.eqw); t2v.addWidget(self.phaser); t2v.addStretch()
        self.tabs.addTab(t2,"🎚 EQ & Phase")

        # Tab 3: Signal Chain
        self.chain_panel=SignalChainPanel()
        self.tabs.addTab(self.chain_panel,"🔗 Signal Chain")

        # Tab 4: Multiband Limiter
        self.limiter_router_widget = LimiterRouterWidget()
        self.tabs.addTab(self.limiter_router_widget, "⚡ Limiters")

        vsplit.addWidget(self.tabs)
        vsplit.setSizes([320,450])
        rv.addWidget(vsplit)
        hsplit.addWidget(right)
        hsplit.setSizes([270,1000])
        root.addWidget(hsplit,1)

    def _connect_widgets(self):
        self.eqw.set_gst(self.eq)
        self.tape_sim.set_pipeline(self.tape_sat,self.tape_gain,self.tape_tone)
        self.tape_spatial.set_pipeline(self.sp_stereo,self.sp_echo,self.sp_sat)
        self.chain_panel.attach(self.chain_els)
        self.chain_panel.set_resolver(self.dsp_resolver)
        self.limiter_router_widget.set_router(self.limiter_router)
        # Phantom Stereo — wspólne elementy GST z SpatialFX
        self.phantom_stereo.set_pipeline(self.sp_stereo, self.sp_echo)
        # SceneManager + SceneBar
        self.scene_mgr = SceneManager(self)
        self.scene_bar.set_manager(self.scene_mgr)
        self._connect_change_notify()

    def _connect_change_notify(self):
        """Podpina notify_change do kluczowych widgetów."""
        notify = self.scene_bar.notify_change
        self.vol_sl.valueChanged.connect(lambda _: notify())
        if hasattr(self.eqw, "cb"):
            self.eqw.cb.currentIndexChanged.connect(lambda _: notify())
        if hasattr(self.eqw, "sl"):
            for sl in self.eqw.sl:
                sl.valueChanged.connect(lambda _: notify())
        for w in self.chain_panel.mws.values():
            w.en.clicked.connect(lambda _: notify())
            for sl in w.param_sliders.values():
                sl.valueChanged.connect(lambda _: notify())
        pw = self.phantom_stereo
        pw.en.clicked.connect(lambda _: notify())
        pw.preset_cb.currentTextChanged.connect(lambda _: notify())
        for sl in pw._sl.values():
            sl.valueChanged.connect(lambda _: notify())

    # ── SCALE UI ──────────────────────────────────────────────────────────
    def _scale(self,delta):
        if delta==0: self.scale=1.0
        else: self.scale=max(0.6,min(1.6,self.scale+delta))
        f=QApplication.instance().font()
        f.setPointSizeF(9*self.scale); QApplication.instance().setFont(f)
        w=int(self.BASE_W*self.scale*0.80); h=int(w*10/16)
        self.resize(w,h)
        self.scale_lbl.setText(f"{int(self.scale*100)}%")

    # ── PLAYBACK ───────────────────────────────────────────────────────────
    def _pl_t(self,i):
        if i<0 or i>=len(self.pl): return
        self.idx=i; uri,name=self.pl[i]

        # Jeśli aktualnie gramy monitor i przełączamy na ten sam monitor — nic nie rób
        if self._mon_pipe and uri.startswith("pulsesrc://"):
            # Już gramy monitor — sprawdź czy to ten sam device
            mon_dev = uri.replace("pulsesrc://","")
            cur_src = self._mon_pipe.get_by_name("mon_src")
            if cur_src:
                try:
                    cur_dev = cur_src.get_property("device")
                    if cur_dev == mon_dev:
                        return  # Ten sam monitor — nic nie rób
                except: pass

        # Zatrzymaj monitor pipeline jeśli istnieje
        if self._mon_pipe:
            self._stop_monitor_pipe()
            self.play = False

        if uri.startswith("pulsesrc://"):
            self._start_mon_pipe(uri.replace("pulsesrc://",""), name); return

        # Stop main pipeline before changing URI
        self.ply.set_state(Gst.State.NULL)
        self.ply.get_state(Gst.CLOCK_TIME_NONE)

        if "[TV]" in name:
            self.dstack.setCurrentIndex(1)
            self.video_player.setSource(QUrl(uri)); self.video_player.play()
        else:
            self.dstack.setCurrentIndex(0); self.video_player.stop()

        self.src.set_property("uri",uri)
        # Re-wstrzyknij aktywne MBL przed startem playbacku
        if hasattr(self, 'limiter_router'):
            for pid in self.limiter_router.registered_points():
                mbl = self.limiter_router.get(pid)
                if mbl and not mbl._injected and mbl.enabled and mbl._upstream and mbl._downstream:
                    mbl.inject(mbl._upstream, mbl._downstream)
        ret=self.ply.set_state(Gst.State.PLAYING)
        print(f"Play: {name}  [{ret.value_name}]")
        self.play=True; self.bp.setText("⏸")
        self.lt.setText(name); self.ls.setCurrentRow(i); self._up_meta()

    def _pp(self):
        if not self.pl: return
        if self.idx==-1: self._pl_t(0); return
        pipe=self._mon_pipe or self.ply
        if self.play:
            pipe.set_state(Gst.State.PAUSED); self.play=False; self.bp.setText("▶")
        else:
            pipe.set_state(Gst.State.PLAYING); self.play=True; self.bp.setText("⏸")

    def _next(self):
        if self.pl: self._pl_t((self.idx+1)%len(self.pl))
    def _prev(self):
        if self.pl: self._pl_t((self.idx-1)%len(self.pl))

    def _seek(self):
        if self._mon_pipe: return
        self.ply.seek_simple(Gst.Format.TIME,Gst.SeekFlags.FLUSH,self.sk.value()*Gst.SECOND)

    def _vol(self,v):
        vol=v/100.0
        if self.hw_sink:
            try: self.hw_sink.set_property("volume",vol)
            except: pass
        if self._mon_pipe:
            hw=self._mon_pipe.get_by_name("mon_hw")
            if hw:
                try: hw.set_property("volume",vol)
                except: pass

    def _clr(self):
        self.ply.set_state(Gst.State.NULL)
        self._stop_monitor_pipe()
        self.video_player.stop(); self.dstack.setCurrentIndex(0)
        self.play=False; self.pl=[]; self.ls.clear(); self.idx=-1; self.lt.setText("Ready")

    def _add(self):
        files,_=QFileDialog.getOpenFileNames(self,"Add","",
            "Audio (*.mp3 *.flac *.wav *.ogg *.aac *.m4a);;Playlist (*.m3u *.m3u8);;All (*)")
        for p in files:
            if p.lower().endswith(('.m3u','.m3u8')):
                for u,n in parse_m3u(p): self.pl.append((u,n)); self.ls.addItem(n)
            else:
                self.pl.append(("file:///"+p.replace("\\","/"),os.path.basename(p)))
                self.ls.addItem(os.path.basename(p))
        if not self.play and self.idx==-1 and self.pl: self._pl_t(0)

    def _load_m3u(self):
        f,_=QFileDialog.getOpenFileName(self,"Open M3U","","M3U (*.m3u *.m3u8);;All (*)")
        if not f: return
        for u,n in parse_m3u(f): self.pl.append((u,n)); self.ls.addItem(n)
        if not self.play and self.idx==-1 and self.pl: self._pl_t(0)

    def _auto_load_m3u(self):
        p=os.path.join(os.path.dirname(os.path.abspath(__file__)),"channels.m3u")
        if os.path.exists(p):
            for u,n in parse_m3u(p): self.pl.append((u,n)); self.ls.addItem(n)

    def _search_radio(self):
        if not PYRADIOS_OK: QMessageBox.critical(self,"Error","pyradios not installed"); return
        d=RadioSearchDialog(self)
        if d.exec()==QDialog.DialogCode.Accepted:
            for u,n in d.get_selected():
                name=f"[Radio] {n}"; self.pl.append((u,name)); self.ls.addItem(name)
            if not self.play and self.idx==-1 and self.pl: self._pl_t(0)

    # ── MONITOR MODE ────────────────────────────────────────────────────────
    def _stop_monitor_pipe(self):
        """Bezpiecznie zatrzymuje i usuwa monitor pipeline."""
        if self._mon_pipe:
            self._mon_pipe.set_state(Gst.State.NULL)
            self._mon_pipe.get_state(Gst.CLOCK_TIME_NONE)
            self._mon_pipe = None
        if self._mon_resolver:
            self._mon_resolver = None
        # Wyczyść extra resolvers z chain_panel i anuluj pending rebuild
        if hasattr(self.chain_panel, '_extra_resolvers'):
            self.chain_panel._extra_resolvers.clear()
        if hasattr(self.chain_panel, '_rebuild_timer'):
            self.chain_panel._rebuild_timer.stop()
        # Przywróć widgety do main pipeline
        self.eqw.set_gst(self.eq)
        self.tape_sim.set_pipeline(self.tape_sat, self.tape_gain, self.tape_tone)
        self.tape_spatial.set_pipeline(self.sp_stereo, self.sp_echo, self.sp_sat)
        self.chain_panel.attach(self.chain_els)  # blockSignals wbudowane w attach()

    def _start_monitor(self):
        if not create_virtual_sink():
            QMessageBox.critical(self,"Error","Failed to create virtual sink!"); return

        # Jeśli monitor już jest na playliście — po prostu przełącz na niego
        mon_uri = f"pulsesrc://{VIRTUAL_SINK}.monitor"
        mon_name = f"[Monitor] {VIRTUAL_SINK}"
        for i,(u,n) in enumerate(self.pl):
            if u == mon_uri:
                self._pl_t(i); return

        # Pierwsza aktywacja — zatrzymaj odtwarzanie i dodaj wpis (tylko raz)
        if self.play: self._pp()
        self.pl.append((mon_uri, mon_name))
        self.ls.addItem(mon_name)
        self._pl_t(len(self.pl)-1)

    def _start_mon_pipe(self, device, name):
        # Zatrzymaj poprzedni monitor pipeline jeśli istnieje
        self._stop_monitor_pipe()
        # Wysuń aktywne MBL przed NULL — set_state(NULL) zrywa pady GST
        _mbl_states = {}
        if hasattr(self, 'limiter_router'):
            for pid in self.limiter_router.registered_points():
                mbl = self.limiter_router.get(pid)
                if mbl and mbl._injected:
                    mbl.eject()
                    _mbl_states[pid] = True
        self.ply.set_state(Gst.State.NULL)
        self.ply.get_state(Gst.CLOCK_TIME_NONE)

        p = Gst.Pipeline.new("mon-pipe"); self._mon_pipe = p

        src   = mkgst("pulsesrc",   "mon_src",  {"device": device})
        conv  = mkgst("audioconvert","mon_conv")
        res   = mkgst("audioresample","mon_res")
        tee   = mkgst("tee",        "mon_tee")
        q_fx  = mkgst("queue","mon_q_fx",{"max-size-buffers":0,"max-size-time":0,"max-size-bytes":0})
        t_sat = mkgst("audiodynamic","mon_tsat",
                      {"characteristics":"soft-knee","mode":"compressor",
                       "threshold":1.0,"ratio":1.0})
        t_gn  = mkgst("volume",     "mon_tgn",  {"volume":1.0})
        t_tn  = mkgst("equalizer-3bands","mon_ttn")
        eq10  = mkgst("equalizer-10bands","mon_eq10")
        sp_sat  = mkgst("audiodynamic","mon_spsat",
                        {"characteristics":"hard-knee","mode":"compressor",
                         "threshold":0.0,"ratio":1.0})
        sp_conv1 = mkgst("audioconvert","mon_sp_conv1")
        sw       = mkgst("stereo","mon_sw",{"stereo":1.0})
        sp_conv2 = mkgst("audioconvert","mon_sp_conv2")
        echo     = mkgst("audioecho","mon_echo",{"delay":1,"intensity":0.0,"feedback":0.0})

        # Używamy pulsesink z default sink — NIE autoaudiosink (który tworzy nowy strumień)
        # sync=False żeby uniknąć underrun przy przetwarzaniu FX
        cvo = mkgst("audioconvert","mon_cvo")
        hw  = mkgst("pulsesink","mon_hw",{"sync":False,"volume":self.vol_sl.value()/100.0})

        q_sp  = mkgst("queue","mon_q_sp",{"max-size-buffers":0,"max-size-time":0,"max-size-bytes":0})
        msp   = mkgst("spectrum","mon_sp",{"bands":64,"threshold":-80,
                                           "post-messages":True,"message-magnitude":True})
        msnk  = mkgst("fakesink","mon_fsnk",{"sync":False,"silent":True})

        # Kopiuj ustawienia z main pipeline
        if self.eq and eq10:
            for i in range(10):
                try: eq10.set_property(f"band{i}", self.eq.get_property(f"band{i}"))
                except: pass
        for src_el, dst_el, props in [
            (self.tape_sat,  t_sat,  ["threshold","ratio"]),
            (self.tape_gain, t_gn,   ["volume"]),
            (self.sp_stereo, sw,     ["stereo"]),
            (self.sp_echo,   echo,   ["delay","intensity","feedback"]),
            (self.sp_sat,    sp_sat, ["threshold","ratio"]),
        ]:
            if src_el and dst_el:
                for prop in props:
                    try: dst_el.set_property(prop, src_el.get_property(prop))
                    except: pass

        mon_chain={}
        for mid in CHAIN_ORDER:
            plugin,neutral,_=CHAIN_GST[mid]
            el=mkgst(plugin,f"mon_ch_{mid}",neutral)
            main_el=self.chain_els.get(mid)
            if main_el and el:
                for prop in neutral:
                    try: el.set_property(prop,main_el.get_property(prop))
                    except: pass
            mon_chain[mid]=el

        for el in ([src,conv,res,tee,q_fx,t_sat,t_gn,t_tn,eq10,sp_sat,
                    sp_conv1,sw,sp_conv2,echo]
                   +list(mon_chain.values())
                   +[cvo,hw,q_sp,msp,msnk]):
            if el: p.add(el)

        def lnk(a,b):
            if a and b:
                if not a.link(b): print(f"  [!] mon link: {a.get_name()}->{b.get_name()}")
        lnk(src,conv); lnk(conv,res); lnk(res,tee); lnk(tee,q_fx)
        prev=q_fx
        for el in [t_sat,t_gn,t_tn,eq10,sp_sat,sp_conv1,sw,sp_conv2,echo]:
            if el: lnk(prev,el); prev=el

        # AutoResolver dla monitor chain
        mon_resolver = DSPAutoResolver(
            pipeline    = p,
            entry_el    = echo,
            exit_el     = cvo,
            name_prefix = "mon",
        )
        mon_resolver.set_chain_elements(mon_chain)
        mon_resolver.init_convs()
        mon_resolver.limiter_router = self.limiter_router  # musi być przed rebuild!

        # Domyślne połączenie — jeśli brak aktywnych, echo → cvo bezpośrednio
        enabled = [mid for mid, w in self.chain_panel.mws.items() if w.en.isChecked()]
        if enabled:
            mon_resolver.rebuild(enabled)
        else:
            lnk(echo, cvo)

        lnk(cvo,hw)
        lnk(tee,q_sp); lnk(q_sp,msp); lnk(msp,msnk)

        bus=p.get_bus(); bus.add_signal_watch()
        bus.connect("message",self._on_mon_bus)

        self.eqw.set_gst(self.eq,eq10)
        self.tape_sim.set_pipeline(self.tape_sat,self.tape_gain,self.tape_tone,t_sat,t_gn,t_tn)
        self.tape_spatial.set_pipeline(self.sp_stereo,self.sp_echo,self.sp_sat,sw,echo,sp_sat)
        self.chain_panel.attach(self.chain_els,mon_chain)
        # Podepnij resolver monitora jako drugi resolver (działa obok głównego)
        self._mon_resolver = mon_resolver
        self.chain_panel.add_resolver(mon_resolver)

        ret=p.set_state(Gst.State.PLAYING)
        print(f"Monitor pipeline: {ret.value_name}")
        self.play=True; self.bp.setText("⏸")
        self.lt.setText(f"🎤 {name}"); self.ls.setCurrentRow(self.idx); self._up_meta()

    def _on_mon_bus(self,bus,msg):
        if msg.type==Gst.MessageType.ERROR:
            err,dbg=msg.parse_error(); print(f"Mon ERR: {err.message} | {dbg}")
        elif msg.type==Gst.MessageType.ELEMENT:
            s=msg.get_structure()
            if s and s.get_name()=="spectrum": self._spectrum(s)

    # ── POLL TIMER ──────────────────────────────────────────────────────────
    def _poll(self):
        if not self.play or self._mon_pipe: return
        ok,pos=self.ply.query_position(Gst.Format.TIME)
        ok2,dur=self.ply.query_duration(Gst.Format.TIME)
        if ok and ok2 and dur>0:
            if not self.sk.isSliderDown():
                self.sk.setRange(0,int(dur/Gst.SECOND)); self.sk.setValue(int(pos/Gst.SECOND))
            ps=int(pos/Gst.SECOND); ds=int(dur/Gst.SECOND)
            self.lm.setText(f"{ps//60}:{ps%60:02}/{ds//60}:{ds%60:02}")

    def _up_meta(self):
        if not self.pl: self.viz.set_covers_data((None,"",""),(None,"",""),(None,"","")); return
        l=len(self.pl); c=self.idx; g=lambda i:get_metadata(*self.pl[i])
        self.viz.set_covers_data(g((c-1)%l),g(c),g((c+1)%l))

# ============================================================================
# ENTRY
# ============================================================================
if __name__=="__main__":
    app=QApplication(sys.argv); app.setStyle("Fusion")
    pal=QPalette()
    pal.setColor(QPalette.ColorRole.Window,      QColor(13,13,16))
    pal.setColor(QPalette.ColorRole.WindowText,  QColor(220,220,220))
    pal.setColor(QPalette.ColorRole.Base,        QColor(10,10,12))
    pal.setColor(QPalette.ColorRole.Text,        QColor(200,200,200))
    pal.setColor(QPalette.ColorRole.Button,      QColor(22,22,28))
    pal.setColor(QPalette.ColorRole.ButtonText,  QColor(220,220,220))
    pal.setColor(QPalette.ColorRole.Highlight,   QColor(0,100,160))
    pal.setColor(QPalette.ColorRole.HighlightedText,QColor(255,255,255))
    app.setPalette(pal)
    w=CarbonPhaserPlayer(); w.show(); sys.exit(app.exec())
