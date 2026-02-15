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
# VIRTUAL SINK MANAGEMENT (Monitor Mode)
# ============================================================================
VIRTUAL_SINK_NAME = "carbon_monitor"

def create_virtual_sink():
    """Create virtual null-sink for monitoring (like eq.py)"""
    import subprocess
    
    # Check if sink already exists
    try:
        result = subprocess.run(['pactl', 'list', 'sinks', 'short'], 
                              capture_output=True, text=True, check=True)
        if VIRTUAL_SINK_NAME in result.stdout:
            print(f"✓ Virtual sink '{VIRTUAL_SINK_NAME}' already exists")
            return True
    except:
        pass
    
    # Create null-sink
    try:
        subprocess.run(
            ['pactl', 'load-module', 'module-null-sink', 
             f'sink_name={VIRTUAL_SINK_NAME}',
             f'sink_properties=device.description="Carbon_Monitor"'],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        print(f"✓ Created virtual sink: {VIRTUAL_SINK_NAME}")
        print(f"📝 Use pavucontrol to redirect apps to '{VIRTUAL_SINK_NAME}'")
        return True
    except Exception as e:
        print(f"✗ Failed to create virtual sink: {e}")
        return False

def cleanup_virtual_sink():
    """Remove virtual sink on exit"""
    import subprocess
    try:
        result = subprocess.run(['pactl', 'list', 'modules', 'short'],
                              capture_output=True, text=True, check=True)
        for line in result.stdout.split('\n'):
            if VIRTUAL_SINK_NAME in line:
                module_id = line.split()[0]
                subprocess.run(['pactl', 'unload-module', module_id], check=True)
                print(f"✓ Removed virtual sink: {VIRTUAL_SINK_NAME}")
                break
    except:
        pass

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
# TAPE SPATIAL FX WIDGET (GStreamer Native!)
# ============================================================================
class TapeSpatialWidget(QGroupBox):
    """Tape Spatial FX using native GStreamer plugins"""
    
    def __init__(self, parent=None):
        super().__init__("🎚️ TAPE SPATIAL FX (GStreamer Native)", parent)
        self.pipeline = None
        self.stereo_width = None
        self.spatial_echo = None
        self.spatial_sat = None
        
        self.setStyleSheet("""
            QGroupBox {
                color: #00FFAA;
                border: 2px solid #00AAAA;
                border-radius: 6px;
                margin-top: 12px;
                font-weight: bold;
                font-size: 12px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0A0A0E, stop:1 #151518);
                padding-top: 12px;
            }
            QLabel {
                color: #999;
                font-size: 9px;
                font-weight: normal;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: #222;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #00FFAA;
                border: 1px solid #00AAAA;
                width: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            QCheckBox {
                color: #00FFAA;
                font-weight: bold;
                spacing: 4px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #00AAAA;
                border-radius: 3px;
                background: #1A1A1E;
            }
            QCheckBox::indicator:checked {
                background: #00AAAA;
            }
            QComboBox {
                background: #1A1A1E;
                color: #EEE;
                border: 1px solid #00AAAA;
                border-radius: 3px;
                padding: 3px;
                font-size: 10px;
            }
        """)
        
        self.init_ui()
    
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(8, 15, 8, 8)
        
        # Top controls
        top_layout = QHBoxLayout()
        self.enable_checkbox = QCheckBox("✓ ENABLE")
        self.enable_checkbox.setChecked(True)
        self.enable_checkbox.toggled.connect(self.on_enable_changed)
        top_layout.addWidget(self.enable_checkbox)
        
        top_layout.addStretch()
        top_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Flat", "Studio", "Wide", "Extreme"])
        self.preset_combo.currentTextChanged.connect(self.load_preset)
        top_layout.addWidget(self.preset_combo)
        
        main_layout.addLayout(top_layout)
        
        # Stereo Width
        width_h = QHBoxLayout()
        width_h.addWidget(QLabel("Stereo Width:"))
        self.width_slider = self.create_compact_slider(0, 100, 10)  # Default 10%
        self.width_slider.valueChanged.connect(self.on_width_changed)
        width_h.addWidget(self.width_slider)
        self.width_label = QLabel("10%")
        width_h.addWidget(self.width_label)
        main_layout.addLayout(width_h)
        
        # Haas Delay
        haas_h = QHBoxLayout()
        haas_h.addWidget(QLabel("Haas Delay:"))
        self.haas_slider = self.create_compact_slider(0, 50, 13)  # Default 13ms (~25%)
        self.haas_slider.valueChanged.connect(self.on_haas_changed)
        haas_h.addWidget(self.haas_slider)
        self.haas_label = QLabel("13ms")
        haas_h.addWidget(self.haas_label)
        main_layout.addLayout(haas_h)
        
        # Saturation
        sat_h = QHBoxLayout()
        sat_h.addWidget(QLabel("Extra Saturation:"))
        self.sat_slider = self.create_compact_slider(10, 100, 55)  # Default middle (5.5:1)
        self.sat_slider.valueChanged.connect(self.on_sat_changed)
        sat_h.addWidget(self.sat_slider)
        self.sat_label = QLabel("5.5:1")
        sat_h.addWidget(self.sat_label)
        main_layout.addLayout(sat_h)
        
        # Info
        info = QLabel("✨ Uses native GStreamer plugins (efficient!)")
        info.setStyleSheet("color: #00AAAA; font-size: 9px; font-style: italic;")
        main_layout.addWidget(info)
    
    def create_compact_slider(self, min_val, max_val, default):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_val, max_val)
        slider.setValue(default)
        slider.setFixedHeight(20)
        return slider
    
    def set_pipeline(self, stereo_width, spatial_echo, spatial_sat):
        """Set references to GStreamer elements"""
        self.stereo_width = stereo_width
        self.spatial_echo = spatial_echo
        self.spatial_sat = spatial_sat
        # Find parent player if not already set
        if not hasattr(self, 'parent_player') or not self.parent_player:
            self.parent_player = None
            p = self.parent()
            while p:
                if hasattr(p, '_monitor_stereo_width'):
                    self.parent_player = p
                    break
                p = p.parent()
        
        # Apply current UI values to the new pipeline elements
        if self.enable_checkbox.isChecked():
            self.on_width_changed(self.width_slider.value())
            self.on_haas_changed(self.haas_slider.value())
            self.on_sat_changed(self.sat_slider.value())
    
    def on_enable_changed(self, enabled):
        if not enabled:
            # Bypass all effects AND clear echo buffer to prevent crackling
            if hasattr(self, 'stereo_width') and self.stereo_width:
                self.stereo_width.set_property("stereo", 1.0)
            
            if hasattr(self, 'spatial_echo') and self.spatial_echo:
                # Clear echo buffer by resetting all properties
                self.spatial_echo.set_property("intensity", 0.0)  # 0.0 = bypass
                self.spatial_echo.set_property("feedback", 0.0)   # No feedback
                self.spatial_echo.set_property("delay", 1)        # Minimum delay
                
                # CRITICAL: Clear internal buffer by sending flush events
                # This prevents crackling from old buffer contents
                try:
                    # Get the element's sink pad and send flush events
                    sink_pad = self.spatial_echo.get_static_pad("sink")
                    if sink_pad:
                        sink_pad.send_event(Gst.Event.new_flush_start())
                        sink_pad.send_event(Gst.Event.new_flush_stop(True))
                except Exception as e:
                    print(f"Note: Could not flush echo buffer: {e}")
                    
            if hasattr(self, 'spatial_sat') and self.spatial_sat:
                self.spatial_sat.set_property("ratio", 1.0)
            
            # Also bypass monitoring pipeline with buffer clearing
            if hasattr(self, 'parent_player') and self.parent_player:
                if hasattr(self.parent_player, '_monitor_stereo_width') and self.parent_player._monitor_stereo_width:
                    self.parent_player._monitor_stereo_width.set_property("stereo", 1.0)
                    
                if hasattr(self.parent_player, '_monitor_spatial_echo') and self.parent_player._monitor_spatial_echo:
                    self.parent_player._monitor_spatial_echo.set_property("intensity", 0.0)
                    self.parent_player._monitor_spatial_echo.set_property("feedback", 0.0)
                    self.parent_player._monitor_spatial_echo.set_property("delay", 1)
                    
                    # Clear monitoring pipeline buffer too
                    try:
                        sink_pad = self.parent_player._monitor_spatial_echo.get_static_pad("sink")
                        if sink_pad:
                            sink_pad.send_event(Gst.Event.new_flush_start())
                            sink_pad.send_event(Gst.Event.new_flush_stop(True))
                    except:
                        pass
                        
                if hasattr(self.parent_player, '_monitor_spatial_sat') and self.parent_player._monitor_spatial_sat:
                    self.parent_player._monitor_spatial_sat.set_property("ratio", 1.0)
        else:
            # Apply current values
            self.on_width_changed(self.width_slider.value())
            self.on_haas_changed(self.haas_slider.value())
            self.on_sat_changed(self.sat_slider.value())
    
    def on_width_changed(self, value):
        if self.enable_checkbox.isChecked():
            width = value / 100.0  # 0.0 to 1.0 (0% to 100%)
            if hasattr(self, 'stereo_width') and self.stereo_width:
                self.stereo_width.set_property("stereo", width)
            # Update monitoring pipeline
            if hasattr(self, 'parent_player') and self.parent_player and hasattr(self.parent_player, '_monitor_stereo_width') and self.parent_player._monitor_stereo_width:
                self.parent_player._monitor_stereo_width.set_property("stereo", width)
            self.width_label.setText(f"{value}%")
    
    def on_haas_changed(self, value):
        if self.enable_checkbox.isChecked():
            # Convert ms to nanoseconds (minimum 1ns)
            delay_ns = max(1, value * 1000000)  # ms to ns, minimum 1
            # Intensity controls the effect strength (0.0 = bypass, even with delay set)
            intensity = 0.0 if value == 0 else 0.5
            
            if hasattr(self, 'spatial_echo') and self.spatial_echo:
                self.spatial_echo.set_property("delay", delay_ns)
                self.spatial_echo.set_property("intensity", intensity)
            # Update monitoring pipeline
            if hasattr(self, 'parent_player') and self.parent_player and hasattr(self.parent_player, '_monitor_spatial_echo') and self.parent_player._monitor_spatial_echo:
                self.parent_player._monitor_spatial_echo.set_property("delay", delay_ns)
                self.parent_player._monitor_spatial_echo.set_property("intensity", intensity)
            self.haas_label.setText(f"{value}ms")
    
    def on_sat_changed(self, value):
        if self.enable_checkbox.isChecked():
            # Ratio: 1.0 = no compression, higher = more compression/saturation
            ratio = value / 10.0  # 1.0 to 10.0
            if hasattr(self, 'spatial_sat') and self.spatial_sat:
                self.spatial_sat.set_property("ratio", ratio)
                self.spatial_sat.set_property("threshold", 0.8)  # 0.0-1.0 range, 0.8 = moderate threshold
            # Update monitoring pipeline
            if hasattr(self, 'parent_player') and self.parent_player and hasattr(self.parent_player, '_monitor_spatial_sat') and self.parent_player._monitor_spatial_sat:
                self.parent_player._monitor_spatial_sat.set_property("ratio", ratio)
                self.parent_player._monitor_spatial_sat.set_property("threshold", 0.8)
            self.sat_label.setText(f"{ratio:.1f}:1")
    
    def load_preset(self, preset_name):
        presets = {
            "Flat": {'width': 10, 'haas': 0, 'sat': 10},
            "Studio": {'width': 10, 'haas': 15, 'sat': 20},
            "Wide": {'width': 10, 'haas': 25, 'sat': 30},
            "Extreme": {'width': 10, 'haas': 40, 'sat': 50}
        }
        
        if preset_name in presets:
            p = presets[preset_name]
            self.width_slider.setValue(p['width'])
            self.haas_slider.setValue(p['haas'])
            self.sat_slider.setValue(p['sat'])


