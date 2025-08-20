import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Gst', '1.0')

from gi.repository import Gtk, Gdk, GObject, GLib, Gst, GdkPixbuf
import os
import json
import random
import subprocess
from urllib.parse import quote
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import base64

# Optional: ID3 for local MP3s (cover art)
try:
    import eyed3
    EYE3D_OK = True
except Exception:
    EYE3D_OK = False

try:
    import notify2
    notify2.init("Carbon Music Player")
    NOTIFY_OK = True
except Exception:
    NOTIFY_OK = False

# For radio stations
try:
    from pyradios import RadioBrowser
    PYRADIOS_OK = True
except Exception:
    PYRADIOS_OK = False
    print("pyradios not installed. Install with 'pip install pyradios' to enable radio search.")


class MusicPlayer:
    """
    Carbon Music Player – improved version with:
    - Fixed visualizer detection using gst-inspect
    - Blinking current track in playlist with morphing colors
    - Better error handling
    - Radio station search using pyradios
    """

    # -------- INIT / CONFIG --------
    def __init__(self):
        Gst.init(None)

        self.config_path = os.path.expanduser("~/.config/carbon_music_player.json")
        self._load_config()
        self._init_state()

        self._build_window()
        self._build_header()
        self._build_main()
        self._apply_css()

        self.window.show_all()

        self._build_gstreamer()
        self._load_recent_playlists_into_combo()

        # timers
        GLib.timeout_add(1000, self._tick_time)
        GLib.timeout_add_seconds(5, self._save_config)
        GLib.timeout_add(1000, self._update_playlist_highlight)  # Increased from 500ms

        self.autofit_active = False
        self.blink_state = False  # For playlist highlighting
        self.color_phase = 0  # For morphing colors

        self.vis_properties = {
            'wavescope': [
                {'name': 'shader', 'type': 'enum', 'values': [0,1,2,3,4,5], 'descs': ['lines', 'lines_fxaa', 'bars', 'dots', 'mesh', 'mesh_fxaa'], 'default': 0},
                {'name': 'style', 'type': 'enum', 'values': [0,1,2,3], 'descs': ['mono', 'color', 'color2', 'color3'], 'default': 0},
            ],
            'spacescope': [
                {'name': 'style', 'type': 'enum', 'values': [0,1], 'descs': ['dots', 'lines'], 'default': 0},
            ],
        }
        self.vis_current_config = {}

        if PYRADIOS_OK:
            self.rb = RadioBrowser()
        else:
            self.rb = None

    def _load_config(self):
        self.config = {
            "recent_playlists": [],
            "last_volume": 0.6,
            "eq_ui": "10-Band",
            "eq_3": [0, 0, 0],
            "eq_10": [0] * 10,
            "show_remaining": False,
            "selected_visualizer": "None",
        }
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r") as f:
                    saved = json.load(f)
                self.config.update(saved)
        except Exception as e:
            print("Config load error:", e)

    def _save_config(self):
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            self.config["last_volume"] = self.gain_scale.get_value() / 100.0
            self.config["eq_ui"] = self.eq_ui_mode
            self.config["eq_3"] = self.eq_3_values
            self.config["eq_10"] = self.eq_10_values
            self.config["show_remaining"] = self.show_remaining
            self.config["selected_visualizer"] = self.selected_visualizer
            with open(self.config_path, "w") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print("Config save error:", e)
        return True

    def _init_state(self):
        self.current_iter = None
        self.current_title = None
        self.current_artist = None
        self.current_album = None
        self.seeking = False
        self.muted = False
        self.repeat_mode = "off"
        self.show_remaining = bool(self.config.get("show_remaining", False))

        self.eq_ui_mode = self.config.get("eq_ui", "10-Band")
        self.eq_3_values = list(self.config.get("eq_3", [0, 0, 0]))
        self.eq_10_values = list(self.config.get("eq_10", [0] * 10))

        self.available_visualizers = []
        self.selected_visualizer = self.config.get("selected_visualizer", "None")

    # -------- UI --------
    def _build_window(self):
        self.window = Gtk.Window()
        self.window.set_title("Music Player - Carbon Edition v4.1")
        self.window.set_default_size(1280, 820)
        self.window.connect("destroy", self._on_destroy)

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.main_box.set_margin_start(15)
        self.main_box.set_margin_end(15)
        self.main_box.set_margin_top(15)
        self.main_box.set_margin_bottom(15)
        self.window.add(self.main_box)

    def _build_header(self):
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        title = Gtk.Label()
        title.set_markup("<span size='x-large' weight='bold'>🎵 Carbon Music Player</span>")
        title.set_halign(Gtk.Align.START)
        hb.pack_start(title, True, True, 0)

        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text("Search in playlist...")
        self.search_entry.connect("changed", lambda e: self.playlist_filter.refilter())
        hb.pack_end(self.search_entry, False, False, 0)

        open_btn = Gtk.Button()
        open_btn.set_image(Gtk.Image.new_from_icon_name("document-open", Gtk.IconSize.LARGE_TOOLBAR))
        open_btn.set_tooltip_text("Open files / playlist")
        open_btn.connect("clicked", self._open_dialog)
        hb.pack_end(open_btn, False, False, 0)

        if PYRADIOS_OK:
            radio_btn = Gtk.Button.new_with_label("Search Radios")
            radio_btn.connect("clicked", self._search_radios)
            hb.pack_end(radio_btn, False, False, 0)

        self.main_box.pack_start(hb, False, False, 0)

    def _build_main(self):
        h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        # LEFT
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        # Playlist
        pl_frame = self._frame("Playlist")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        v.pack_start(self._playlist_toolbar(), False, False, 0)
        self._build_playlist_view()
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.playlist_view)
        v.pack_start(sw, True, True, 0)
        pl_frame.add(v)
        left.pack_start(pl_frame, True, True, 0)

        # Recent
        recent_frame = self._frame("Recent Playlists")
        recent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.recent_combo = Gtk.ComboBoxText()
        self.recent_combo.append_text("Choose recent playlist...")
        self.recent_combo.set_active(0)
        self.recent_combo.connect("changed", self._load_recent_from_combo)
        clear_recent = Gtk.Button.new_with_label("Clear List")
        clear_recent.connect("clicked", self._clear_recent)
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        hb.pack_start(self.recent_combo, True, True, 0)
        hb.pack_start(clear_recent, False, False, 0)
        recent_box.pack_start(hb, False, False, 0)
        recent_frame.add(recent_box)
        left.pack_start(recent_frame, False, False, 0)

        # Controls
        controls_frame = self._frame("Controls")
        controls_frame.add(self._controls_box())
        left.pack_start(controls_frame, False, False, 0)

        # Track Info (with cover art)
        now_frame = self._frame("Now Playing")
        now_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        self.cover_image = Gtk.Image()
        self.cover_image.set_size_request(140, 140)
        now_box.pack_start(self.cover_image, False, False, 0)

        tv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.now_title = Gtk.Label()
        self.now_title.set_markup("<span size='large' weight='bold'>No track playing</span>")
        self.now_title.set_xalign(0)
        tv.pack_start(self.now_title, False, False, 0)

        self.now_artist = Gtk.Label()
        self.now_artist.set_markup("<span size='small'>Artist: Unknown</span>")
        self.now_artist.set_xalign(0)
        tv.pack_start(self.now_artist, False, False, 0)

        self.now_album = Gtk.Label()
        self.now_album.set_markup("<span size='small'>Album: Unknown</span>")
        self.now_album.set_xalign(0)
        tv.pack_start(self.now_album, False, False, 0)

        self.time_label = Gtk.Label()
        self.time_label.set_markup("<span size='small'>00:00 / 00:00</span>")
        self.time_label.set_xalign(0)
        tv.pack_start(self.time_label, False, False, 0)

        ph = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.pos_label = Gtk.Label(label="00:00")
        self.progress_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.progress_scale.set_draw_value(False)
        self.progress_scale.connect("value-changed", self._on_seek)
        self.progress_scale.connect("button-press-event", lambda w, e: setattr(self, 'seeking', True))
        self.progress_scale.connect("button-release-event", lambda w, e: setattr(self, 'seeking', False))
        self.dur_label = Gtk.Label(label="00:00")
        ph.pack_start(self.pos_label, False, False, 0)
        ph.pack_start(self.progress_scale, True, True, 0)
        ph.pack_start(self.dur_label, False, False, 0)
        tv.pack_start(ph, False, False, 0)

        toggle_remaining = Gtk.Button.new_with_label("Show/Hide remaining time")
        toggle_remaining.connect("clicked", lambda w: setattr(self, 'show_remaining', not self.show_remaining))
        tv.pack_start(toggle_remaining, False, False, 0)

        now_box.pack_start(tv, True, True, 0)
        now_frame.add(now_box)
        left.pack_start(now_frame, False, False, 0)

        h.pack_start(left, False, False, 0)

        # RIGHT
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        # Equalizer
        self.eq_frame = self._frame("Equalizer")
        self.eq_frame.add(self._build_equalizer_ui())
        right.pack_start(self.eq_frame, False, False, 0)

        # Visualization (GStreamer)
        viz_frame = self._frame("Visualization (GStreamer)")
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        hb_viz = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.viz_combo = Gtk.ComboBoxText()
        self.viz_combo.connect("changed", self._on_visualizer_changed)
        hb_viz.pack_start(self.viz_combo, True, True, 0)
        self.viz_config_btn = Gtk.Button.new_with_label("Config")
        self.viz_config_btn.connect("clicked", self._on_viz_config)
        hb_viz.pack_start(self.viz_config_btn, False, False, 0)
        vbox.pack_start(hb_viz, False, False, 0)

        self.viz_video_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.viz_video_box.set_size_request(-1, 260)
        vbox.pack_start(self.viz_video_box, True, True, 0)

        viz_frame.add(vbox)
        right.pack_start(viz_frame, True, True, 0)

        h.pack_start(right, True, True, 0)
        self.main_box.pack_start(h, True, True, 0)

    def _apply_css(self):
        css = """
        window { background: #202124; }
        button { background: #3a3d40; color: #fff; border: 1px solid #5f6368; border-radius: 6px; padding: 6px; }
        button:hover { background: #44474a; }
        entry { background: #2b2f33; color: #fff; border: 1px solid #5f6368; border-radius: 6px; padding: 5px; }
        label { color: #e8eaed; }
        frame { background: #26282b; border: 1px solid #5f6368; border-radius: 8px; }
        frame > label { background: #3a3d40; color: #fff; padding: 3px 7px; border-radius: 6px; }
        scale trough { background: #2b2f33; border: 1px solid #5f6368; min-height: 10px; }
        scale slider { background: #8ab4f8; border: 1px solid #aab4be; border-radius: 8px; min-width: 16px; min-height: 16px; }
        .current-track { font-weight: bold; }
        """
    
        # Add EQ band styles
        css_str = css
        for i in range(10):
            hue = int(0 + i * 24)  # From red (0) to blue-ish (216)
            pale = f"hsl({hue}, 40%, 40%)"
            intense = f"hsl({hue}, 80%, 60%)"
            css_str += f".eq-band-{i} trough {{ background: linear-gradient(to top, {pale}, {intense}); }}\n"
            css_str += f".eq-band-{i} slider {{ background: hsl({hue}, 70%, 50%); }}\n"
    
        # Encode as UTF-8 bytes
        css_bytes = css_str.encode('utf-8')
    
        prov = Gtk.CssProvider()
        try:
            prov.load_from_data(css_bytes)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                prov,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        except Exception as e:
            print(f"CSS load error: {e}")
            # Fallback to basic CSS without EQ band styles
            prov.load_from_data("""
            window { background: #202124; }
            button { background: #3a3d40; color: #fff; border: 1px solid #5f6368; border-radius: 6px; padding: 6px; }
            button:hover { background: #44474a; }
            entry { background: #2b2f33; color: #fff; border: 1px solid #5f6368; border-radius: 6px; padding: 5px; }
            label { color: #e8eaed; }
            frame { background: #26282b; border: 1px solid #5f6368; border-radius: 8px; }
            frame > label { background: #3a3d40; color: #fff; padding: 3px 7px; border-radius: 6px; }
            scale trough { background: #2b2f33; border: 1px solid #5f6368; min-height: 10px; }
            scale slider { background: #8ab4f8; border: 1px solid #aab4be; border-radius: 8px; min-width: 16px; min-height: 16px; }
            .current-track { font-weight: bold; }
            """.encode('utf-8'))
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                prov,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _frame(self, title):
        fr = Gtk.Frame()
        fr.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        if title:
            lbl = Gtk.Label()
            lbl.set_markup(f"<span weight='bold'>{title}</span>")
            fr.set_label_widget(lbl)
        return fr

    # -------- PLAYLIST --------
    def _build_playlist_view(self):
        self.playlist_store = Gtk.ListStore(str, str, str, str, str)  # path, artist, genre, album, title
        self.playlist_filter = self.playlist_store.filter_new()
        self.playlist_filter.set_visible_func(self._playlist_filter)

        self.playlist_view = Gtk.TreeView(model=self.playlist_filter)
        
        # Custom cell renderer for current track highlighting
        for i, title in enumerate(["File", "Artist", "Genre", "Album", "Title"]):
            r = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(title, r, text=i)
            col.set_resizable(True)
            col.set_sort_column_id(i)
            col.set_cell_data_func(r, self._cell_data_func, i)
            self.playlist_view.append_column(col)
        
        self.playlist_view.connect("row-activated", self._on_row_activated)

    def _cell_data_func(self, column, cell, model, iter, column_id):
        """Custom cell renderer to highlight current track"""
        if self.current_iter and self.playlist_store.iter_is_valid(self.current_iter):
            try:
                # Convert filter iter to store iter for comparison
                store_iter = model.convert_iter_to_child_iter(iter) if model != self.playlist_store else iter
                current_path = self.playlist_store.get_path(self.current_iter)
                iter_path = self.playlist_store.get_path(store_iter)
                
                if current_path == iter_path:
                    # Generate morphing colors
                    import math
                    phase = (self.color_phase % 360) * math.pi / 180
                    r = int(128 + 127 * math.sin(phase))
                    g = int(128 + 127 * math.sin(phase + 2 * math.pi / 3))
                    b = int(128 + 127 * math.sin(phase + 4 * math.pi / 3))
                    
                    color = f"#{r:02x}{g:02x}{b:02x}"
                    
                    if self.blink_state:
                        cell.set_property("foreground", color)
                        cell.set_property("weight", 700)  # Bold
                    else:
                        cell.set_property("foreground", "#ffffff")
                        cell.set_property("weight", 700)  # Keep bold
                else:
                    cell.set_property("foreground", "#e8eaed")
                    cell.set_property("weight", 400)  # Normal
            except Exception as e:
                # Fallback to normal styling
                cell.set_property("foreground", "#e8eaed")
                cell.set_property("weight", 400)
        else:
            cell.set_property("foreground", "#e8eaed")
            cell.set_property("weight", 400)

    def _update_playlist_highlight(self):
        """Update blinking and color morphing effect"""
        self.blink_state = not self.blink_state
        self.color_phase = (self.color_phase + 10) % 360
        
        # Force redraw of playlist only if iterator is valid
        if hasattr(self, 'playlist_view') and self.current_iter and self.playlist_store.iter_is_valid(self.current_iter):
            self.playlist_view.queue_draw()
        
        return True

    def _playlist_toolbar(self):
        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_file = Gtk.Button.new_with_label("Add File")
        add_file.connect("clicked", self._add_file)
        add_dir = Gtk.Button.new_with_label("Add Folder")
        add_dir.connect("clicked", self._add_folder)
        save_pl = Gtk.Button.new_with_label("Save Playlist")
        save_pl.connect("clicked", self._save_playlist)
        clear_pl = Gtk.Button.new_with_label("Clear")
        clear_pl.connect("clicked", lambda b: (self.playlist_store.clear(), self._update_stats(), setattr(self, 'current_iter', None)))

        sort_combo = Gtk.ComboBoxText()
        sort_combo.append_text("Sort by...")
        for opt in ["Title", "Artist", "Album", "Genre"]:
            sort_combo.append_text(opt)
        sort_combo.set_active(0)
        sort_combo.connect("changed", self._sort_playlist)

        self.playlist_stats = Gtk.Label(label="0 tracks")

        for w in [add_file, add_dir, save_pl, clear_pl, sort_combo]:
            tb.pack_start(w, False, False, 0)
        tb.pack_end(self.playlist_stats, False, False, 0)
        return tb

    def _playlist_filter(self, model, it, data=None):
        text = self.search_entry.get_text().lower()
        if not text:
            return True
        for i in range(5):
            val = model.get_value(it, i)
            if val and text in val.lower():
                return True
        return False

    def _sort_playlist(self, combo):
        a = combo.get_active()
        if a > 0:
            if self.current_iter and self.playlist_store.iter_is_valid(self.current_iter):
                current_path = self.playlist_store.get_value(self.current_iter, 0)  # Store file path
                self.playlist_store.set_sort_column_id(a - 1, Gtk.SortType.ASCENDING)
                # Find new iterator for the same track
                for row in self.playlist_store:
                    if row[0] == current_path:
                        self.current_iter = self.playlist_store.get_iter(row.path)
                        break
                else:
                    self.current_iter = None
            else:
                self.current_iter = None
                self.playlist_store.set_sort_column_id(a - 1, Gtk.SortType.ASCENDING)

    def _update_stats(self):
        self.playlist_stats.set_text(f"{len(self.playlist_store)} tracks")

    def _add_file(self, btn):
        dlg = Gtk.FileChooserDialog(title="Add Audio File", parent=self.window, action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
        dlg.set_select_multiple(True)
        filt = Gtk.FileFilter()
        filt.set_name("Audio files")
        for ext in [".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus"]:
            filt.add_pattern(f"*{ext}")
            filt.add_pattern(f"*{ext.upper()}")
        dlg.add_filter(filt)
        if dlg.run() == Gtk.ResponseType.OK:
            self.current_iter = None  # Reset iterator to avoid stale reference
            for p in dlg.get_filenames():
                self._append_track(p)
        dlg.destroy()

    def _add_folder(self, btn):
        dlg = Gtk.FileChooserDialog(title="Add Folder", parent=self.window, action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
        if dlg.run() == Gtk.ResponseType.OK:
            self.current_iter = None  # Reset iterator
            root = dlg.get_filename()
            for rt, _, files in os.walk(root):
                for f in files:
                    fp = os.path.join(rt, f)
                    if self._is_audio(fp):
                        self._append_track(fp)
        dlg.destroy()

    def _save_playlist(self, btn):
        dlg = Gtk.FileChooserDialog(title="Save Playlist", parent=self.window, action=Gtk.FileChooserAction.SAVE)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        filt = Gtk.FileFilter()
        filt.set_name("M3U Playlist")
        filt.add_pattern("*.m3u")
        dlg.add_filter(filt)
        if dlg.run() == Gtk.ResponseType.OK:
            path = dlg.get_filename()
            if not path.endswith('.m3u'):
                path += '.m3u'
            with open(path, 'w', encoding='utf-8') as f:
                f.write("#EXTM3U\n")
                for row in self.playlist_store:
                    f.write(f"{row[0]}\n")
            self._add_recent(path)
            self._notify("Playlist Saved", os.path.basename(path))
        dlg.destroy()

    def _is_audio(self, path):
        if path.startswith(('http://', 'https://')):
            return True
        return any(path.lower().endswith(ext) for ext in [
            '.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.wma', '.opus'
        ])

    def _append_track(self, path, artist="Unknown", genre="Unknown", album="Unknown", title=None):
        if path.startswith(('http://', 'https://')):
            title = title or os.path.basename(path.split('?')[0]) or "Stream"
            self.playlist_store.append([path, artist, genre, album, title])
        else:
            title = title or os.path.basename(path)
            if EYE3D_OK and path.lower().endswith('.mp3'):
                try:
                    af = eyed3.load(path)
                    if af and af.tag:
                        title = af.tag.title or title
                        artist = af.tag.artist or artist
                        genre = str(af.tag.genre) if af.tag.genre else genre
                        album = af.tag.album or album
                except Exception as e:
                    print("eyed3 read error:", e)
            self.playlist_store.append([path, artist, genre, album, title])
        self._update_stats()

    def _on_row_activated(self, tv, path, col):
        model = tv.get_model()
        self.current_iter = model.get_iter(path)
        if model != self.playlist_store:
            self.current_iter = model.convert_iter_to_child_iter(self.current_iter)
        self._play()

    # -------- RADIO SEARCH --------
    def _search_radios(self, btn):
        if not PYRADIOS_OK or not self.rb:
            self._error("pyradios not available. Install with 'pip install pyradios'.")
            return
    
        # Use modal=True instead of deprecated flags
        dlg = Gtk.Dialog(
            title="Search Internet Radios",
            parent=self.window,
            modal=True,
            destroy_with_parent=True
        )
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Add Selected", Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_spacing(6)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
    
        # Name
        hb_name = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl_name = Gtk.Label(label="Name:")
        self.radio_name_entry = Gtk.Entry()
        hb_name.pack_start(lbl_name, False, False, 0)
        hb_name.pack_start(self.radio_name_entry, True, True, 0)
        box.pack_start(hb_name, False, False, 0)
    
        # Country
        hb_country = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl_country = Gtk.Label(label="Country:")
        self.radio_country_store = Gtk.ListStore(str, str)  # code, name
        self.radio_country_combo = Gtk.ComboBox(model=self.radio_country_store)
        renderer = Gtk.CellRendererText()
        self.radio_country_combo.pack_start(renderer, True)
        self.radio_country_combo.add_attribute(renderer, "text", 1)
        hb_country.pack_start(lbl_country, False, False, 0)
        hb_country.pack_start(self.radio_country_combo, True, True, 0)
        box.pack_start(hb_country, False, False, 0)
    
        # Language
        hb_lang = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl_lang = Gtk.Label(label="Language:")
        self.radio_lang_entry = Gtk.Entry()
        hb_lang.pack_start(lbl_lang, False, False, 0)
        hb_lang.pack_start(self.radio_lang_entry, True, True, 0)
        box.pack_start(hb_lang, False, False, 0)
    
        # Tag
        hb_tag = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl_tag = Gtk.Label(label="Tag:")
        self.radio_tag_entry = Gtk.Entry()
        hb_tag.pack_start(lbl_tag, False, False, 0)
        hb_tag.pack_start(self.radio_tag_entry, True, True, 0)
        box.pack_start(hb_tag, False, False, 0)
    
        # Search button
        search_btn = Gtk.Button.new_with_label("Search")
        search_btn.connect("clicked", self._do_radio_search)
        box.pack_start(search_btn, False, False, 0)
    
        # Results TreeView
        self.radio_results_store = Gtk.ListStore(str, str, str, str, int, str)  # name, country, language, tags, bitrate, url
        self.radio_results_view = Gtk.TreeView(model=self.radio_results_store)
        self.radio_results_view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        for i, title in enumerate(["Name", "Country", "Language", "Tags", "Bitrate"]):
            r = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(title, r, text=i)
            col.set_resizable(True)
            self.radio_results_view.append_column(col)
    
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.radio_results_view)
        sw.set_size_request(600, 400)
        box.pack_start(sw, True, True, 0)
    
        dlg.show_all()
    
        # Populate country combo
        self.radio_country_store.append(['', 'Any'])
        try:
            countries = self.rb.countries()
            sorted_countries = sorted(countries, key=lambda x: x['name'])
            for c in sorted_countries:
                # Use 'countrycode' instead of 'code' based on RadioBrowser API
                self.radio_country_store.append([c.get('countrycode', ''), c.get('name', 'Unknown')])
            self.radio_country_combo.set_active(0)
        except Exception as e:
            self._error(f"Failed to load countries: {str(e)}")
    
        response = dlg.run()
        if response == Gtk.ResponseType.OK:
            model, paths = self.radio_results_view.get_selection().get_selected_rows()
            added = 0
            for path in paths:
                it = model.get_iter(path)
                url = model.get_value(it, 5)
                name = model.get_value(it, 0) or "Unknown"
                country = model.get_value(it, 1) or "Unknown"
                language = model.get_value(it, 2) or "Unknown"
                tags = model.get_value(it, 3) or ""
                if url:
                    self._append_track(
                        url,
                        artist=f"Online - {language}",
                        genre=tags,
                        album=country,
                        title=name
                    )
                    added += 1
            if added > 0:
                self._notify("Radio Stations Added", f"{added} stations added to playlist")
                self._update_stats()
            else:
                self._notify("No Stations Added", "No stations were selected")
    
        dlg.destroy()

    def _do_radio_search(self, btn):
        self.radio_results_store.clear()

        name = self.radio_name_entry.get_text().strip() or None
        lang = self.radio_lang_entry.get_text().strip() or None
        tag = self.radio_tag_entry.get_text().strip() or None

        active_iter = self.radio_country_combo.get_active_iter()
        country_code = None
        if active_iter:
            country_code = self.radio_country_store.get_value(active_iter, 0)
            if not country_code:
                country_code = None

        params = {
            'limit': 100,
            'order': 'clickcount',
            'reverse': True,
            'hidebroken': True
        }
        if name:
            params['name'] = name
        if country_code:
            params['countrycode'] = country_code
        if lang:
            params['language'] = lang
        if tag:
            params['tag'] = tag

        try:
            results = self.rb.search(**params)
            for r in results:
                self.radio_results_store.append([
                    r.get('name', 'Unknown'),
                    r.get('country', 'Unknown'),
                    r.get('language', 'Unknown'),
                    r.get('tags', ''),
                    r.get('bitrate', 0),
                    r.get('url', '')
                ])
        except Exception as e:
            self._error(f"Radio search error: {str(e)}")

    # -------- CONTROLS --------
    def _controls_box(self):
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.btn_play = Gtk.Button.new_with_label("▶ Play")
        self.btn_play.connect("clicked", lambda b: self._play())
        self.btn_pause = Gtk.Button.new_with_label("⏸ Pause")
        self.btn_pause.connect("clicked", lambda b: self._toggle_pause())
        self.btn_stop = Gtk.Button.new_with_label("⏹ Stop")
        self.btn_stop.connect("clicked", lambda b: self._stop())
        prev_btn = Gtk.Button.new_with_label("⏮ Previous")
        prev_btn.connect("clicked", lambda b: self._prev())
        next_btn = Gtk.Button.new_with_label("⏭ Next")
        next_btn.connect("clicked", lambda b: self._next())
        for w in [self.btn_play, self.btn_pause, self.btn_stop, prev_btn, next_btn]:
            hb.pack_start(w, False, False, 0)
        v.pack_start(hb, False, False, 0)

        vol_frame = Gtk.Frame(label="Volume")
        vh = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.mute_btn = Gtk.Button.new_with_label("🔊")
        self.mute_btn.connect("clicked", lambda b: self._toggle_mute())
        self.gain_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.gain_scale.set_value(self.config.get("last_volume", 0.6) * 100)
        self.gain_scale.set_draw_value(True)
        self.gain_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.gain_scale.add_mark(0, Gtk.PositionType.BOTTOM, "0%")
        self.gain_scale.add_mark(50, Gtk.PositionType.BOTTOM, "50%")
        self.gain_scale.add_mark(100, Gtk.PositionType.BOTTOM, "100%")
        self.gain_scale.connect("value-changed", lambda s: self.playbin.set_property("volume", s.get_value()/100.0))
        vh.pack_start(self.mute_btn, False, False, 0)
        vh.pack_start(self.gain_scale, True, True, 0)
        vol_frame.add(vh)
        v.pack_start(vol_frame, False, False, 0)

        hb2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        off = Gtk.RadioButton.new_with_label_from_widget(None, "No Repeat")
        one = Gtk.RadioButton.new_with_label_from_widget(off, "Repeat One")
        allb = Gtk.RadioButton.new_with_label_from_widget(off, "Repeat All")
        off.connect("toggled", lambda b: setattr(self, 'repeat_mode', 'off'))
        one.connect("toggled", lambda b: setattr(self, 'repeat_mode', 'one'))
        allb.connect("toggled", lambda b: setattr(self, 'repeat_mode', 'all'))
        for w in [off, one, allb]:
            hb2.pack_start(w, False, False, 0)
        shuffle_btn = Gtk.Button.new_with_label("🔀 Shuffle")
        shuffle_btn.connect("clicked", lambda b: self._shuffle())
        hb2.pack_start(shuffle_btn, False, False, 0)
        v.pack_start(hb2, False, False, 0)
        return v

    # -------- EQUALIZER UI --------
    def _build_equalizer_ui(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        mode_h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.eq_mode_3 = Gtk.RadioButton.new_with_label_from_widget(None, "3-Band")
        self.eq_mode_10 = Gtk.RadioButton.new_with_label_from_widget(self.eq_mode_3, "10-Band")
        if self.eq_ui_mode == "3-Band":
            self.eq_mode_3.set_active(True)
        else:
            self.eq_mode_10.set_active(True)
        self.eq_mode_3.connect("toggled", lambda b: self._switch_eq_ui("3-Band") if b.get_active() else None)
        self.eq_mode_10.connect("toggled", lambda b: self._switch_eq_ui("10-Band") if b.get_active() else None)
        for w in [self.eq_mode_3, self.eq_mode_10]:
            mode_h.pack_start(w, False, False, 0)
        box.pack_start(mode_h, False, False, 0)

        presets = self._eq_presets()
        ph = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.eq_preset_combo = Gtk.ComboBoxText()
        for name in presets.keys():
            self.eq_preset_combo.append_text(name)
        self.eq_preset_combo.set_active(0)
        self.eq_preset_combo.connect("changed", lambda c: self._apply_preset(presets))
        reset_btn = Gtk.Button.new_with_label("Reset")
        reset_btn.connect("clicked", lambda b: self._reset_eq())
        autofit_btn = Gtk.Button.new_with_label("AutoFit EQ")
        autofit_btn.set_tooltip_text("Adjust EQ sliders to current spectrum")
        autofit_btn.connect("clicked", self._autofit_eq_from_spectrum)
        autofit_btn.set_sensitive(True)
        for w in [self.eq_preset_combo, reset_btn, autofit_btn]:
            ph.pack_start(w, False, False, 0)
        box.pack_start(ph, False, False, 0)

        self.eq_sliders_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.pack_start(self.eq_sliders_box, False, False, 0)
        self._rebuild_eq_sliders()

        return box

    def _switch_eq_ui(self, mode):
        self.eq_ui_mode = mode
        self._rebuild_eq_sliders()
        if hasattr(self, 'spectrum') and self.spectrum:
            self.spectrum.set_property("bands", 10 if mode == "10-Band" else 3)
        self._apply_eq()

    def _rebuild_eq_sliders(self):
        for child in list(self.eq_sliders_box.get_children()):
            self.eq_sliders_box.remove(child)
        self.eq_sliders = []

        if self.eq_ui_mode == "3-Band":
            labels = ["Low", "Mid", "High"]
            values = self.eq_3_values
            bands = 3
        else:
            labels = ["31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
            values = self.eq_10_values
            bands = 10

        for i in range(bands):
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            lbl = Gtk.Label(label=labels[i])
            lbl.set_angle(90)
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, -12, 12, 1)
            sc.set_value(values[i])
            sc.set_size_request(36, 160)
            sc.connect("value-changed", lambda s, idx=i: self._on_eq_slider(idx, s.get_value()))

            # Add marks
            for val in [-12, -6, 0, 6, 12]:
                sc.add_mark(val, Gtk.PositionType.RIGHT, str(val))
            for val in [-9, -3, 3, 9]:
                sc.add_mark(val, Gtk.PositionType.RIGHT, None)

            vb.pack_start(lbl, False, False, 0)
            vb.pack_start(sc, True, True, 0)
            self.eq_sliders_box.pack_start(vb, False, False, 0)
            self.eq_sliders.append(sc)

            # Add class for CSS
            vb.get_style_context().add_class(f"eq-band-{i}")

        self.eq_sliders_box.show_all()

    def _on_eq_slider(self, idx, val):
        if self.eq_ui_mode == "3-Band":
            self.eq_3_values[idx] = val
        else:
            self.eq_10_values[idx] = val
        self._apply_eq()

    def _eq_presets(self):
        return {
            "Flat": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "Rock": [4, 3, 2, 1, 0, 0, 1, 2, 3, 4],
            "Pop": [0, 2, 3, 4, 3, 2, 1, 0, 0, 0],
            "Classical": [0, 0, 0, 0, 0, -1, -2, -3, -2, -1],
            "Bass Boost": [6, 5, 4, 2, 0, 0, 0, 0, 0, 0],
            "Jazz": [2, 1, 0, -1, 0, 1, 2, 2, 1, 0],
            "Vocal": [-1, -1, 0, 2, 4, 4, 2, 0, -1, -1],
            "Dance": [5, 4, 3, 1, 0, 0, 1, 3, 4, 5],
            "Metal": [3, 2, 1, 0, -1, -1, 0, 1, 2, 3],
            "Treble Boost": [0, 0, 0, 0, 0, 2, 3, 4, 5, 6],
            "Soft": [0, -1, -2, -2, -1, 0, 1, 1, 0, -1],
        }

    def _apply_preset(self, presets):
        name = self.eq_preset_combo.get_active_text()
        if not name:
            return
        vals10 = list(presets[name])
        self.eq_10_values = vals10
        self.eq_3_values = [
            sum(vals10[0:3]) / 3.0,
            sum(vals10[3:7]) / 4.0,
            sum(vals10[7:10]) / 3.0,
        ]
        if self.eq_ui_mode == "3-Band":
            for i, sc in enumerate(self.eq_sliders):
                sc.set_value(self.eq_3_values[i])
        else:
            for i, sc in enumerate(self.eq_sliders):
                sc.set_value(self.eq_10_values[i])
        self._apply_eq()

    def _reset_eq(self):
        self.eq_3_values = [0, 0, 0]
        self.eq_10_values = [0] * 10
        for sc in self.eq_sliders:
            sc.set_value(0)
        self._apply_eq()

    def _autofit_eq_from_spectrum(self, btn=None):
        if self.autofit_active:
            self.autofit_active = False
            self._notify("AutoFit EQ", "Dynamic EQ adjustment disabled")
        else:
            self.autofit_active = True
            self._notify("AutoFit EQ", "Dynamic EQ adjustment enabled")

    # -------- GSTREAMER --------
        
    def _build_gstreamer(self):
        self.playbin = Gst.ElementFactory.make("playbin", "playbin")
        self.playbin.set_property("volume", self.config.get("last_volume", 0.6))
    
        # --- audio processing bin: audioconvert -> audioresample -> spectrum -> eq -> sink
        self.audio_bin = Gst.Bin.new("audio_bin")
        ac1 = Gst.ElementFactory.make("audioconvert", None)
        ar1 = Gst.ElementFactory.make("audioresample", None)
    
        self.spectrum = Gst.ElementFactory.make("spectrum", "spectrum")
        if not self.spectrum:
            print("Failed to create spectrum element. Ensure gstreamer1.0-plugins-good is installed.")
            self._notify("Error", "Spectrum element unavailable. Install gstreamer1.0-plugins-good.")
            return
    
        self.spectrum.set_property("bands", 10 if self.eq_ui_mode == "10-Band" else 3)
        self.spectrum.set_property("threshold", -80)
        self.spectrum.set_property("post-messages", True)
        self.spectrum.set_property("message-magnitude", True)
    
        self.eq_element = Gst.ElementFactory.make("equalizer-10bands", "eq")
        self.eq_mode_bands = 10 if self.eq_element else 3
        if not self.eq_element:
            self.eq_element = Gst.ElementFactory.make("equalizer-3bands", "eq")
    
        ac2 = Gst.ElementFactory.make("audioconvert", None)
        ar2 = Gst.ElementFactory.make("audioresample", None)
    
        sink = None
        for name in ("pipewiresink", "pulsesink", "autoaudiosink", "alsasink"):
            try:
                s = Gst.ElementFactory.make(name, None)
                if s:
                    sink = s
                    print("Using audio sink:", name)
                    break
            except Exception:
                pass
        if not sink:
            sink = Gst.ElementFactory.make("autoaudiosink", None)
    
        for el in [ac1, ar1, self.spectrum, self.eq_element, ac2, ar2, sink]:
            if el:
                self.audio_bin.add(el)
    
        chain = [ac1, ar1, self.spectrum, self.eq_element, ac2, ar2, sink]
        prev = chain[0]
        for el in chain[1:]:
            if prev and el:
                if not prev.link(el):
                    print("Link failed:", prev, "->", el)
            prev = el
    
        sinkpad = ac1.get_static_pad("sink")
        self.audio_bin.add_pad(Gst.GhostPad.new("sink", sinkpad))
    
        self.playbin.set_property("audio-sink", self.audio_bin)
    
        # --- video sink (for visualizations)
        self.video_sink = Gst.ElementFactory.make("gtksink", "gtksink")
        if not self.video_sink:
            self.video_sink = Gst.ElementFactory.make("autovideosink", None)
        self.playbin.set_property("video-sink", self.video_sink)
    
        try:
            if self.video_sink and self.video_sink.props.widget:
                self.viz_video_box.pack_start(self.video_sink.props.widget, True, True, 0)
                self.viz_video_box.show_all()
        except Exception:
            pass
    
        self.available_visualizers = self._detect_visualizers()
        self._fill_visualizer_combo()
    
        try:
            flags = self.playbin.get_property("flags")
            self.playbin.set_property("flags", int(flags) | 0x0008)  # 0x0008 = VIS
        except Exception as e:
            print("Cannot set playbin VIS flag:", e)
    
        bus = self.playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus)
    
        self._apply_eq()
        self._apply_visualizer(self.selected_visualizer)

    def _detect_visualizers(self):
        """Improved visualizer detection using gst-inspect-1.0 command"""
        visualizers = []
        
        # Try using gst-inspect-1.0 command for better detection
        try:
            result = subprocess.run(['gst-inspect-1.0'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    line = line.strip()
                    if ':' in line:
                        parts = line.split(':', 2)
                        if len(parts) >= 2:
                            plugin_name = parts[0].strip()
                            element_name = parts[1].strip()
                            description = parts[2].strip() if len(parts) > 2 else element_name
                            
                            # Check for visualization-related plugins
                            if any(keyword in plugin_name.lower() or keyword in element_name.lower() 
                                   for keyword in ['visual', 'goom', 'scope', 'spectrum', 'synaes']):
                                
                                # Test if element can be created
                                try:
                                    test_elem = Gst.ElementFactory.make(element_name, None)
                                    if test_elem:
                                        visualizers.append((element_name, description))
                                        print(f"Found visualizer via gst-inspect: {element_name} ({description})")
                                except Exception:
                                    pass
                            
                            # Also check specific known visualizers
                            if element_name in ['goom', 'goom2k1', 'synaesthesia', 'monoscope', 
                                              'spacescope', 'spectrascope', 'synaescope', 'wavescope']:
                                try:
                                    test_elem = Gst.ElementFactory.make(element_name, None)
                                    if test_elem:
                                        visualizers.append((element_name, description))
                                        print(f"Found known visualizer: {element_name} ({description})")
                                except Exception:
                                    pass
                                    
        except Exception as e:
            print(f"gst-inspect command failed: {e}")
        
        # Fallback to registry scanning if gst-inspect didn't work well
        if len(visualizers) < 3:  # If we didn't find many, try registry method
            try:
                registry = Gst.Registry.get()
                features = registry.get_feature_list(Gst.ElementFactory)
                
                for feature in features:
                    try:
                        klass = feature.get_klass() or ""
                        name = feature.get_name()
                        
                        if (("Visualization" in klass or "Visual" in klass) or 
                            name in ["goom", "goom2k1", "synaesthesia", "monoscope", 
                                   "spacescope", "spectrascope", "synaescope", "wavescope"]):
                            
                            elem = Gst.ElementFactory.make(name, None)
                            if elem:
                                longname = feature.get_longname() or name
                                if (name, longname) not in visualizers:
                                    visualizers.append((name, longname))
                                    print(f"Found visualizer via registry: {name} ({longname})")
                    except Exception as e:
                        continue
                        
            except Exception as e:
                print(f"Registry scan failed: {e}")
        
        # Remove duplicates and sort
        unique_visualizers = []
        seen_names = set()
        for name, desc in visualizers:
            if name not in seen_names:
                seen_names.add(name)
                unique_visualizers.append((name, desc))
        
        unique_visualizers.sort(key=lambda x: x[0].lower())
        
        if not unique_visualizers:
            print("No visualization plugins found. Install packages like:")
            print("- gstreamer1.0-plugins-good (for basic visualizers)")
            print("- gstreamer1.0-plugins-bad (for more visualizers)")
            print("- gstreamer1.0-libvisual (for libvisual plugins)")
            self._notify("Warning", "No visualization plugins detected. Install GStreamer visualization packages.")
        else:
            print(f"Found {len(unique_visualizers)} visualization plugins")
        
        return unique_visualizers

    def _fill_visualizer_combo(self):
        if hasattr(self, 'viz_combo'):
            # Disconnect existing handler
            handlers = GObject.signal_list_ids(self.viz_combo)
            for handler_id in handlers:
                if GObject.signal_name(handler_id) == "changed":
                    self.viz_combo.disconnect(handler_id)
            
            self.viz_combo.remove_all()
            
        self.viz_combo.append_text("None")
        for name, longname in self.available_visualizers:
            display_text = f"{name} — {longname}" if longname != name else name
            self.viz_combo.append_text(display_text)
        
        # Set active item
        active_idx = 0
        if self.selected_visualizer != "None":
            for i, (name, _) in enumerate(self.available_visualizers, start=1):
                if name == self.selected_visualizer:
                    active_idx = i
                    break
        
        self.viz_combo.set_active(active_idx)
        self.viz_combo.connect("changed", self._on_visualizer_changed)

    def _on_visualizer_changed(self, combo):
        text = combo.get_active_text()
        if not text:
            return
        if text == "None":
            self._apply_visualizer("None")
        else:
            vis_name = text.split(" — ", 1)[0].strip()
            self._apply_visualizer(vis_name)

    def _on_viz_config(self, btn):
        text = self.viz_combo.get_active_text()
        if not text or text == "None":
            return
        vis_name = text.split(" — ", 1)[0].strip()
        if vis_name not in self.vis_properties:
            self._notify("No config", "No options for this visualizer")
            return
        props = self.vis_properties[vis_name]
        config = self.vis_current_config.get(vis_name, {p['name']: p['default'] for p in props})

        dlg = Gtk.Dialog(title="Visualizer Config", parent=self.window, flags=Gtk.DialogFlags.MODAL)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "OK", Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_spacing(6)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.set_margin_top(10)
        box.set_margin_bottom(10)

        for p in props:
            hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            lbl = Gtk.Label(label=p['name'])
            combo = Gtk.ComboBoxText()
            for desc in p['descs']:
                combo.append_text(desc)
            combo.set_active(config[p['name']])
            hb.pack_start(lbl, False, False, 0)
            hb.pack_start(combo, True, True, 0)
            box.pack_start(hb, False, False, 0)
            p['temp_combo'] = combo  # Temp reference

        dlg.show_all()
        response = dlg.run()
        if response == Gtk.ResponseType.OK:
            for p in props:
                idx = p['temp_combo'].get_active()
                value = p['values'][idx]
                config[p['name']] = value
            self.vis_current_config[vis_name] = config
            self._apply_visualizer(vis_name)
        dlg.destroy()

    def _apply_visualizer(self, vis_name: str):
        """Apply GStreamer visualization to playbin"""
        self.selected_visualizer = vis_name
        try:
            current_state = self.playbin.get_state(0)[1]
            self.playbin.set_state(Gst.State.PAUSED)

            if vis_name == "None":
                try:
                    self.playbin.set_property("vis-plugin", None)
                    print("Cleared visualization")
                except Exception as e:
                    print("Clear vis-plugin error:", e)
            else:
                elem = Gst.ElementFactory.make(vis_name, None)
                if not elem:
                    print(f"Cannot create visualizer: {vis_name}")
                    self.playbin.set_property("vis-plugin", None)
                    self._notify("Error", f"Failed to create visualizer: {vis_name}")
                else:
                    if vis_name in self.vis_current_config:
                        for prop_name, value in self.vis_current_config[vis_name].items():
                            elem.set_property(prop_name, value)
                    try:
                        self.playbin.set_property("vis-plugin", elem)
                        print(f"Applied visualizer: {vis_name}")
                        self._notify("Visualizer", f"Activated: {vis_name}")
                    except Exception as e:
                        print(f"Set vis-plugin error: {e}")
                        self.playbin.set_property("vis-plugin", None)

            try:
                flags = self.playbin.get_property("flags")
                self.playbin.set_property("flags", int(flags) | 0x0008)  # Enable VIS flag
            except Exception as e:
                print("Cannot set playbin VIS flag:", e)

            if current_state == Gst.State.PLAYING:
                self.playbin.set_state(Gst.State.PLAYING)
            else:
                self.playbin.set_state(current_state)
        except Exception as e:
            print(f"Apply visualizer error: {e}")
            self._notify("Error", f"Visualizer error: {str(e)}")

    def _apply_eq(self):
        if not self.eq_element:
            return
        if self.eq_mode_bands == 10:
            vals = self.eq_10_values if self.eq_ui_mode == "10-Band" else (
                [self.eq_3_values[0]]*3 + [self.eq_3_values[1]]*4 + [self.eq_3_values[2]]*3
            )
            for i, g in enumerate(vals[:10]):
                try:
                    self.eq_element.set_property(f"band{i}", float(g))
                except Exception as e:
                    print("EQ set error:", i, e)
        else:
            if self.eq_ui_mode == "10-Band":
                m3 = [
                    sum(self.eq_10_values[0:3]) / 3.0,
                    sum(self.eq_10_values[3:7]) / 4.0,
                    sum(self.eq_10_values[7:10]) / 3.0,
                ]
            else:
                m3 = self.eq_3_values
            for i, g in enumerate(m3[:3]):
                try:
                    self.eq_element.set_property(f"band{i}", float(g))
                except Exception as e:
                    print("EQ set error (3):", i, e)

    # -------- BUS / TAGS --------
    def _on_bus(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS:
            self._next()
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print("GStreamer ERROR:", err, debug)
            self._stop()
            self.current_iter = None  # Reset iterator on error
            self._notify("Playback Error", f"{str(err)}\n{debug}")
        elif t == Gst.MessageType.TAG:
            taglist = message.parse_tag()
            self._update_from_tags(taglist)
            self._maybe_update_cover_from_tags(taglist)
        elif t == Gst.MessageType.ELEMENT:
            if message.src.get_name() == "spectrum":
                self._process_spectrum_message(message)

    def _process_spectrum_message(self, message):
        """Working spectrum processing using string conversion workaround for GstValueList"""
        if not self.autofit_active:
            return
        
        structure = message.get_structure()
        if not structure or structure.get_name() != "spectrum":
            return
    
        try:
            # Workaround for GstValueList limitation in gst-python
            # Convert structure to string and parse the magnitude values
            struct_str = structure.to_string()
            
            # Debug print (remove after testing)
            if not hasattr(self, '_spectrum_debug_done'):
                print(f"Spectrum structure string: {struct_str[:200]}...")  # First 200 chars
                self._spectrum_debug_done = True
            
            magnitudes_list = []
            
            # Look for magnitude field in the string
            # Expected format: magnitude=(float){ value1, value2, value3, ... }
            import re
            
            # Try different patterns for magnitude field
            patterns = [
                r'magnitude=\(float\)\{\s*([^}]+)\s*\}',  # magnitude=(float){ 1.0, 2.0, 3.0 }
                r'magnitude=<\s*([^>]+)\s*>',             # magnitude=< 1.0, 2.0, 3.0 >
                r'magnitude=\[\s*([^\]]+)\s*\]',          # magnitude=[ 1.0, 2.0, 3.0 ]
                r'magnitude=\{\s*([^}]+)\s*\}',           # magnitude={ 1.0, 2.0, 3.0 }
            ]
            
            magnitude_values_str = None
            for pattern in patterns:
                match = re.search(pattern, struct_str)
                if match:
                    magnitude_values_str = match.group(1)
                    break
            
            if magnitude_values_str:
                # Parse the comma-separated float values
                try:
                    # Split by comma and convert to floats
                    value_strings = magnitude_values_str.split(',')
                    for value_str in value_strings:
                        cleaned_value = value_str.strip()
                        # Remove any extra formatting
                        cleaned_value = re.sub(r'[^\d\.\-\+e]', '', cleaned_value)
                        if cleaned_value:
                            try:
                                magnitude = float(cleaned_value)
                                magnitudes_list.append(magnitude)
                            except ValueError:
                                continue
                                
                except Exception as e:
                    print(f"Error parsing magnitude values: {e}")
                    return
            
            if not magnitudes_list:
                # If we still can't find magnitude data, show what we got
                if not hasattr(self, '_no_magnitude_warned'):
                    print(f"No magnitude values found in spectrum message.")
                    print(f"Structure string: {struct_str}")
                    self._no_magnitude_warned = True
                return
            
            # Success! Apply the EQ adjustments
            if not hasattr(self, '_magnitude_success_logged'):
                print(f"Successfully extracted {len(magnitudes_list)} magnitude values!")
                print(f"Sample values: {magnitudes_list[:5]}")
                self._magnitude_success_logged = True
            
            # Apply AutoFit EQ adjustment
            target_preset = self.eq_10_values if self.eq_ui_mode == "10-Band" else self.eq_3_values
            num_bands = min(len(magnitudes_list), len(target_preset))
            
            for i in range(num_bands):
                try:
                    mag_db = magnitudes_list[i]
                    
                    # Convert magnitude from dB to EQ adjustment
                    # Spectrum gives us dB values (typically -80 to 0)
                    # We want to convert this to EQ gain adjustments (-12 to +12)
                    
                    # Clamp to reasonable spectrum range
                    mag_db = max(-80, min(0, mag_db))
                    
                    # Simple mapping strategy:
                    # Quiet frequencies (< -50 dB) -> boost them (+1 to +4 dB)
                    # Medium frequencies (-50 to -20 dB) -> minimal adjustment 
                    # Loud frequencies (> -20 dB) -> reduce them (-1 to -3 dB)
                    
                    if mag_db < -50:
                        # Quiet - boost it
                        eq_adjustment = 2.0 + ((-50 - mag_db) / 30.0) * 2.0  # +2 to +4 dB
                    elif mag_db < -20:
                        # Medium - minimal adjustment  
                        eq_adjustment = (mag_db + 35) / 15.0  # -1 to +1 dB
                    else:
                        # Loud - cut it
                        eq_adjustment = -1.0 + ((mag_db + 20) / 20.0) * (-2.0)  # -1 to -3 dB
                    
                    # Clamp to EQ limits
                    eq_adjustment = max(-12, min(12, eq_adjustment))
                    
                    # Very gentle blending with current EQ (only 2% adjustment per update)
                    current_gain = target_preset[i]
                    new_gain = current_gain * 0.98 + eq_adjustment * 0.02
                    
                    # Apply bounds again
                    new_gain = max(-12, min(12, new_gain))
                    
                    # Update EQ values and sliders
                    if self.eq_ui_mode == "3-Band":
                        self.eq_3_values[i] = new_gain
                        if i < len(self.eq_sliders):
                            GLib.idle_add(self.eq_sliders[i].set_value, new_gain)
                    else:
                        self.eq_10_values[i] = new_gain
                        if i < len(self.eq_sliders):
                            GLib.idle_add(self.eq_sliders[i].set_value, new_gain)
                            
                except Exception as e:
                    continue
            
            # Apply the EQ changes
            GLib.idle_add(self._apply_eq)
    
        except Exception as e:
            if not hasattr(self, '_spectrum_error_count'):
                self._spectrum_error_count = 0
            
            self._spectrum_error_count += 1
            if self._spectrum_error_count <= 2:  # Only show first couple errors
                print(f"AutoFit EQ processing error: {e}")
    
    def _update_from_tags(self, taglist):
        if self.current_iter and self.playlist_store.iter_is_valid(self.current_iter):
            def sget(name):
                ok, val = taglist.get_string(name)
                return val if ok else None
            title = sget("title")
            artist = sget("artist")
            album = sget("album")
            if title:
                self.playlist_store.set_value(self.current_iter, 4, title)
                self.now_title.set_markup(f"<span size='large' weight='bold'>{title}</span>")
            if artist:
                self.playlist_store.set_value(self.current_iter, 1, artist)
                self.now_artist.set_markup(f"<span size='small'>Artist: {artist}</span>")
            if album:
                self.playlist_store.set_value(self.current_iter, 3, album)
                self.now_album.set_markup(f"<span size='small'>Album: {album}</span>")

    def _maybe_update_cover_from_tags(self, taglist: Gst.TagList, current_uri: str = None):
        """Update cover art from tags, URLs, or remote ID3"""
        def _set_pixbuf_from_bytes(data: bytes):
            try:
                loader = GdkPixbuf.PixbufLoader.new()
                loader.write(data)
                loader.close()
                cover = loader.get_pixbuf()
                if cover:
                    scaled = cover.scale_simple(140, 140, GdkPixbuf.InterpType.BILINEAR)
                    self.cover_image.set_from_pixbuf(scaled)
                    return True
            except Exception as e:
                print("Pixbuf decode failed:", e)
            return False
    
        current_uri = current_uri or getattr(self, 'current_uri', None)
        self.cover_image.clear()
    
        # Try tags first (z GStreamer – to działa dla streamów)
        for key in ("image", "coverart", "preview-image"):
            ok, sample = taglist.get_sample(key)
            if ok and sample:
                buf = sample.get_buffer()
                if buf:
                    success, mapinfo = buf.map(Gst.MapFlags.READ)
                    if success:
                        if _set_pixbuf_from_bytes(mapinfo.data):
                            buf.unmap(mapinfo)
                            return
                        buf.unmap(mapinfo)
    
        # Try URL tags (to działa, bo fetchuje osobny URL na cover, nie stream)
        for key in ("coverart-url", "image"):
            ok, url = taglist.get_string(key)
            if ok and url and url.startswith(("http://", "https://")):
                try:
                    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Carbon Player)"})
                    with urlopen(req, timeout=5) as resp:
                        data = resp.read()
                    if _set_pixbuf_from_bytes(data):
                        return
                except Exception as e:
                    print("Cover art URL fetch failed:", url, e)
    


    def _set_cover_from_bytes(self, data: bytes):
        try:
            pl = GdkPixbuf.PixbufLoader.new()
            pl.write(data)
            pl.close()
            pix = pl.get_pixbuf()
            if pix:
                scaled = pix.scale_simple(140, 140, GdkPixbuf.InterpType.BILINEAR)
                self.cover_image.set_from_pixbuf(scaled)
        except Exception as e:
            print("Cover decode error:", e)

    def _load_cover_from_file(self, path):
        if not (EYE3D_OK and path.lower().endswith('.mp3')):
            return
        try:
            af = eyed3.load(path)
            if af and af.tag and af.tag.images:
                img = af.tag.images[0]
                data = img.image_data
                if data:
                    self._set_cover_from_bytes(data)
        except Exception as e:
            print("Cover read (eyed3) error:", e)

    def _notify(self, title, msg):
        if NOTIFY_OK:
            try:
                n = notify2.Notification(title, msg, "audio-x-generic")
                n.show()
            except Exception:
                pass

    # -------- PLAYBACK CMDS --------
    def _play(self):
        sel = self.playlist_view.get_selection()
        model, it = sel.get_selected()
        if it:
            if model is self.playlist_filter:
                it = model.convert_iter_to_child_iter(it)
            self.current_iter = it
        elif not self.current_iter or not self.playlist_store.iter_is_valid(self.current_iter):
            self.current_iter = self.playlist_store.get_iter_first()
            if not self.current_iter:
                self._error("Playlist is empty")
                return

        if not self.current_iter or not self.playlist_store.iter_is_valid(self.current_iter):
            self._error("Invalid track selected")
            return

        path = self.playlist_store.get_value(self.current_iter, 0)
        title = self.playlist_store.get_value(self.current_iter, 4)
        artist = self.playlist_store.get_value(self.current_iter, 1)
        album = self.playlist_store.get_value(self.current_iter, 3)

        self.now_title.set_markup(f"<span size='large' weight='bold'>{title}</span>")
        self.now_artist.set_markup(f"<span size='small'>Artist: {artist}</span>")
        self.now_album.set_markup(f"<span size='small'>Album: {album}</span>")

        self.cover_image.clear()
        if path and not path.startswith(('http://', 'https://')):
            self._load_cover_from_file(path)
        else:
            self.current_uri = path

        try:
            self.playbin.set_state(Gst.State.NULL)
            if path.startswith(('http://', 'https://')):
                uri = path
            else:
                uri = f"file://{quote(os.path.abspath(path))}"
            self.playbin.set_property("uri", uri)
            ret = self.playbin.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                self._error("Failed to start playback")
                self._stop()
                return
        except Exception as e:
            self._error(f"Playback error: {str(e)}")
            self._next()  # Skip to next track instead of stopping
            return

        self.btn_play.set_sensitive(False)
        self.btn_pause.set_sensitive(True)
        self.btn_stop.set_sensitive(True)

        self._notify("Now Playing", f"{title}\nby {artist}")

    def _toggle_pause(self):
        st = self.playbin.get_state(0)[1]
        if st == Gst.State.PLAYING:
            self.playbin.set_state(Gst.State.PAUSED)
            self.btn_play.set_sensitive(True)
            self.btn_pause.set_sensitive(False)
            self._notify("Paused", self.playlist_store.get_value(self.current_iter, 4) if self.current_iter else "")
        elif st == Gst.State.PAUSED:
            self.playbin.set_state(Gst.State.PLAYING)
            self.btn_play.set_sensitive(False)
            self.btn_pause.set_sensitive(True)

    def _stop(self):
        self.playbin.set_state(Gst.State.NULL)
        self.btn_play.set_sensitive(True)
        self.btn_pause.set_sensitive(False)
        self.btn_stop.set_sensitive(False)
        self.progress_scale.set_value(0)
        self.time_label.set_markup("<span size='small'>00:00 / 00:00</span>")
        self.pos_label.set_text("00:00")
        self.dur_label.set_text("00:00")

    def _next(self):
        if not self.current_iter or not self.playlist_store.iter_is_valid(self.current_iter):
            self.current_iter = self.playlist_store.get_iter_first()
        else:
            if self.repeat_mode == "one":
                self._play()
                return
            nxt = self.playlist_store.iter_next(self.current_iter)
            if not nxt:
                if self.repeat_mode == "all":
                    nxt = self.playlist_store.get_iter_first()
            self.current_iter = nxt
        if self.current_iter:
            self._play()
        else:
            self._stop()

    def _prev(self):
        if not self.current_iter or not self.playlist_store.iter_is_valid(self.current_iter):
            self.current_iter = self.playlist_store.get_iter_first()
        else:
            path = self.playlist_store.get_path(self.current_iter)
            if path and path.get_indices()[0] > 0:
                idx = path.get_indices()[0] - 1
                self.current_iter = self.playlist_store.get_iter((idx,))
        if self.current_iter:
            self._play()

    def _toggle_mute(self):
        self.muted = not self.muted
        self.playbin.set_property("mute", self.muted)
        self.mute_btn.set_label("🔇" if self.muted else "🔊")

    def _shuffle(self):
        items = [row[:] for row in self.playlist_store]
        random.shuffle(items)
        self.current_iter = None  # Reset iterator
        self.playlist_store.clear()
        for it in items:
            self.playlist_store.append(it)
        self._update_stats()
        self._notify("Playlist Shuffled", f"{len(items)} tracks")

    # -------- TIME / SEEK --------
    def _tick_time(self):
        st = self.playbin.get_state(0)[1]
        if st == Gst.State.PLAYING and not self.seeking:
            okp, pos = self.playbin.query_position(Gst.Format.TIME)
            okd, dur = self.playbin.query_duration(Gst.Format.TIME)
            if okp and okd and dur > 0:
                ps = pos // Gst.SECOND
                ds = dur // Gst.SECOND
                self.progress_scale.set_range(0, ds)
                self.progress_scale.set_value(ps)
                pos_str = f"{int(ps//60):02d}:{int(ps%60):02d}"
                dur_str = f"{int(ds//60):02d}:{int(ds%60):02d}"
                self.pos_label.set_text(pos_str)
                self.dur_label.set_text(dur_str)
                if self.show_remaining:
                    rs = max(0, ds - ps)
                    self.time_label.set_markup(f"<span size='small'>-{int(rs//60):02d}:{int(rs%60):02d} / {dur_str}</span>")
                else:
                    self.time_label.set_markup(f"<span size='small'>{pos_str} / {dur_str}</span>")
        return True

    def _on_seek(self, scale):
        if self.seeking:
            val = scale.get_value()
            self.playbin.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, int(val) * Gst.SECOND)

    # -------- RECENT / DIALOGS --------
    def _open_dialog(self, btn):
        dlg = Gtk.FileChooserDialog(title="Open Audio or Playlist", parent=self.window, action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
        dlg.set_select_multiple(True)
        filt_a = Gtk.FileFilter()
        filt_a.set_name("Audio files")
        for ext in [".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus"]:
            filt_a.add_pattern(f"*{ext}")
            filt_a.add_pattern(f"*{ext.upper()}")
        dlg.add_filter(filt_a)
        filt_pl = Gtk.FileFilter()
        filt_pl.set_name("Playlists")
        [filt_pl.add_pattern(p) for p in ("*.m3u", "*.m3u8", "*.pls")]
        dlg.add_filter(filt_pl)
        if dlg.run() == Gtk.ResponseType.OK:
            for p in dlg.get_filenames():
                if p.lower().endswith((".m3u", ".m3u8", ".pls")):
                    self._parse_playlist_file(p)
                else:
                    self._append_track(p)
        dlg.destroy()

    def _parse_playlist_file(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            added = 0
            self.current_iter = None  # Reset iterator
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.startswith(('http://', 'https://')) or os.path.exists(line):
                    self._append_track(line)
                    added += 1
            self._add_recent(path)
            self._notify("Playlist Loaded", f"{added} tracks")
        except Exception as e:
            self._error(f"Error loading playlist: {e}")

    def _add_recent(self, path):
        rec = self.config.get("recent_playlists", [])
        if path in rec:
            rec.remove(path)
        rec.insert(0, path)
        self.config["recent_playlists"] = rec[:10]
        self._load_recent_playlists_into_combo()

    def _load_recent_playlists_into_combo(self):
        if not hasattr(self, 'recent_combo'):
            return
        model = self.recent_combo.get_model()
        while self.recent_combo.get_active_text() is not None and model.iter_n_children(None) > 1:
            self.recent_combo.remove(1)
        for p in self.config.get("recent_playlists", []):
            if os.path.exists(p):
                self.recent_combo.append_text(os.path.basename(p))

    def _load_recent_from_combo(self, combo):
        a = combo.get_active()
        if a > 0:
            p = self.config.get("recent_playlists", [])[a-1]
            if os.path.exists(p):
                self._parse_playlist_file(p)

    def _clear_recent(self, btn):
        self.config["recent_playlists"] = []
        self._load_recent_playlists_into_combo()

    # -------- HELPERS --------
    def _error(self, msg):
        dlg = Gtk.MessageDialog(parent=self.window, flags=Gtk.DialogFlags.MODAL, type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK, message_format=msg)
        dlg.run()
        dlg.destroy()

    def _on_destroy(self, *a):
        try:
            self.playbin.set_state(Gst.State.NULL)
        except Exception:
            pass
        self._save_config()
        Gtk.main_quit()


def main():
    GObject.threads_init()
    app = MusicPlayer()
    Gtk.main()


if __name__ == "__main__":
    main()
