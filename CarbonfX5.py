#!/usr/bin/env python3
"""
CarbonX Player  v3.0  "Grid Edition"
- Naprawiony tor audio: uridecodebin + tee -> FX chain -> autoaudiosink
- Layout 2x2 (16:10): playlista | wizualizer / FX tabs z TapeSim/Spatial/EQ/Chain
- Skalowalny UI (przyciski + / -)
- Signal Chain 13 modulow DSP z zapisem presetow JSON
- Monitor Mode przez wirtualny PulseAudio sink
"""
import sys, os, math, random, re, json

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QListWidget, QFileDialog, QFrame,
    QComboBox, QGroupBox, QCheckBox, QMessageBox, QDial,
    QDialog, QLineEdit, QSpinBox, QListWidgetItem, QStackedWidget,
    QScrollArea, QSplitter, QTabWidget, QButtonGroup
)
from PyQt6.QtCore  import Qt, QTimer, QPointF, QRect, QUrl
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
                   {"stereo":(0.0,2.0,1.0,100,"x")}),
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
            return optimal  # nic się nie zmieniło

        print(f"[AutoResolver:{self.name_prefix}] {self._current_order} → {optimal}")
        self._current_order = optimal

        pipe = self.pipeline

        # ── 1. Zapamiętaj stan i ustaw NULL ──────────────────────────────────
        _, cur_state, _ = pipe.get_state(0)
        was_playing = (cur_state == Gst.State.PLAYING)
        was_paused  = (cur_state == Gst.State.PAUSED)

        pipe.set_state(Gst.State.NULL)
        pipe.get_state(Gst.CLOCK_TIME_NONE)

        # ── 2. Odepnij wszystko pomiędzy entry a exit ─────────────────────────
        # Odpinamy srcpad entry_el
        src_pad = self.entry_el.get_static_pad("src")
        if src_pad and src_pad.is_linked():
            peer = src_pad.get_peer()
            if peer:
                src_pad.unlink(peer)

        # Odpinamy wszystkie łańcuchowe elementy (chain + konwertery)
        all_middle = list(self.chain_els.values()) + self._convs
        for el in all_middle:
            if not el:
                continue
            sp = el.get_static_pad("src")
            if sp and sp.is_linked():
                peer = sp.get_peer()
                if peer:
                    sp.unlink(peer)
            sk = el.get_static_pad("sink")
            if sk and sk.is_linked():
                peer = sk.get_peer()
                if peer:
                    peer.unlink(sk)

        # Odpinamy sinkpad exit_el
        sink_pad = self.exit_el.get_static_pad("sink")
        if sink_pad and sink_pad.is_linked():
            peer = sink_pad.get_peer()
            if peer:
                peer.unlink(sink_pad)

        # ── 3. Zbuduj sekwencję elementów z konwerterami ─────────────────────
        sequence = []
        conv_idx = 0
        prev_meta = None

        for i, mid in enumerate(optimal):
            meta = DSP_META.get(mid, {})
            el   = self.chain_els.get(mid)
            if not el:
                continue

            # Konwerter PRZED — gdy moduł wymaga float lub poprzedni zostawił float
            need_pre = meta.get("needs_conv_before", False)
            if not need_pre and prev_meta and prev_meta.get("needs_conv_after", False):
                need_pre = True  # poprzedni zostawił float, ten nie akceptuje

            if need_pre and conv_idx < len(self._convs):
                sequence.append(self._convs[conv_idx]); conv_idx += 1

            sequence.append(el)

            # Konwerter PO — gdy moduł zmienia format a następny nie jest float
            if meta.get("needs_conv_after", False):
                next_mid  = optimal[i+1] if i+1 < len(optimal) else None
                next_meta = DSP_META.get(next_mid, {}) if next_mid else {}
                if not next_meta.get("float_required", False):
                    if conv_idx < len(self._convs):
                        sequence.append(self._convs[conv_idx]); conv_idx += 1

            prev_meta = meta

        # ── 4. Podłącz: entry → [sequence] → exit ────────────────────────────
        chain = [self.entry_el] + sequence + [self.exit_el]

        def lnk(a, b):
            if not a.link(b):
                print(f"  [AutoResolver] BŁĄD link: {a.get_name()} → {b.get_name()}")

        for a, b in zip(chain, chain[1:]):
            lnk(a, b)

        print(f"  łańcuch: {' → '.join(e.get_name() for e in chain)}")

        # ── 5. Wznów pipeline ─────────────────────────────────────────────────
        if was_playing:
            pipe.set_state(Gst.State.PLAYING)
        elif was_paused:
            pipe.set_state(Gst.State.PAUSED)
        # jeśli był NULL — nie wznawiamy (np. przy init)

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
            try: el.set_property(k,v)
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
    def __init__(self,parent=None):
        super().__init__(parent); self.setMinimumHeight(180)
        self.ad=[0.0]*64; self.bl=0.0; self.ph=0.0
        self.dc=(None,"",""); self.dp=(None,"",""); self.dn=(None,"","")
        self.bg=None; self.phaser_mode="linear"; self.phase_speed=0.03; self.parts=[]
        self.presets={
            "Cyberpunk":{"layers":["grid_3d","spectrum_bars","digital_rain"],"c":("#00FFFF","#FF00FF","#050010")},
            "Solar":    {"layers":["starfield","pulse_orb","flux_wave"],"c":("#FFDD00","#FF4400","#100500")},
            "Ocean":    {"layers":["flux_wave","bubbles","mirror_spectrum"],"c":("#0088FF","#00FF88","#001020")},
            "Matrix":   {"layers":["digital_rain","spectrum_bars"],"c":("#00FF00","#008800","#000000")},
            "Neon":     {"layers":["grid_3d","pulse_orb","mirror_spectrum"],"c":("#FF0055","#5500FF","#101010")},
        }
        self.curr="Cyberpunk"
        self.tm=QTimer(); self.tm.timeout.connect(self._anim); self.tm.start(16)

    def set_preset(self,n): self.curr=n; self.parts=[]
    def set_covers_data(self,p,c,n): self.dp=p; self.dc=c; self.dn=n; self.bg=blur_pixmap(c[0],self.size()) if c[0] else None; self.update()
    def update_data(self,d):
        if d: self.ad=d; self.bl=self.bl*0.8+(sum(d[:5])/5)*0.2; self.update()
    def _anim(self): self.ph+=self.phase_speed; self.update()

    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w,h=self.width(),self.height()
        pr=self.presets.get(self.curr,self.presets["Cyberpunk"]); c=pr["c"]
        if self.bg: p.drawPixmap(0,0,self.bg.scaled(self.size()))
        else: p.fillRect(0,0,w,h,QColor(c[2]))
        for layer in pr["layers"]:
            getattr(self,f"_draw_{layer}",lambda *a:None)(p,w,h,c)
        self._draw_sidebar(p,w,h); p.end()

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
                try: el.set_property(prop,val)
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
    RANGES = {
        "width":  (0,   200, 100,  50,  150),   # /100 -> stereo prop
        "haas":   (0,   20,  0,    0,   15),     # ms
        "sat":    (10,  80,  10,   10,  30),     # /10 -> ratio
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
            try: el.set_property(prop, val)
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
        stereo = v / 100.0   # 0.0..2.0  (1.0 = neutral)
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
        # (width%, haas_ms, sat*10)
        p = {"Flat": (100, 0, 10), "Studio": (110, 8, 15), "Wide": (130, 12, 20)}
        if n in p:
            w, h, s = p[n]
            mn_w,mx_w,_,smn_w,smx_w = self.RANGES["width"]
            mn_h,mx_h,_,smn_h,smx_h = self.RANGES["haas"]
            mn_s,mx_s,_,smn_s,smx_s = self.RANGES["sat"]
            if self._safe_mode:
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
                        try: el.set_property(gp,float(val))
                        except: pass

    def _bypass(self):
        _,neutral,_=CHAIN_GST.get(self.mid,("",{},""))
        for el in self.gst_els:
            for k,v in neutral.items():
                try: el.set_property(k,v)
                except: pass

    def _phase(self):
        if not self.en.isChecked(): return
        d=1.0 if(getattr(self,'invL',None)and(self.invL.isChecked()or self.invR.isChecked())) else 0.0
        for el in self.gst_els:
            try: el.set_property("degree",d)
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
            me=main_els.get(mid)
            if me: w.add_gst(me)
            if mon_els:
                mone=mon_els.get(mid)
                if mone: w.add_gst(mone)

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

        # Spectrum branch
        lnk(self.tee,self.q_sp); lnk(self.q_sp,self.sp); lnk(self.sp,self.sp_snk)
        lnk(self.conv_out,self.hw_sink)

        bus=self.ply.get_bus(); bus.add_signal_watch()
        bus.connect("message",self._on_bus)
        print("Main pipeline built (DSPAutoResolver aktywny)")

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
            GLib.idle_add(lambda:(self.ply.set_state(Gst.State.NULL),
                                  setattr(self,'play',False),
                                  self.bp.setText("Play")))
        elif t==Gst.MessageType.ELEMENT:
            s=msg.get_structure()
            if s and s.get_name()=="spectrum":
                self._spectrum(s)

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
        t1v.addWidget(self.tape_sim); t1v.addWidget(self.tape_spatial); t1v.addStretch()
        self.tabs.addTab(t1,"🎛 Tape & Spatial")

        # Tab 2: EQ + Phaser
        t2=QWidget(); t2v=QVBoxLayout(t2); t2v.setContentsMargins(4,4,4,4); t2v.setSpacing(4)
        self.eqw=EqualizerWidget(); self.phaser=PhaserWidget(self.viz,self.eqw)
        t2v.addWidget(self.eqw); t2v.addWidget(self.phaser); t2v.addStretch()
        self.tabs.addTab(t2,"🎚 EQ & Phase")

        # Tab 3: Signal Chain
        self.chain_panel=SignalChainPanel()
        self.tabs.addTab(self.chain_panel,"🔗 Signal Chain")

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
        # Podepnij AutoResolver do SignalChainPanel
        self.chain_panel.set_resolver(self.dsp_resolver)

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
        # Wyczyść extra resolvers z chain_panel
        if hasattr(self.chain_panel, '_extra_resolvers'):
            self.chain_panel._extra_resolvers.clear()
        # Przywróć widgety do main pipeline
        self.eqw.set_gst(self.eq)
        self.tape_sim.set_pipeline(self.tape_sat, self.tape_gain, self.tape_tone)
        self.tape_spatial.set_pipeline(self.sp_stereo, self.sp_echo, self.sp_sat)
        self.chain_panel.attach(self.chain_els)

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