class AnalogTapeWidget(QGroupBox):
    def __init__(self, gst_pipeline, parent=None):
        super().__init__("ATS-1 Tape Simulation", parent)
        self.pipe = gst_pipeline
        # References for direct element access
        self.tape_sat = None
        self.tape_gain = None
        self.tape_tone = None
        # Monitoring pipeline references
        self.monitor_tape_sat = None
        self.monitor_tape_gain = None
        self.monitor_tape_tone = None
        # Store dials for later initialization
        self._dials = []
        
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

    def set_pipeline(self, tape_sat, tape_gain, tape_tone):
        """Set direct references to GStreamer elements"""
        self.tape_sat = tape_sat
        self.tape_gain = tape_gain
        self.tape_tone = tape_tone
        
        # Debug output
        if tape_sat and tape_gain and tape_tone:
            print(f"✓ Tape Saturation widget connected to GStreamer elements")
        else:
            print(f"⚠ Tape Saturation widget: Missing elements - sat:{tape_sat} gain:{tape_gain} tone:{tape_tone}")
        
        # Find monitoring pipeline references from parent
        p = self.parent()
        while p:
            if hasattr(p, '_monitor_tape_sat'):
                self.monitor_tape_sat = p._monitor_tape_sat
                self.monitor_tape_gain = p._monitor_tape_gain
                self.monitor_tape_tone = p._monitor_tape_tone
                print(f"✓ Tape Saturation widget found monitoring pipeline elements")
                break
            p = p.parent()
        
        # NOW apply initial dial values (after elements are connected)
        if self.bypass_btn.isChecked() and self._dials:
            print(f"🎛️ Applying initial Tape values...")
            for dial, func in self._dials:
                func(dial.value())

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
        # Store dial reference for later initialization
        self._dials.append((d, func))

    def toggle_bypass(self, state):
        if not state:
            # RESET DO FLAT (BYPASS)
            # Main pipeline
            if self.tape_sat:
                self.tape_sat.set_property("ratio", 1.0)  # No compression
                self.tape_sat.set_property("threshold", 1.0)  # High threshold = no effect
            if self.tape_gain:
                self.tape_gain.set_property("volume", 1.0)  # Unity gain
            if self.tape_tone:
                self.tape_tone.set_property("band0", 0.0)  # Flat bass
                self.tape_tone.set_property("band2", 0.0)  # Flat treble
            
            # Monitoring pipeline
            if self.monitor_tape_sat:
                self.monitor_tape_sat.set_property("ratio", 1.0)
                self.monitor_tape_sat.set_property("threshold", 1.0)
            if self.monitor_tape_gain:
                self.monitor_tape_gain.set_property("volume", 1.0)
            if self.monitor_tape_tone:
                self.monitor_tape_tone.set_property("band0", 0.0)
                self.monitor_tape_tone.set_property("band2", 0.0)
            
            self.bypass_btn.setText("BYPASS")
        else:
            self.bypass_btn.setText("ACTIVE")
            # Re-apply current knob values when re-enabled
            # (knobs will trigger their callbacks on next adjustment)

    def set_drive(self, v):
        # DRIVE: Obniżamy próg (threshold) i podnosimy gain (makeup)
        if not self.bypass_btn.isChecked(): return

        # 1. Threshold (kompresor): 0.0 do 1.0.
        # Duży Drive = Mały Threshold (mocna kompresja sygnału)
        # Mapujemy 0-100 na zakres 0.9 do 0.1
        thresh = 0.9 - (v / 100.0 * 0.8)

        # 2. Makeup Gain (nowy element tape_gain)
        # Mapujemy 0-100 na głośność 1.0x do 1.8x
        gain = 1.0 + (v / 100.0 * 0.8)

        print(f"🎛️ Tape Drive: {v} → threshold={thresh:.2f}, gain={gain:.2f}x")

        # Main pipeline
        if self.tape_sat:
            self.tape_sat.set_property("threshold", float(thresh))
        else:
            print("⚠ Main tape_sat is None!")
            
        if self.tape_gain:
            self.tape_gain.set_property("volume", float(gain))
        else:
            print("⚠ Main tape_gain is None!")
        
        # Monitoring pipeline
        if self.monitor_tape_sat:
            self.monitor_tape_sat.set_property("threshold", float(thresh))
        if self.monitor_tape_gain:
            self.monitor_tape_gain.set_property("volume", float(gain))

    def set_comp(self, v):
        if not self.bypass_btn.isChecked(): return
        
        # Ratio: 1.0 (brak) do 8.0 (mocna)
        ratio = 1.0 + (v / 100.0 * 7.0)
        
        # Main pipeline
        if self.tape_sat:
            self.tape_sat.set_property("ratio", float(ratio))
        
        # Monitoring pipeline
        if self.monitor_tape_sat:
            self.monitor_tape_sat.set_property("ratio", float(ratio))

    def set_warmth(self, v):
        if not self.bypass_btn.isChecked(): return
        
        high_cut = -(v / 100.0 * 8.0)  # Tnie górę do -8dB
        low_boost = (v / 100.0 * 5.0)  # Podbija dół do +5dB
        
        # Main pipeline
        if self.tape_tone:
            self.tape_tone.set_property("band0", float(low_boost))
            self.tape_tone.set_property("band2", float(high_cut))
        
        # Monitoring pipeline
        if self.monitor_tape_tone:
            self.monitor_tape_tone.set_property("band0", float(low_boost))
            self.monitor_tape_tone.set_property("band2", float(high_cut))


