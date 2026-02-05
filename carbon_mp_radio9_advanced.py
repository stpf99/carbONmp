import sys
import os
import math
import random
import re
from urllib.request import urlopen, Request

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QSlider, QLabel, QListWidget,
                             QFileDialog, QFrame, QComboBox, QGroupBox, QCheckBox,
                             QButtonGroup, QInputDialog, QMessageBox, QDial, QDialog,
                             QLineEdit, QSpinBox, QListWidgetItem, QStackedWidget) # Added more widgets
from PyQt6.QtCore import Qt, QTimer, QPointF, QRect, QUrl
from PyQt6.QtGui import (QPainter, QColor, QPen, QBrush, QLinearGradient,
                         QRadialGradient, QPixmap, QImage, QPainterPath, QFontMetrics)
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget

# --- GStreamer Import ---
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

# --- Opcjonalne Biblioteki ---
try:
    import eyed3
    import logging
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
# ADVANCED RADIO SEARCH DIALOG
# ============================================================================
class RadioSearchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Advanced Radio Search")
        self.setModal(True)
        self.setMinimumSize(700, 500)
        self.setStyleSheet("""
            QDialog { background: #1a1a1e; }
            QLabel { color: #ddd; font-size: 11px; }
            QLineEdit, QSpinBox { background: #2a2a30; color: #eee; border: 1px solid #444; padding: 5px; border-radius: 3px; }
            QPushButton { background: #2a2a30; color: #eee; border: 1px solid #444; padding: 6px 15px; border-radius: 4px; }
            QPushButton:hover { border-color: #00AAAA; background: #333; }
            QPushButton:pressed { background: #444; }
            QListWidget { background: #18181c; border: 1px solid #333; color: #ddd; }
            QListWidget::item:selected { background: #0088CC; }
            QListWidget::item:hover { background: #2a2a30; }
        """)
        
        self.selected_stations = []
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # Search filters
        filters = QGroupBox("Search Filters")
        filters.setStyleSheet("QGroupBox { color: #00AAAA; border: 1px solid #444; margin-top: 10px; padding-top: 10px; }")
        f_layout = QVBoxLayout(filters)
        
        # Name search
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Name:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., BBC, NPR, Jazz...")
        name_layout.addWidget(self.name_input)
        f_layout.addLayout(name_layout)
        
        # Tag/Genre search
        tag_layout = QHBoxLayout()
        tag_layout.addWidget(QLabel("Tag/Genre:"))
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("e.g., jazz, rock, news, classical...")
        tag_layout.addWidget(self.tag_input)
        f_layout.addLayout(tag_layout)
        
        # Country search
        country_layout = QHBoxLayout()
        country_layout.addWidget(QLabel("Country:"))
        self.country_input = QLineEdit()
        self.country_input.setPlaceholderText("e.g., Poland, USA, UK...")
        country_layout.addWidget(self.country_input)
        f_layout.addLayout(country_layout)
        
        # Language search
        lang_layout = QHBoxLayout()
        lang_layout.addWidget(QLabel("Language:"))
        self.lang_input = QLineEdit()
        self.lang_input.setPlaceholderText("e.g., polish, english, spanish...")
        lang_layout.addWidget(self.lang_input)
        f_layout.addLayout(lang_layout)
        
        # Limit
        limit_layout = QHBoxLayout()
        limit_layout.addWidget(QLabel("Max Results:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(5, 100)
        self.limit_spin.setValue(30)
        self.limit_spin.setFixedWidth(80)
        limit_layout.addWidget(self.limit_spin)
        limit_layout.addStretch()
        f_layout.addLayout(limit_layout)
        
        layout.addWidget(filters)
        
        # Search button
        self.search_btn = QPushButton("🔍 Search Stations")
        self.search_btn.clicked.connect(self.perform_search)
        self.search_btn.setStyleSheet("QPushButton { font-weight: bold; background: #0088CC; } QPushButton:hover { background: #00AACC; }")
        layout.addWidget(self.search_btn)
        
        # Results list
        results_label = QLabel("Search Results:")
        results_label.setStyleSheet("font-weight: bold; color: #00AAAA; font-size: 12px;")
        layout.addWidget(results_label)
        
        self.results_list = QListWidget()
        self.results_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(self.results_list)
        
        # Status label
        self.status_label = QLabel("Enter search criteria and click Search")
        self.status_label.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(self.status_label)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.add_btn = QPushButton("Add Selected to Playlist")
        self.add_btn.clicked.connect(self.accept)
        self.add_btn.setEnabled(False)
        self.add_btn.setStyleSheet("QPushButton { background: #00AA00; } QPushButton:hover { background: #00CC00; }")
        btn_layout.addWidget(self.add_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
        
        self.results_list.itemSelectionChanged.connect(self.update_add_button)
    
    def perform_search(self):
        if not PYRADIOS_OK:
            self.status_label.setText("❌ Error: pyradios library not installed")
            return
        
        self.results_list.clear()
        self.search_btn.setEnabled(False)
        self.status_label.setText("🔄 Searching...")
        QApplication.processEvents()
        
        try:
            rb = RadioBrowser()
            
            # Build search parameters
            params = {}
            
            name = self.name_input.text().strip()
            if name:
                params['name'] = name
            
            tag = self.tag_input.text().strip()
            if tag:
                params['tag'] = tag
            
            country = self.country_input.text().strip()
            if country:
                params['country'] = country
            
            language = self.lang_input.text().strip()
            if language:
                params['language'] = language
            
            params['limit'] = self.limit_spin.value()
            
            # Perform search
            if not params or len(params) == 1:  # Only limit
                self.status_label.setText("⚠️ Please enter at least one search criterion")
                self.search_btn.setEnabled(True)
                return
            
            stations = rb.search(**params)
            
            if not stations:
                self.status_label.setText("No stations found. Try different search criteria.")
                self.search_btn.setEnabled(True)
                return
            
            # Populate results
            for s in stations:
                name = s.get('name', 'Unknown').strip()
                url = s.get('url_resolved')
                country = s.get('country', '')
                tags = s.get('tags', '')
                bitrate = s.get('bitrate', 0)
                
                if url and name:
                    # Create display text with extra info
                    display = f"{name}"
                    if country:
                        display += f" [{country}]"
                    if tags:
                        display += f" • {tags[:30]}"
                    if bitrate:
                        display += f" • {bitrate}kbps"
                    
                    item = QListWidgetItem(display)
                    item.setData(Qt.ItemDataRole.UserRole, (url, name))
                    self.results_list.addItem(item)
            
            self.status_label.setText(f"✓ Found {len(stations)} stations")
            
        except Exception as e:
            self.status_label.setText(f"❌ Search error: {str(e)}")
        
        finally:
            self.search_btn.setEnabled(True)
    
    def update_add_button(self):
        self.add_btn.setEnabled(len(self.results_list.selectedItems()) > 0)
    
    def get_selected_stations(self):
        """Return list of (url, name) tuples for selected stations"""
        stations = []
        for item in self.results_list.selectedItems():
            url, name = item.data(Qt.ItemDataRole.UserRole)
            stations.append((url, f"[Radio] {name}"))
        return stations

# ============================================================================
# HELPERY
# ============================================================================
EQ_PRESETS = {
    "Flat": [0]*10, "Club": [0,0,2,3,3,3,2,0,0,0], "Bass": [6,5,4,2,0,0,0,0,0,0],
    "Treble": [0,0,0,0,0,1,3,5,5,8], "Rock": [4,3,1,-1,-2,-2,0,1,3,4],
    "Techno": [4,3,0,-2,-3,-2,0,2,4,4], "Vocal": [-2,-3,-3,1,3,3,3,1,0,-1]
}

def get_metadata(uri, fn):
    p, t, a = None, fn, "Unknown"
    # Obsługa plików lokalnych
    if uri.startswith("file://") and EYE3D_OK:
        path = uri[7:].replace("/", os.sep)
        if os.path.exists(path):
            try:
                f = eyed3.load(path)
                if f and f.tag:
                    t = f.tag.title or t; a = f.tag.artist or a
                    if f.tag.images: p = QPixmap.fromImage(QImage.fromData(f.tag.images[0].image_data))
            except: pass

    # Obsługa Radia
    if "[Radio]" in fn:
        a = "Internet Radio"
        t = fn.replace("[Radio] ", "")
    
    # Obsługa TV
    if "[TV]" in fn:
        a = "TV Channel"
        t = fn.replace("[TV] ", "")

    return (p, t, a)

def blur_pixmap(p, s):
    if not p: return None
    img = p.scaled(s.width()//20, s.height()//20, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation).toImage()
    b = img.scaled(s, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    pt = QPainter(b); pt.fillRect(b.rect(), QColor(0,0,0,160)); pt.end()
    return QPixmap.fromImage(b)

def parse_m3u(filepath):
    """Parse M3U playlist file and return list of (url, name) tuples"""
    entries = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        current_name = None
        for line in lines:
            line = line.strip()
            if line.startswith('#EXTINF:'):
                # Extract channel name (text after the last comma)
                parts = line.split(',', 1)
                if len(parts) > 1:
                    current_name = parts[1].strip()
            elif line and not line.startswith('#'):
                # This is a URL line
                url = line.strip()
                if current_name:
                    entries.append((url, f"[TV] {current_name}"))
                    current_name = None
                else:
                    # Fallback if no EXTINF was found
                    entries.append((url, f"[Stream] {url.split('/')[-1]}"))
    except Exception as e:
        print(f"M3U Parse Error: {e}")
    
    return entries

# ============================================================================
# ANALOG TAPE SIMULATOR (ATS-1 STYLE) - FINAL FIX
# ============================================================================
class AnalogTapeWidget(QGroupBox):
    def __init__(self, gst_pipeline, parent=None):
        super().__init__("ATS-1 Tape Simulation", parent)
        self.pipe = gst_pipeline
        self.setStyleSheet("""
            QGroupBox { color: #FFCC00; border: 1px solid #444; margin-top: 10px; font-weight: bold; background: #151515; }
            QLabel { color: #888; font-size: 10px; font-family: 'Consolas'; }
            QDial { background: #111; }
        """)
        self.setFixedHeight(100)
        l = QHBoxLayout(self); l.setSpacing(15); l.setContentsMargins(15, 15, 15, 5)

        # 1. Przycisk Bypass (musi być pierwszy)
        self.bypass_btn = QPushButton("ACTIVE")
        self.bypass_btn.setCheckable(True)
        self.bypass_btn.setChecked(True)
        self.bypass_btn.setStyleSheet("QPushButton{background:#330000;color:#555;border:1px solid #444} QPushButton:checked{background:#CC0000;color:#FFF;border:1px solid #F00}")
        self.bypass_btn.setFixedWidth(60)
        self.bypass_btn.toggled.connect(self.toggle_bypass)

        # 2. Pokrętła
        self.add_knob(l, "DRIVE", self.set_drive, 0, 100, 50, "Saturation Amount")
        self.add_knob(l, "WARMTH", self.set_warmth, 0, 100, 30, "Analog Low-End / High-Roll-off")
        self.add_knob(l, "COMP", self.set_comp, 0, 100, 20, "Tape Compression")

        l.addStretch()
        l.addWidget(self.bypass_btn)

    def add_knob(self, layout, name, func, min_v, max_v, def_v, tip):
        v = QVBoxLayout()
        d = QDial()
        d.setRange(min_v, max_v)
        d.setValue(def_v)
        d.setNotchesVisible(True)
        d.setFixedSize(50, 50)
        d.valueChanged.connect(func)
        d.setToolTip(tip)
        lbl = QLabel(name); lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(d); v.addWidget(lbl)
        layout.addLayout(v)
        # Trigger initial value immediately
        QTimer.singleShot(100, lambda: func(def_v))

    def toggle_bypass(self, state):
        if not self.pipe: return
        if not state:
            # RESET DO FLAT (BYPASS)
            try:
                # Saturation OFF
                ts = self.pipe.get_by_name("tape_sat")
                tg = self.pipe.get_by_name("tape_gain")
                tt = self.pipe.get_by_name("tape_tone")

                if ts:
                    ts.set_property("ratio", 1.0) # Brak kompresji
                    ts.set_property("threshold", 0.0) # Próg na 0 (lub 1.0 zaleznie od implementacji, bezpiecznie 0 dla braku dzialania)
                if tg: tg.set_property("volume", 1.0) # Głośność neutralna
                if tt:
                    tt.set_property("band2", 0.0)
                    tt.set_property("band0", 0.0)
            except: pass
        # Jeśli włączamy (state=True), pokrętła same zaktualizują stan przy najbliższym ruchu,
        # lub można by wymusić odświeżenie, ale w tym modelu wystarczy ruszyć gałką.

    def set_drive(self, v):
        # DRIVE: Obniżamy próg (threshold) i podnosimy gain (makeup)
        if not self.pipe or not self.bypass_btn.isChecked(): return

        # 1. Threshold (kompresor): 0.0 do 1.0.
        # Duży Drive = Mały Threshold (mocna kompresja sygnału)
        # Mapujemy 0-100 na zakres 0.9 do 0.1
        thresh = 0.9 - (v / 100.0 * 0.8)

        # 2. Makeup Gain (nowy element tape_gain)
        # Mapujemy 0-100 na głośność 1.0x do 1.8x
        gain = 1.0 + (v / 100.0 * 0.8)

        try:
            ts = self.pipe.get_by_name("tape_sat")
            tg = self.pipe.get_by_name("tape_gain")

            if ts: ts.set_property("threshold", float(thresh))
            if tg: tg.set_property("volume", float(gain))
        except Exception as e: print(f"Drive Error: {e}")

    def set_comp(self, v):
        if not self.pipe or not self.bypass_btn.isChecked(): return
        el = self.pipe.get_by_name("tape_sat")
        if el:
            # Ratio: 1.0 (brak) do 8.0 (mocna)
            ratio = 1.0 + (v / 100.0 * 7.0)
            try: el.set_property("ratio", float(ratio))
            except: pass

    def set_warmth(self, v):
        if not self.pipe or not self.bypass_btn.isChecked(): return
        el = self.pipe.get_by_name("tape_tone")
        if el:
            high_cut = -(v / 100.0 * 8.0) # Tnie górę do -8dB
            low_boost = (v / 100.0 * 5.0) # Podbija dół do +5dB
            try:
                el.set_property("band2", float(high_cut))
                el.set_property("band0", float(low_boost))
            except: pass

# ============================================================================
# PHASER CONTROLLER
# ============================================================================
class PhaserWidget(QGroupBox):
    def __init__(self, viz_ref, eq_ref, parent=None):
        super().__init__("Geometry & Phasing", parent)
        self.viz = viz_ref; self.eq = eq_ref
        self.setStyleSheet("""
            QGroupBox { color: #00AAAA; border: 1px solid #333; margin-top: 10px; font-weight: bold; background: #0E0E10; }
            QPushButton { background: #1A1A1E; color: #888; border: 1px solid #333; font-size: 16px; padding: 5px; border-radius: 4px; }
            QPushButton:checked { background: #004444; color: #FFF; border: 1px solid #00AAAA; }
            QPushButton:hover { border-color: #555; color: #DDD; }
        """)
        self.setFixedHeight(80)
        l = QHBoxLayout(self); l.setSpacing(10); l.setContentsMargins(10, 15, 10, 5)
        modes = [("🌊","Linear","linear"), ("⇋","Diverge","diverge"), ("⇌","Converge","converge"),
                 ("◢","Rise","rise"), ("◣","Fall","fall"), ("🌀","Chaos","chaos")]
        self.bg = QButtonGroup(self)
        for i, n, mid in modes:
            b = QPushButton(f"{i}"); b.setToolTip(n); b.setCheckable(True)
            if mid == "linear": b.setChecked(True)
            b.clicked.connect(lambda _, m=mid: self.set_m(m)); self.bg.addButton(b); l.addWidget(b)
        l.addStretch()
        lb = QLabel("Flux Speed"); lb.setStyleSheet("color:#666;font-size:9px;border:none")
        sl = QSlider(Qt.Orientation.Horizontal); sl.setRange(0, 100); sl.setValue(30); sl.setFixedWidth(100)
        sl.valueChanged.connect(self.up_spd); l.addWidget(lb); l.addWidget(sl)

    def set_m(self, m): self.viz.phaser_mode = m; self.eq.proc.phaser_mode = m
    def up_spd(self, v): s = v/1000.0; self.viz.phase_speed = s; self.eq.proc.phase_speed = s

# ============================================================================
# SMART EQ PROCESSOR
# ============================================================================
class SmartEQProcessor:
    def __init__(self, eq_widget):
        self.eq = eq_widget; self.active = False; self.geo_active = True; self.depth = 0.5
        self.pm = "linear"; self.ph = 0.0; self.ps = 0.03
        self.tgt = [0.65, 0.65, 0.6, 0.55, 0.5, 0.5, 0.5, 0.55, 0.6, 0.6]
        self.base = [0.0]*10; self.curr = [0.0]*10; self.sm = 0.9

    def set_base(self, i, v): self.base[i] = float(v)
    def set_all_base(self, vals): self.base = [float(v) for v in vals]

    def process(self, spec):
        if not spec: return
        self.ph += self.ps
        chunk = len(spec)//10
        for i in range(10):
            gm = 0.0
            if self.geo_active:
                if self.pm == "linear": gm = math.sin(self.ph + i*0.5) * 2.0
                elif self.pm == "diverge": gm = math.sin(self.ph - abs(4.5-i)*0.5) * 3.0
                elif self.pm == "converge": gm = math.sin(self.ph + abs(4.5-i)*0.5) * 3.0
                elif self.pm == "rise": gm = math.sin(self.ph + i*0.8) * 4.0 * (i/10.0)
                elif self.pm == "fall": gm = math.sin(self.ph - i*0.8) * 4.0 * ((10-i)/10.0)
                elif self.pm == "chaos": gm = (random.random() - 0.5) * 4.0

            dc = 0.0
            if self.active:
                s = i*chunk; ea = sum(spec[s:s+chunk])/chunk if chunk else 0
                dc = (self.tgt[i] - ea) * 20.0 * self.depth

            des = max(-12.0, min(12.0, self.base[i] + gm + dc))
            self.curr[i] = (self.curr[i]*self.sm) + (des*(1.0-self.sm))
            self.eq.update_vis(i, self.curr[i])

# ============================================================================
# EQUALIZER WIDGET
# ============================================================================
class EqualizerWidget(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Equalizer & Smart DSP", parent)
        self.setStyleSheet("""
            QGroupBox { color: #BBB; border: 1px solid #333; margin-top: 10px; font-weight: bold; background: #0E0E10; }
            QSlider::groove:vertical { width: 4px; background: #222; }
            QSlider::handle:vertical { background: #00AAAA; height: 10px; margin: 0 -3px; border-radius: 5px; }
            QCheckBox { color: #00FFFF; } QLabel { color: #666; font-size: 9px; }
            QComboBox { background: #1A1A1E; color: #EEE; border: 1px solid #333; }
        """)
        self.setFixedHeight(190); self.gst = None; self.sl = []; self.proc = SmartEQProcessor(self); self.prog_upd = False
        m = QVBoxLayout(self); m.setContentsMargins(5,15,5,5); m.setSpacing(5)

        pl = QHBoxLayout()
        self.chk = QCheckBox("⚡ DYNAMIC"); self.chk.toggled.connect(self.tog_dyn)
        self.chk_g = QCheckBox("🌊 PHASE"); self.chk_g.setChecked(True); self.chk_g.toggled.connect(self.tog_geo)
        self.cb = QComboBox(); self.cb.addItems(list(EQ_PRESETS.keys())); self.cb.currentTextChanged.connect(self.app_pre)
        pl.addWidget(self.chk); pl.addWidget(self.chk_g); pl.addStretch(); pl.addWidget(self.cb); m.addLayout(pl)

        bl = QHBoxLayout(); bl.setSpacing(2)
        fr = ["32","64","125","250","500","1k","2k","4k","8k","16k"]
        for i, f in enumerate(fr):
            v = QVBoxLayout(); s = QSlider(Qt.Orientation.Vertical); s.setRange(-12,12); s.setValue(0)
            s.valueChanged.connect(lambda v, x=i: self.usr_chg(x,v)); self.sl.append(s)
            v.addWidget(s,1,Qt.AlignmentFlag.AlignHCenter); v.addWidget(QLabel(f),0,Qt.AlignmentFlag.AlignHCenter); bl.addLayout(v)
        m.addLayout(bl)

    def set_gst(self, el): self.gst = el
    def usr_chg(self, i, v):
        if not self.prog_upd: self.proc.set_base(i, v); self.set_b(i, v)
    def update_vis(self, i, v): self.prog_upd = True; self.sl[i].setValue(int(v)); self.prog_upd = False; self.set_b(i, v)
    def set_b(self, i, v):
        if self.gst: self.gst.set_property(f"band{i}", float(v))
    def tog_dyn(self, a): self.proc.active = a
    def tog_geo(self, a): self.proc.geo_active = a
    def app_pre(self, n):
        if n in EQ_PRESETS:
            self.proc.set_all_base(EQ_PRESETS[n])
            if not self.proc.active and not self.proc.geo_active:
                for i,v in enumerate(EQ_PRESETS[n]): self.sl[i].setValue(v)

# ============================================================================
# MATRIX VISUALIZER
# ============================================================================
class MatrixVisualizer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(280); self.setMouseTracking(True)
        self.ad = [0.0]*64; self.bl = 0.0; self.ph = 0.0
        self.dc = (None,"",""); self.dp = (None,"",""); self.dn = (None,"",""); self.bg = None
        self.phaser_mode = "linear"; self.phase_speed = 0.03
        self.presets = {
            "Cyberpunk": { "layers": ["grid_3d", "spectrum_bars", "digital_rain"], "c": ("#00FFFF", "#FF00FF", "#050010") },
            "Solar":     { "layers": ["starfield", "pulse_orb", "flux_wave"], "c": ("#FFDD00", "#FF4400", "#100500") },
            "Ocean":     { "layers": ["flux_wave", "bubbles", "mirror_spectrum"], "c": ("#0088FF", "#00FF88", "#001020") },
            "Matrix":    { "layers": ["digital_rain", "spectrum_bars"], "c": ("#00FF00", "#008800", "#000000") },
            "Neon":      { "layers": ["grid_3d", "pulse_orb", "mirror_spectrum"], "c": ("#FF0055", "#5500FF", "#101010") }
        }
        self.curr = "Cyberpunk"; self.parts = []
        self.tm = QTimer(); self.tm.timeout.connect(self.anim); self.tm.start(16)

    def set_preset(self, n): self.curr = n; self.parts = []
    def set_covers_data(self, p, c, n): self.dp=p; self.dc=c; self.dn=n; self.bg = blur_pixmap(c[0], self.size()) if c[0] else None; self.update()
    def update_data(self, d):
        if d: self.ad = d; self.bl = self.bl*0.8+(sum(d[:5])/5.0)*0.2; self.update()
    def anim(self): self.ph += self.phase_speed; self.update()
    def map_geo(self, i, t, w):
        p = i/t; x = i*(w/t); m = 1.0
        if self.phaser_mode == "diverge": m = 1.0 - abs(0.5-p)*2
        elif self.phaser_mode == "converge": m = abs(0.5-p)*2
        elif self.phaser_mode == "rise": m = p
        elif self.phaser_mode == "fall": m = 1.0-p
        elif self.phaser_mode == "chaos": m = 0.5 + 0.5*math.sin(i*132.0+self.ph)
        return x, m

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); w,h = self.width(), self.height()
        pre = self.presets[self.curr]; c = pre["c"]
        if self.bg: p.drawPixmap(0,0,self.bg); t=QColor(c[2]); t.setAlpha(180); p.fillRect(self.rect(), t)
        else: p.fillRect(self.rect(), QColor(c[2]))
        vw = int(w*0.72); p.save(); p.setClipRect(0,0,vw,h)
        for l in pre["layers"]: getattr(self, f"draw_{l}")(p, vw, h, c)
        p.restore(); self.draw_sb(p,w,h)

    def draw_flux_wave(self, p, w, h, c):
        ph = QPainterPath(); ph.moveTo(0, h/2); cnt = len(self.ad)
        for i, val in enumerate(self.ad):
            x, m = self.map_geo(i, cnt, w); y = (h/2) - (val*m*h/3) + math.sin(self.ph + i*0.2) * (20 + self.bl*40)
            ph.lineTo(x, y)
        ph.lineTo(w, h/2); g = QLinearGradient(0,0,w,0); g.setColorAt(0,QColor(c[0])); g.setColorAt(1,QColor(c[1]))
        p.setBrush(g); p.setPen(Qt.PenStyle.NoPen); p.drawPath(ph)
        p.save(); p.translate(0,h); p.scale(1,-1); p.drawPath(ph); p.restore()

    def draw_spectrum_bars(self, p, w, h, c):
        cnt = len(self.ad); bw = w/cnt; p.setPen(Qt.PenStyle.NoPen)
        for i, val in enumerate(self.ad):
            _, m = self.map_geo(i, cnt, w); bh = val*m*h*0.8
            col = QColor(c[1] if val>0.6 else c[0]); col.setAlpha(220); p.setBrush(col)
            p.drawRect(int(i*bw), int(h-bh), int(bw-1), int(bh))

    def draw_mirror_spectrum(self, p, w, h, c):
        cnt = len(self.ad); bw = w/cnt; mid = h/2
        for i, val in enumerate(self.ad):
            _, m = self.map_geo(i, cnt, w); bh = val*m*(h/2.5)
            p.setBrush(QColor(c[0])); p.drawRect(int(i*bw), int(mid-bh), int(bw-1), int(bh))
            tc = QColor(c[1]); tc.setAlpha(100); p.setBrush(tc); p.drawRect(int(i*bw), int(mid), int(bw-1), int(bh))

    def draw_grid_3d(self, p, w, h, c):
        p.setPen(QColor(c[1])); hy=h*0.4; cx=w/2; cnt=20
        for i in range(-cnt, cnt+1):
            o = i*(w/cnt)*2 + math.sin(self.ph)*self.bl*50
            if self.phaser_mode == "diverge": o *= (1.0 + math.sin(self.ph)*0.2)
            p.drawLine(QPointF(cx+o*0.1, hy), QPointF(cx+o, h))
        s = (self.ph*50)%100
        for i in range(10): y = hy+(i*(h-hy)/10)+s; y=y if y<h else y-(h-hy); p.drawLine(0,int(y),int(w),int(y))
        g=QLinearGradient(0,hy,0,h); C=QColor(c[0]); C.setAlpha(60); g.setColorAt(0,C); g.setColorAt(1,Qt.GlobalColor.transparent); p.fillRect(0,int(hy),int(w),int(h-hy),g)

    def draw_digital_rain(self, p, w, h, c):
        if len(self.parts)<60: self.parts.append([random.randint(0,int(w)), 0, random.randint(3,8)])
        p.setPen(QPen(QColor(c[0]),2)); act=[]; cx = w/2
        for pt in self.parts:
            if self.phaser_mode == "diverge": pt[0] += (pt[0]-cx) * 0.02
            pt[1]+=pt[2]+self.bl*15
            if pt[1]<h and 0 < pt[0] < w:
                p.setOpacity(0.5); p.drawLine(int(pt[0]),int(pt[1]),int(pt[0]),int(pt[1]-15)); p.setOpacity(1.0)
                p.setPen(QPen(QColor(c[1]),2)); p.drawPoint(int(pt[0]),int(pt[1])); p.setPen(QPen(QColor(c[0]),2)); act.append(pt)
        self.parts=act

    def draw_bubbles(self, p, w, h, c):
        if len(self.parts)<40: self.parts.append([random.randint(0,int(w)), h, random.uniform(1,3), random.randint(3,10)])
        p.setBrush(QColor(c[0])); p.setPen(Qt.PenStyle.NoPen); act=[]
        for pt in self.parts:
            pt[1]-=pt[2]; xw=math.sin(self.ph+pt[1]*0.1)*3
            if self.phaser_mode == "converge": pt[0] += (w/2 - pt[0]) * 0.01
            if pt[1]>-20: p.drawEllipse(QPointF(pt[0]+xw, pt[1]), pt[3], pt[3]); act.append(pt)
        self.parts=act

    def draw_starfield(self, p, w, h, c):
        cx,cy=w/2,h/2;
        if len(self.parts)<100: self.parts.append([random.uniform(0,6.28), random.uniform(10,50)])
        p.setPen(QColor(c[0])); act=[]
        for pt in self.parts:
            pt[1]*=1.05+self.bl*0.1; r = pt[1] if self.phaser_mode != "converge" else (200 - pt[1])
            x=cx+math.cos(pt[0])*r; y=cy+math.sin(pt[0])*r
            if 0<x<w and 0<y<h and r > 0: p.drawEllipse(QPointF(x,y), 2, 2); act.append(pt)
        self.parts=act

    def draw_pulse_orb(self, p, w, h, c):
        cx,cy=w/2,h/2; r=50+self.bl*150;
        if self.phaser_mode == "rise": cx += math.sin(self.ph)*50
        rd=QRadialGradient(cx,cy,r*1.5); C1=QColor(c[1]); C1.setAlpha(0); C2=QColor(c[0]); C2.setAlpha(120)
        rd.setColorAt(0,C1); rd.setColorAt(0.5,C2); rd.setColorAt(1,C1)
        p.setBrush(rd); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(QPointF(cx,cy),r*1.5,r*1.5); p.setBrush(QColor(c[0])); p.drawEllipse(QPointF(cx,cy),r*0.5,r*0.5)

    def draw_sb(self, p, w, h):
        sw=int(w*0.28); sx=w-sw; sy=h//3; p.fillRect(sx,0,sw,h,QColor(0,0,0,120)); p.setPen(QColor(255,255,255,30)); p.drawLine(sx,0,sx,h)
        self.d_itm(p,self.dp,QRect(sx,0,sw,sy),0.5,"PREV"); rc=QRect(sx,sy,sw,sy); p.fillRect(rc,QColor(255,255,255,10)); self.d_itm(p,self.dc,rc,1.0,"PLAYING")
        self.d_itm(p,self.dn,QRect(sx,sy*2,sw,h-sy*2),0.5,"NEXT")
    def d_itm(self, p, d, r, o, l):
        px,t,a=d; p.setOpacity(o); m=15; ir=r.adjusted(m,m,-m,-m-40); tr=QRect(r.left()+m, ir.bottom()+5, r.width()-2*m, 40)
        if px: s=px.scaled(ir.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation); cx=ir.left()+(ir.width()-s.width())//2; cy=ir.top()+(ir.height()-s.height())//2; p.drawPixmap(cx,cy,s); p.setPen(QColor(255,255,255,80)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(cx,cy,s.width(),s.height())
        else: p.setPen(QColor(255,255,255,30)); p.drawRect(ir); p.drawText(ir,Qt.AlignmentFlag.AlignCenter,l)
        p.setPen(QColor(255,255,255,255 if o==1 else 150)); f=p.font(); f.setBold(True); p.setFont(f); fm=QFontMetrics(f)
        p.drawText(tr.left(),tr.top()+15, fm.elidedText(t,Qt.TextElideMode.ElideRight,tr.width())); f.setBold(False); f.setPointSize(f.pointSize()-1); p.setFont(f)
        p.drawText(tr.left(),tr.top()+30, fm.elidedText(a,Qt.TextElideMode.ElideRight,tr.width())); p.setOpacity(1.0); f.setPointSize(f.pointSize()+1); p.setFont(f)
    def resizeEvent(self, e):
        if self.dc[0]: self.bg = blur_pixmap(self.dc[0], self.size())
        super().resizeEvent(e)

# ============================================================================
# MAIN
# ============================================================================
class CarbonPhaserPlayer(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Carbon Player v14 (AnaMod ATS-1 Edition)")
        self.resize(1200, 980); self.setStyleSheet("QMainWindow{background:#121214}QWidget{color:#DDD;font-family:'Segoe UI'}QListWidget{background:#18181C;border:none}QListWidget::item:selected{background:#0088CC}QPushButton{background:#2A2A30;border:1px solid #3A3A40;padding:5px;border-radius:4px}QPushButton:hover{border-color:#00AAAA}QComboBox{background:#2A2A30;color:#EEE;border:1px solid #333}")
        self.pl=[]; self.idx=-1; self.play=False; self.pipeline_bin = None
        Gst.init(None); self.gst_init() # Init GST first to have pipeline ready
        self.setup();
        self.tm=QTimer(); self.tm.timeout.connect(self.poll); self.tm.start(50)

    def setup(self):
        c=QWidget(); self.setCentralWidget(c); m=QHBoxLayout(c); m.setContentsMargins(0,0,0,0); m.setSpacing(0)

        lp=QFrame(); lp.setFixedWidth(280); lp.setStyleSheet("background:#18181C;border-right:1px solid #222"); ll=QVBoxLayout(lp)
        ll.addWidget(QLabel("LIBRARY")); self.ls=QListWidget(); self.ls.itemDoubleClicked.connect(self.dbl); ll.addWidget(self.ls)

        bh=QHBoxLayout()
        ba=QPushButton("Add"); ba.clicked.connect(self.add)
        br=QPushButton("Radio"); br.clicked.connect(self.search_radio)
        bm=QPushButton("M3U"); bm.clicked.connect(self.load_m3u)
        bc=QPushButton("Clear"); bc.clicked.connect(self.clr)
        bh.addWidget(ba); bh.addWidget(br); bh.addWidget(bm); bh.addWidget(bc); ll.addLayout(bh); m.addWidget(lp)

        # Auto-load channels.m3u if it exists in the same directory
        self.auto_load_m3u()

        rp=QWidget(); rl=QVBoxLayout(rp); rl.setContentsMargins(0,0,0,0)
        
        # Stacked widget for visualizer and video player
        self.display_stack = QStackedWidget()
        self.display_stack.setStyleSheet("background: #000;")
        
        # Page 0: Visualizer
        vc=QWidget(); vl=QVBoxLayout(vc); vl.setContentsMargins(0,0,0,0); ph=QHBoxLayout(); ph.setContentsMargins(10,10,10,0)
        ph.addWidget(QLabel("PRESET:")); cb=QComboBox(); self.viz=MatrixVisualizer(); cb.addItems(list(self.viz.presets.keys())); cb.currentTextChanged.connect(self.viz.set_preset); ph.addWidget(cb); ph.addStretch(); vl.addLayout(ph); vl.addWidget(self.viz,1)
        
        # Page 1: Video Player
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background: #000;")
        self.video_player = QMediaPlayer()
        self.video_player.setVideoOutput(self.video_widget)
        
        # Add pages to stack
        self.display_stack.addWidget(vc)
        self.display_stack.addWidget(self.video_widget)
        self.display_stack.setCurrentIndex(0)  # Start with visualizer
        
        rl.addWidget(self.display_stack,1)

        self.eqw=EqualizerWidget();
        self.phaser = PhaserWidget(self.viz, self.eqw);

        # --- ADDING TAPE SIMULATOR ---
        self.tape_sim = AnalogTapeWidget(self.pipeline_bin)
        rl.addWidget(self.tape_sim)
        # -----------------------------

        rl.addWidget(self.phaser); rl.addWidget(self.eqw)

        ctrl=QFrame(); ctrl.setStyleSheet("background:#151518;border-top:1px solid #222"); cl=QVBoxLayout(ctrl)
        ih=QHBoxLayout(); self.lt=QLabel("Ready"); self.lm=QLabel("00:00"); self.lt.setStyleSheet("font-size:14px;font-weight:bold;color:white"); ih.addWidget(self.lt); ih.addStretch(); ih.addWidget(self.lm); cl.addLayout(ih)
        self.sk=QSlider(Qt.Orientation.Horizontal); self.sk.sliderReleased.connect(self.sk_r); cl.addWidget(self.sk)
        bh2=QHBoxLayout(); bp=QPushButton("Prev"); bp.clicked.connect(self.prev); self.bp=QPushButton("Play"); self.bp.clicked.connect(self.pp); bn=QPushButton("Next"); bn.clicked.connect(self.next); bh2.addWidget(bp); bh2.addWidget(self.bp); bh2.addWidget(bn); bh2.addStretch(); vsl=QSlider(Qt.Orientation.Horizontal); vsl.setRange(0,100); vsl.setValue(50); vsl.setFixedWidth(100); vsl.valueChanged.connect(self.vol); bh2.addWidget(QLabel("Vol")); bh2.addWidget(vsl); cl.addLayout(bh2); rl.addWidget(ctrl); m.addWidget(rp)

    def gst_init(self):
        self.ply=Gst.ElementFactory.make("playbin","p")
        self.pipeline_bin=Gst.Bin.new("a")

        # Elements for Tape Saturation Chain
        conv = Gst.ElementFactory.make("audioconvert","c")

        # 1. Tape Saturation (Compressor)
        tape_sat = Gst.ElementFactory.make("audiodynamic","tape_sat")
        tape_sat.set_property("characteristics", "soft-knee")
        tape_sat.set_property("mode", "compressor")

        # 2. Tape Gain (Makeup Gain - naprawa braku tej funkcji w audiodynamic)
        tape_gain = Gst.ElementFactory.make("volume", "tape_gain")

        # 3. Tape Tone (Analog Color)
        tape_tone = Gst.ElementFactory.make("equalizer-3bands", "tape_tone")

        # Main EQ
        self.eq=Gst.ElementFactory.make("equalizer-10bands","e")
        self.sp=Gst.ElementFactory.make("spectrum","s"); self.sp.set_property("bands",64); self.sp.set_property("threshold",-80); self.sp.set_property("post-messages",True); self.sp.set_property("message-magnitude",True)
        sink = Gst.ElementFactory.make("autoaudiosink","k")

        if self.eq:
            # Build Chain: Conv -> TapeSat -> TapeGain -> TapeTone -> MainEQ -> Spec -> Sink
            self.pipeline_bin.add(conv)
            self.pipeline_bin.add(tape_sat)
            self.pipeline_bin.add(tape_gain) # Dodajemy nowy element
            self.pipeline_bin.add(tape_tone)
            self.pipeline_bin.add(self.eq)
            self.pipeline_bin.add(self.sp)
            self.pipeline_bin.add(sink)

            conv.link(tape_sat)
            tape_sat.link(tape_gain) # Linkujemy
            tape_gain.link(tape_tone) # Linkujemy
            tape_tone.link(self.eq)
            self.eq.link(self.sp)
            self.sp.link(sink)

            if hasattr(self, 'eqw'): self.eqw.set_gst(self.eq)

        else:
            self.pipeline_bin.add(conv); self.pipeline_bin.add(self.sp); self.pipeline_bin.add(sink)
            conv.link(self.sp); self.sp.link(sink)

        pad = conv.get_static_pad("sink")
        ghost_pad = Gst.GhostPad.new("sink", pad)
        self.pipeline_bin.add_pad(ghost_pad)

        self.ply.set_property("audio-sink", self.pipeline_bin)
        self.bus=self.ply.get_bus()

    def poll(self):
        while True:
            m=self.bus.pop()
            if not m: break
            if m.type==Gst.MessageType.EOS: self.next()
            elif m.type==Gst.MessageType.ELEMENT:
                s=m.get_structure()
                if s and s.get_name()=="spectrum":
                    rm=[]
                    try: rm=s.get_value("magnitude")
                    except TypeError:
                        try:
                            match=re.search(r'magnitude=\(float\)\{\s*([^}]+)\s*\}', s.to_string())
                            if match: rm=[float(x.strip()) for x in match.group(1).split(',')]
                        except: pass
                    if rm:
                        d=[max(0,min(1,(x+80)/80)) for x in rm]
                        self.viz.update_data(d); self.eqw.proc.process(d)
        if self.play:
            _,p=self.ply.query_position(Gst.Format.TIME); _,d=self.ply.query_duration(Gst.Format.TIME)
            if p!=-1 and d!=-1:
                if not self.sk.isSliderDown(): self.sk.setRange(0,int(d/Gst.SECOND)); self.sk.setValue(int(p/Gst.SECOND))
                self.lm.setText(f"{p//Gst.SECOND//60:02}:{p//Gst.SECOND%60:02} / {d//Gst.SECOND//60:02}:{d//Gst.SECOND%60:02}")

    def search_radio(self):
        if not PYRADIOS_OK:
            QMessageBox.critical(self, "Error", "Library 'pyradios' not found.\nInstall: pip install pyradios")
            return
        
        dialog = RadioSearchDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            stations = dialog.get_selected_stations()
            if stations:
                for url, name in stations:
                    self.pl.append((url, name))
                    self.ls.addItem(name)
                
                # Auto-play first added station if nothing is playing
                if not self.play and self.idx == -1 and self.pl:
                    # Find the first added station (last N items)
                    first_new_idx = len(self.pl) - len(stations)
                    self.pl_t(first_new_idx)

    def auto_load_m3u(self):
        """Automatically load channels.m3u if it exists in the same directory as the script"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        m3u_path = os.path.join(script_dir, "channels.m3u")
        
        if os.path.exists(m3u_path):
            try:
                entries = parse_m3u(m3u_path)
                if entries:
                    for url, name in entries:
                        self.pl.append((url, name))
                        self.ls.addItem(name)
                    print(f"Auto-loaded {len(entries)} channels from channels.m3u")
                    # Don't auto-play, just load the channels
            except Exception as e:
                print(f"Auto-load M3U error: {e}")

    def up_m(self):
        if not self.pl: self.viz.set_covers_data((None,"",""),(None,"",""),(None,"","")); return
        l=len(self.pl); c=self.idx; g=lambda i: get_metadata(*self.pl[i])
        self.viz.set_covers_data(g((c-1)%l), g(c), g((c+1)%l))
    def pl_t(self,i): 
        self.idx=i
        uri = self.pl[i][0]
        
        # Check if it's a video stream (TV channels)
        is_video = "[TV]" in self.pl[i][1] or uri.startswith("http://") or uri.startswith("https://")
        
        if is_video and ("[TV]" in self.pl[i][1]):
            # Use video player for TV streams
            self.display_stack.setCurrentIndex(1)  # Switch to video
            self.video_player.setSource(QUrl(uri))
            self.video_player.play()
            
            # Also play audio through GStreamer (for spectrum)
            self.ply.set_state(Gst.State.NULL)
            self.ply.set_property("uri", uri)
            self.ply.set_state(Gst.State.PLAYING)
        else:
            # Use audio player and visualizer
            self.display_stack.setCurrentIndex(0)  # Switch to visualizer
            self.video_player.stop()
            
            self.ply.set_state(Gst.State.NULL)
            self.ply.set_property("uri", uri)
            self.ply.set_state(Gst.State.PLAYING)
        
        self.play=True
        self.bp.setText("Pause")
        self.lt.setText(self.pl[i][1])
        self.ls.setCurrentRow(i)
        self.up_m()
    def pp(self):
        if not self.pl: return
        if self.idx==-1: self.pl_t(0); return
        
        # Check if currently playing video
        is_video_mode = self.display_stack.currentIndex() == 1
        
        if self.play:
            self.ply.set_state(Gst.State.PAUSED)
            if is_video_mode:
                self.video_player.pause()
            self.play=False
            self.bp.setText("Play")
        else:
            self.ply.set_state(Gst.State.PLAYING)
            if is_video_mode:
                self.video_player.play()
            self.play=True
            self.bp.setText("Pause")
    def next(self): self.pl_t((self.idx+1)%len(self.pl)) if self.pl else None
    def prev(self): self.pl_t((self.idx-1)%len(self.pl)) if self.pl else None
    def load_m3u(self):
        """Load M3U playlist file"""
        m3u_file, _ = QFileDialog.getOpenFileName(self, "Open M3U Playlist", "", "M3U Playlist (*.m3u *.m3u8);;All Files (*.*)")
        if not m3u_file:
            return
        
        entries = parse_m3u(m3u_file)
        if not entries:
            QMessageBox.information(self, "Info", "No valid entries found in M3U file.")
            return
        
        # Add all entries to playlist
        for url, name in entries:
            self.pl.append((url, name))
            self.ls.addItem(name)
        
        QMessageBox.information(self, "Success", f"Loaded {len(entries)} channels from M3U playlist.")
        
        # Auto-play first track if nothing is playing
        if not self.play and self.idx == -1 and self.pl:
            self.pl_t(0)
    
    def add(self):
        f,_=QFileDialog.getOpenFileNames(self,"Add","","Audio/Playlist (*.mp3 *.flac *.m3u *.m3u8)")
        for p in f:
            # Check if it's an M3U file
            if p.lower().endswith(('.m3u', '.m3u8')):
                entries = parse_m3u(p)
                for url, name in entries:
                    self.pl.append((url, name))
                    self.ls.addItem(name)
            else:
                # Regular audio file
                self.pl.append(("file:///"+p.replace("\\","/"),os.path.basename(p)))
                self.ls.addItem(os.path.basename(p))
        if not self.play and self.idx==-1 and self.pl: self.pl_t(0)
    def clr(self): 
        self.ply.set_state(Gst.State.NULL)
        self.video_player.stop()
        self.display_stack.setCurrentIndex(0)  # Back to visualizer
        self.play=False
        self.pl=[]
        self.ls.clear()
        self.idx=-1
        self.up_m()
    def sk_r(self): self.ply.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH, self.sk.value()*Gst.SECOND)
    def vol(self,v): self.ply.set_property("volume",v/100.0)
    def dbl(self,i): self.pl_t(self.ls.row(i))

if __name__=="__main__": app=QApplication(sys.argv); app.setStyle("Fusion"); w=CarbonPhaserPlayer(); w.show(); sys.exit(app.exec())