# ⚠️ NOTE: TapeSpatialWidget is currently UI-only and doesn't process audio in real-time
# To actually hear the effects, they need to be integrated into the GStreamer pipeline
# with custom audio processing elements or appsink/appsrc callback processing.
# This would require significant GStreamer pipeline modifications.


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
        self.exposure_mode = "Flat" # Nowe pole: "Dół", "Środek", "Góra"
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

                exp_offset = 0.0
                if self.exposure_mode == "Góra":
                    # Wzmacnia liniowo od basu do góry (od -3dB do +5dB)
                    exp_offset = -3.0 + (i * 0.8)
                elif self.exposure_mode == "Dół":
                    # Wzmacnia dół, tnie górę
                    exp_offset = 5.0 - (i * 0.8)
                elif self.exposure_mode == "Środek":
                    # Bell curve skupiony na środku (pasmach 4-6)
                    exp_offset = 5.0 - abs(4.5 - i) * 1.5

                dc = 0.0
                if self.active:
                    s = i*chunk; ea = sum(spec[s:s+chunk])/chunk if chunk else 0
                    dc = (self.tgt[i] - ea) * 20.0 * self.depth

            # Sumujemy bazę + geometrię + DYNAMICZNE + NOWĄ EKSPOZYCJĘ
            des = max(-12.0, min(12.0, self.base[i] + gm + dc + exp_offset))
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

        # 1. NAJPIERW tworzymy układ poziomy (pl)
        pl = QHBoxLayout()

        # 2. DODAJEMY elementy do układu (w tym nowy ComboBox EXP)
        self.chk = QCheckBox("⚡ DYNAMIC"); self.chk.toggled.connect(self.tog_dyn)
        self.chk_g = QCheckBox("🌊 PHASE"); self.chk_g.setChecked(True); self.chk_g.toggled.connect(self.tog_geo)

        self.exp_cb = QComboBox()
        self.exp_cb.addItems(["Flat", "Dół", "Środek", "Góra"])
        self.exp_cb.setToolTip("Typ ekspozycji (Kompensacja kolumn)")
        self.exp_cb.currentTextChanged.connect(self.change_exposure)

        self.cb = QComboBox()
        self.cb.addItems(list(EQ_PRESETS.keys()))
        self.cb.currentTextChanged.connect(self.app_pre)

        # Układamy w linii: Dynamic, Phase, Stretch (odstęp), Label EXP, Combo EXP, Presety
        pl.addWidget(self.chk)
        pl.addWidget(self.chk_g)
        pl.addStretch()
        pl.addWidget(QLabel("EXP:"))
        pl.addWidget(self.exp_cb)
        pl.addWidget(self.cb)

        # 3. DODAJEMY układ do głównego layoutu (m)
        m.addLayout(pl)

        # Sekcja suwaków (bez zmian)
        bl = QHBoxLayout(); bl.setSpacing(2)
        fr = ["32","64","125","250","500","1k","2k","4k","8k","16k"]
        for i, f in enumerate(fr):
            v = QVBoxLayout(); s = QSlider(Qt.Orientation.Vertical); s.setRange(-12,12); s.setValue(0)
            s.valueChanged.connect(lambda v, x=i: self.usr_chg(x,v)); self.sl.append(s)
            v.addWidget(s,1,Qt.AlignmentFlag.AlignHCenter); v.addWidget(QLabel(f),0,Qt.AlignmentFlag.AlignHCenter); bl.addLayout(v)
        m.addLayout(bl)

    def change_exposure(self, val):
        self.proc.exposure_mode = val
    def set_gst(self, el): 
        self.gst = el
        # Store reference to parent for monitoring pipeline access
        self.parent_player = None
        p = self.parent()
        while p:
            if hasattr(p, '_monitor_eq'):
                self.parent_player = p
                break
            p = p.parent()
    
    def usr_chg(self, i, v):
        if not self.prog_upd: self.proc.set_base(i, v); self.set_b(i, v)
    def update_vis(self, i, v): self.prog_upd = True; self.sl[i].setValue(int(v)); self.prog_upd = False; self.set_b(i, v)
    def set_b(self, i, v):
        # Update main pipeline EQ
        if self.gst: 
            self.gst.set_property(f"band{i}", float(v))
        # Update monitoring pipeline EQ if active
        if self.parent_player and hasattr(self.parent_player, '_monitor_eq') and self.parent_player._monitor_eq:
            self.parent_player._monitor_eq.set_property(f"band{i}", float(v))
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


    def closeEvent(self, event):
        """Cleanup on exit"""
        if hasattr(self, '_monitor_pipeline') and self._monitor_pipeline:
            self._monitor_pipeline.set_state(Gst.State.NULL)
        cleanup_virtual_sink()
        super().closeEvent(event)

    def setup(self):
        c=QWidget(); self.setCentralWidget(c); m=QHBoxLayout(c); m.setContentsMargins(0,0,0,0); m.setSpacing(0)

        lp=QFrame(); lp.setFixedWidth(280); lp.setStyleSheet("background:#18181C;border-right:1px solid #222"); ll=QVBoxLayout(lp)
        ll.addWidget(QLabel("LIBRARY")); self.ls=QListWidget(); self.ls.itemDoubleClicked.connect(self.dbl); ll.addWidget(self.ls)

        bh=QHBoxLayout()
        ba=QPushButton("Add"); ba.clicked.connect(self.add)
        br=QPushButton("Radio"); br.clicked.connect(self.search_radio)
        bm=QPushButton("M3U"); bm.clicked.connect(self.load_m3u)
        bc=QPushButton("Clear"); bc.clicked.connect(self.clr)
        bmon=QPushButton("Monitor"); bmon.clicked.connect(self.start_monitor)
        bh.addWidget(ba); bh.addWidget(br); bh.addWidget(bm); bh.addWidget(bc); bh.addWidget(bmon); ll.addLayout(bh); m.addWidget(lp)

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
        
        # --- TAPE SPATIAL FX (GStreamer Native!) ---
        self.tape_spatial = TapeSpatialWidget()
        self.tape_spatial.parent_player = self  # Allow widget to access monitoring pipeline
        rl.addWidget(self.tape_spatial)
        
        # --- TAPE SPATIAL FX ---
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

        # Elements for audio chain
        conv = Gst.ElementFactory.make("audioconvert","c")

        # 1. Tape Saturation (Compressor)
        tape_sat = Gst.ElementFactory.make("audiodynamic","tape_sat")
        tape_sat.set_property("characteristics", "soft-knee")
        tape_sat.set_property("mode", "compressor")

        # 2. Tape Gain (Makeup Gain)
        tape_gain = Gst.ElementFactory.make("volume", "tape_gain")

        # 3. Tape Tone (Analog Color)
        tape_tone = Gst.ElementFactory.make("equalizer-3bands", "tape_tone")

        # Main EQ
        self.eq=Gst.ElementFactory.make("equalizer-10bands","e")
        
        # Spectrum analyzer
        self.sp=Gst.ElementFactory.make("spectrum","s")
        self.sp.set_property("bands",64)
        self.sp.set_property("threshold",-80)
        self.sp.set_property("post-messages",True)
        self.sp.set_property("message-magnitude",True)
        
        sink = Gst.ElementFactory.make("autoaudiosink","k")

        # SPATIAL FX ELEMENTS (GStreamer native!)
        # 1. Stereo widening
        self.stereo_width = Gst.ElementFactory.make("stereo", "stereo_width")
        if self.stereo_width:
            self.stereo_width.set_property("stereo", 1.0)  # 0.0 = mono, 1.0 = normal, 2.0 = wide
        
        # 2. Audio echo for Haas effect
        self.spatial_echo = Gst.ElementFactory.make("audioecho", "spatial_echo")
        if self.spatial_echo:
            self.spatial_echo.set_property("delay", 1)  # nanoseconds, 1 = bypass (0 is invalid)
            self.spatial_echo.set_property("intensity", 0.0)  # 0.0 = bypass
            self.spatial_echo.set_property("feedback", 0.0)
        
        # 3. Extra saturation (in addition to tape_sat)
        self.spatial_sat = Gst.ElementFactory.make("audiodynamic", "spatial_sat")
        if self.spatial_sat:
            self.spatial_sat.set_property("characteristics", "hard-knee")
            self.spatial_sat.set_property("mode", "compressor")
            self.spatial_sat.set_property("threshold", 0.0)
            self.spatial_sat.set_property("ratio", 1.0)  # 1.0 = bypass
        
        # Store tape elements as instance variables for monitoring
        self.tape_sat = tape_sat
        self.tape_gain = tape_gain
        self.tape_tone = tape_tone

        if self.eq:
            # Enhanced chain: Conv -> TapeSat -> TapeGain -> TapeTone -> EQ -> 
            #                 SpatialSat -> StereoWidth -> SpatialEcho -> Spec -> Sink
            self.pipeline_bin.add(conv)
            self.pipeline_bin.add(tape_sat)
            self.pipeline_bin.add(tape_gain)
            self.pipeline_bin.add(tape_tone)
            self.pipeline_bin.add(self.eq)
            
            if self.spatial_sat:
                self.pipeline_bin.add(self.spatial_sat)
            if self.stereo_width:
                self.pipeline_bin.add(self.stereo_width)
            if self.spatial_echo:
                self.pipeline_bin.add(self.spatial_echo)
                
            self.pipeline_bin.add(self.sp)
            self.pipeline_bin.add(sink)

            # Link chain
            conv.link(tape_sat)
            tape_sat.link(tape_gain)
            tape_gain.link(tape_tone)
            tape_tone.link(self.eq)
            
            last_element = self.eq
            
            if self.spatial_sat:
                last_element.link(self.spatial_sat)
                last_element = self.spatial_sat
            
            if self.stereo_width:
                last_element.link(self.stereo_width)
                last_element = self.stereo_width
                
            if self.spatial_echo:
                last_element.link(self.spatial_echo)
                last_element = self.spatial_echo
            
            last_element.link(self.sp)
            self.sp.link(sink)

            if hasattr(self, 'eqw'): self.eqw.set_gst(self.eq)

        else:
            self.pipeline_bin.add(conv)
            self.pipeline_bin.add(self.sp)
            self.pipeline_bin.add(sink)
            conv.link(self.sp)
            self.sp.link(sink)

        pad = conv.get_static_pad("sink")
        ghost_pad = Gst.GhostPad.new("sink", pad)
        self.pipeline_bin.add_pad(ghost_pad)

        self.ply.set_property("audio-sink", self.pipeline_bin)
        self.bus=self.ply.get_bus()
        
        # Connect Tape Spatial FX widget to pipeline elements
        if hasattr(self, 'tape_spatial'):
            self.tape_spatial.set_pipeline(
                self.stereo_width if hasattr(self, 'stereo_width') else None,
                self.spatial_echo if hasattr(self, 'spatial_echo') else None,
                self.spatial_sat if hasattr(self, 'spatial_sat') else None
            )
        
        # Connect Tape Saturation widget to pipeline elements
        if hasattr(self, 'tape_sim'):
            self.tape_sim.set_pipeline(
                self.tape_sat if hasattr(self, 'tape_sat') else None,
                self.tape_gain if hasattr(self, 'tape_gain') else None,
                self.tape_tone if hasattr(self, 'tape_tone') else None
            )

    def on_monitor_message(self, bus, message):
        """Handle messages from monitoring pipeline"""
        # Process spectrum messages directly
        if message.type == Gst.MessageType.ELEMENT:
            s = message.get_structure()
            if s and s.get_name() == "spectrum":
                rm = []
                try:
                    rm = s.get_value("magnitude")
                except TypeError:
                    try:
                        match = re.search(r'magnitude=\(float\)\{\s*([^}]+)\s*\}', s.to_string())
                        if match:
                            rm = [float(x.strip()) for x in match.group(1).split(',')]
                    except:
                        pass
                if rm:
                    d = [max(0, min(1, (x+80)/80)) for x in rm]
                    self.viz.update_data(d)
                    self.eqw.proc.process(d)



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


    def start_monitor(self):
        """Start monitoring the virtual sink (eq.py style)"""
        # Create virtual sink if it doesn't exist
        if not create_virtual_sink():
            QMessageBox.critical(
                self, 
                "Error",
                "Failed to create virtual sink!\n\n"
                "Make sure PulseAudio/PipeWire is running."
            )
            return
        
        # Show instructions
        QMessageBox.information(
            self,
            "Virtual Sink Created",
            f"✓ Virtual sink '{VIRTUAL_SINK_NAME}' is ready!\n\n"
            f"📝 NEXT STEPS:\n"
            f"1. Open pavucontrol (PulseAudio Volume Control)\n"
            f"2. Go to 'Playback' tab\n"
            f"3. Find your application (Firefox, Spotify, etc.)\n"
            f"4. Click dropdown and select 'Carbon_Monitor'\n\n"
            f"Carbon will now monitor this virtual sink automatically."
        )
        
        # Stop current playback
        if self.play:
            self.pp()
        
        # Add monitor to playlist
        monitor_uri = f"pulsesrc://{VIRTUAL_SINK_NAME}.monitor"
        display_name = f"[Monitor] {VIRTUAL_SINK_NAME}"
        
        self.pl.append((monitor_uri, display_name))
        self.ls.addItem(display_name)
        
        # Auto-play
        if len(self.pl) > 0:
            self.pl_t(len(self.pl) - 1)

    def up_m(self):
        if not self.pl: self.viz.set_covers_data((None,"",""),(None,"",""),(None,"","")); return
        l=len(self.pl); c=self.idx; g=lambda i: get_metadata(*self.pl[i])
        self.viz.set_covers_data(g((c-1)%l), g(c), g((c+1)%l))
    def pl_t(self,i): 
        self.idx=i
        uri = self.pl[i][0]
        
        # Handle PulseAudio monitoring
        if uri.startswith("pulsesrc://"):
            device = uri.replace("pulsesrc://", "")
            self.display_stack.setCurrentIndex(0)  # Use visualizer
            self.video_player.stop()
            
            # Stop playbin completely
            self.ply.set_state(Gst.State.NULL)
            # Give it a moment to actually stop
            self.ply.get_state(Gst.CLOCK_TIME_NONE)
            print("✓ Main playbin stopped")
            
            # Clean up old monitoring pipeline if it exists
            if hasattr(self, '_monitor_pipeline') and self._monitor_pipeline:
                print("🔄 Cleaning up old monitoring pipeline...")
                self._monitor_pipeline.set_state(Gst.State.NULL)
                self._monitor_pipeline.get_state(Gst.CLOCK_TIME_NONE)
                self._monitor_pipeline = None
            
            # Always create fresh monitoring pipeline
            print(f"🎤 Creating fresh monitoring pipeline for: {device}")
            
            # Create new pipeline for monitoring
            self._monitor_pipeline = Gst.Pipeline.new("monitor-pipeline")
            
            # Source: PulseAudio monitor
            monitor_src = Gst.ElementFactory.make("pulsesrc", "monitor-src")
            if not monitor_src:
                print("❌ Failed to create pulsesrc element")
                return
            monitor_src.set_property("device", device)
            
            # Audio processing chain (same as main pipeline)
            audioconvert = Gst.ElementFactory.make("audioconvert", "mon-convert")
            if not audioconvert:
                print("❌ Failed to create audioconvert element")
                return
                
            audioresample = Gst.ElementFactory.make("audioresample", "mon-resample")
            if not audioresample:
                print("❌ Failed to create audioresample element")
                return
            
            # Tape effects chain
            tape_sat = Gst.ElementFactory.make("audiodynamic", "mon-tape-sat")
            tape_sat.set_property("characteristics", "soft-knee")
            tape_sat.set_property("mode", "compressor")
            
            tape_gain = Gst.ElementFactory.make("volume", "mon-tape-gain")
            
            tape_tone = Gst.ElementFactory.make("equalizer-3bands", "mon-tape-tone")
            
            # Main EQ (copy settings from self.eq if available)
            monitor_eq = Gst.ElementFactory.make("equalizer-10bands", "mon-eq")
            if self.eq:
                # Copy EQ band settings
                for i in range(10):
                    gain = self.eq.get_property(f"band{i}")
                    monitor_eq.set_property(f"band{i}", gain)
            
            # Spatial FX
            monitor_spatial_sat = Gst.ElementFactory.make("audiodynamic", "mon-spatial-sat")
            monitor_spatial_sat.set_property("characteristics", "hard-knee")
            monitor_spatial_sat.set_property("mode", "compressor")
            # Copy current values from main pipeline
            if self.spatial_sat:
                monitor_spatial_sat.set_property("threshold", self.spatial_sat.get_property("threshold"))
                monitor_spatial_sat.set_property("ratio", self.spatial_sat.get_property("ratio"))
            else:
                monitor_spatial_sat.set_property("threshold", 0.0)
                monitor_spatial_sat.set_property("ratio", 1.0)
            
            monitor_stereo_width = Gst.ElementFactory.make("stereo", "mon-stereo-width")
            # Copy current value from main pipeline
            if self.stereo_width:
                monitor_stereo_width.set_property("stereo", self.stereo_width.get_property("stereo"))
            else:
                monitor_stereo_width.set_property("stereo", 1.0)
            
            monitor_spatial_echo = Gst.ElementFactory.make("audioecho", "mon-spatial-echo")
            # Copy current values from main pipeline
            if self.spatial_echo:
                monitor_spatial_echo.set_property("delay", max(1, self.spatial_echo.get_property("delay")))
                monitor_spatial_echo.set_property("intensity", self.spatial_echo.get_property("intensity"))
                monitor_spatial_echo.set_property("feedback", self.spatial_echo.get_property("feedback"))
            else:
                monitor_spatial_echo.set_property("delay", 1)  # 1ns minimum
                monitor_spatial_echo.set_property("intensity", 0.0)  # 0.0 = bypass
                monitor_spatial_echo.set_property("feedback", 0.0)
            
            # Store references for UI control
            self._monitor_eq = monitor_eq
            self._monitor_spatial_sat = monitor_spatial_sat
            self._monitor_stereo_width = monitor_stereo_width
            self._monitor_spatial_echo = monitor_spatial_echo
            self._monitor_tape_sat = tape_sat
            self._monitor_tape_gain = tape_gain
            self._monitor_tape_tone = tape_tone
            
            # Spectrum for visualization
            spectrum = Gst.ElementFactory.make("spectrum", "mon-spectrum")
            spectrum.set_property("bands", 64)
            spectrum.set_property("threshold", -80)
            spectrum.set_property("post-messages", True)
            spectrum.set_property("message-magnitude", True)
            
            # Audio converts for format compatibility between effects
            audioconvert_spatial1 = Gst.ElementFactory.make("audioconvert", "mon-conv-spatial1")
            audioconvert_spatial2 = Gst.ElementFactory.make("audioconvert", "mon-conv-spatial2")
            audioconvert_spatial3 = Gst.ElementFactory.make("audioconvert", "mon-conv-spatial3")
            
            # Audio convert after spectrum for compatibility
            audioconvert2 = Gst.ElementFactory.make("audioconvert", "mon-convert2")
            
            # Audio sink for output
            audio_sink = Gst.ElementFactory.make("autoaudiosink", "mon-audio-output")
            
            # Add all elements to pipeline
            self._monitor_pipeline.add(monitor_src)
            self._monitor_pipeline.add(audioconvert)
            self._monitor_pipeline.add(audioresample)
            self._monitor_pipeline.add(tape_sat)
            self._monitor_pipeline.add(tape_gain)
            self._monitor_pipeline.add(tape_tone)
            self._monitor_pipeline.add(monitor_eq)
            self._monitor_pipeline.add(monitor_spatial_sat)
            self._monitor_pipeline.add(audioconvert_spatial1)
            self._monitor_pipeline.add(monitor_stereo_width)
            self._monitor_pipeline.add(audioconvert_spatial2)
            self._monitor_pipeline.add(monitor_spatial_echo)
            self._monitor_pipeline.add(audioconvert_spatial3)
            self._monitor_pipeline.add(spectrum)
            self._monitor_pipeline.add(audioconvert2)
            self._monitor_pipeline.add(audio_sink)
            
            # Link complete chain:
            # monitor_src -> audioconvert -> audioresample -> 
            # tape_sat -> tape_gain -> tape_tone -> eq -> 
            # spatial_sat -> conv_spatial1 -> stereo_width -> conv_spatial2 ->
            # spatial_echo -> conv_spatial3 -> spectrum -> audioconvert2 -> audio_sink
            
            if not monitor_src.link(audioconvert):
                print("❌ Failed to link monitor source to audioconvert")
                return
            if not audioconvert.link(audioresample):
                print("❌ Failed to link audioconvert to audioresample")
                return
            if not audioresample.link(tape_sat):
                print("❌ Failed to link audioresample to tape_sat")
                return
            if not tape_sat.link(tape_gain):
                print("❌ Failed to link tape_sat to tape_gain")
                return
            if not tape_gain.link(tape_tone):
                print("❌ Failed to link tape_gain to tape_tone")
                return
            if not tape_tone.link(monitor_eq):
                print("❌ Failed to link tape_tone to eq")
                return
            if not monitor_eq.link(monitor_spatial_sat):
                print("❌ Failed to link eq to spatial_sat")
                return
            if not monitor_spatial_sat.link(audioconvert_spatial1):
                print("❌ Failed to link spatial_sat to audioconvert_spatial1")
                return
            if not audioconvert_spatial1.link(monitor_stereo_width):
                print("❌ Failed to link audioconvert_spatial1 to stereo_width")
                return
            if not monitor_stereo_width.link(audioconvert_spatial2):
                print("❌ Failed to link stereo_width to audioconvert_spatial2")
                return
            if not audioconvert_spatial2.link(monitor_spatial_echo):
                print("❌ Failed to link audioconvert_spatial2 to spatial_echo")
                return
            if not monitor_spatial_echo.link(audioconvert_spatial3):
                print("❌ Failed to link spatial_echo to audioconvert_spatial3")
                return
            if not audioconvert_spatial3.link(spectrum):
                print("❌ Failed to link audioconvert_spatial3 to spectrum")
                return
            if not spectrum.link(audioconvert2):
                print("❌ Failed to link spectrum to audioconvert2")
                return
            if not audioconvert2.link(audio_sink):
                print("❌ Failed to link audioconvert2 to audio sink")
                return
            
            print("✓ All elements linked successfully")
            print(f"✓ Pipeline chain created:")
            print(f"  monitor_src -> audioconvert -> audioresample -> tape_sat ->")
            print(f"  tape_gain -> tape_tone -> EQ -> spatial_sat -> conv1 ->")
            print(f"  stereo -> conv2 -> spatial_echo -> conv3 ->")
            print(f"  spectrum -> audioconvert2 -> audio_sink")
            
            # Test: Set to READY first
            ret = self._monitor_pipeline.set_state(Gst.State.READY)
            if ret == Gst.StateChangeReturn.FAILURE:
                print("❌ Failed to set monitoring pipeline to READY state")
                return
            print("✓ Pipeline set to READY state")
            
            print("✓ Monitoring pipeline with full FX chain created successfully")
            
            # Connect UI controls to monitor pipeline elements
            if hasattr(self, 'eqw'):
                self.eqw.set_gst(monitor_eq)
            if hasattr(self, 'tape_sim'):
                self.tape_sim.set_pipeline(tape_sat, tape_gain, tape_tone)
            if hasattr(self, 'tape_spatial'):
                self.tape_spatial.set_pipeline(monitor_stereo_width, monitor_spatial_echo, monitor_spatial_sat)
            
            # Connect to bus for spectrum messages
            monitor_bus = self._monitor_pipeline.get_bus()
            monitor_bus.add_signal_watch()
            monitor_bus.connect("message", self.on_monitor_message)
            
            # Start monitoring
            self._monitor_pipeline.set_state(Gst.State.PLAYING)
            self.play = True
            self.bp.setText("Pause")
            self.lt.setText(f"🎤 {self.pl[i][1]}")
            self.up_m()
            return
        else:
            # Stop monitoring pipeline if active
            if hasattr(self, '_monitor_pipeline') and self._monitor_pipeline:
                print("🔄 Stopping monitoring pipeline...")
                self._monitor_pipeline.set_state(Gst.State.NULL)
                self._monitor_pipeline.get_state(Gst.CLOCK_TIME_NONE)  # Wait for state change
                self._monitor_pipeline = None
                print("✓ Monitoring pipeline stopped")
                
                # CRITICAL: Reconnect UI controls back to main pipeline!
                if hasattr(self, 'eqw') and self.eq:
                    self.eqw.set_gst(self.eq)
                if hasattr(self, 'tape_sim') and hasattr(self, 'tape_sat'):
                    self.tape_sim.set_pipeline(self.tape_sat, self.tape_gain, self.tape_tone)
                if hasattr(self, 'tape_spatial'):
                    self.tape_spatial.set_pipeline(self.stereo_width, self.spatial_echo, self.spatial_sat)
                
                print("✓ UI controls reconnected to main pipeline")
                
                # Verify main playbin audio-sink is still set
                audio_sink = self.ply.get_property("audio-sink")
                if audio_sink != self.pipeline_bin:
                    print("⚠ WARNING: audio-sink not set correctly, fixing...")
                    self.ply.set_property("audio-sink", self.pipeline_bin)
                print(f"✓ Main playbin audio-sink verified: {audio_sink}")

        
        # Check if it's a video stream (TV channels)
        is_video = "[TV]" in self.pl[i][1] or uri.startswith("http://") or uri.startswith("https://")
        
        if is_video and ("[TV]" in self.pl[i][1]):
            # Use video player for TV streams
            self.display_stack.setCurrentIndex(1)  # Switch to video
            self.video_player.setSource(QUrl(uri))
            self.video_player.play()
            
            # Also play audio through GStreamer (for spectrum)
            print(f"🎬 Playing video: {uri}")
            self.ply.set_state(Gst.State.NULL)
            self.ply.set_property("uri", uri)
            self.ply.set_state(Gst.State.PLAYING)
        else:
            # Use audio player and visualizer
            self.display_stack.setCurrentIndex(0)  # Switch to visualizer
            self.video_player.stop()
            
            print(f"🎵 Playing audio: {uri}")
            
            # Stop current playback completely
            self.ply.set_state(Gst.State.NULL)
            state_change = self.ply.get_state(Gst.CLOCK_TIME_NONE)
            print(f"  Stopped playbin: {state_change}")
            
            # Verify audio-sink
            audio_sink = self.ply.get_property("audio-sink")
            print(f"  Audio sink: {audio_sink}")
            if not audio_sink or audio_sink != self.pipeline_bin:
                print(f"  ⚠ Resetting audio-sink to pipeline_bin")
                self.ply.set_property("audio-sink", self.pipeline_bin)
            
            # Set new URI
            self.ply.set_property("uri", uri)
            print(f"  URI set: {uri}")
            
            # Start playback
            ret = self.ply.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                print(f"❌ Failed to start playback!")
                # Try to get error message from bus
                msg = self.bus.pop()
                if msg and msg.type == Gst.MessageType.ERROR:
                    err, debug = msg.parse_error()
                    print(f"   Error: {err}")
                    print(f"   Debug: {debug}")
            else:
                print(f"✓ Playback started: {ret}")
        
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
