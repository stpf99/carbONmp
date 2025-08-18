import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Gst', '1.0')

from gi.repository import Gtk, Gdk, GObject, GLib, Gst, GdkPixbuf
import os
import json
import random
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


class MusicPlayer:
    """
    Carbon Music Player — wersja:
    - okładka w Now Playing także zdalnie (URL w metadanych streamów),
    - wizualizacje GStreamera (wykrywane automatycznie) zamiast rysowania Cairo,
    - rozbudowane presety EQ (3 i 10 pasm).
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

    def _load_config(self):
        self.config = {
            "recent_playlists": [],
            "last_volume": 0.6,
            "eq_ui": "10-Band",
            "eq_3": [0, 0, 0],
            "eq_10": [0] * 10,
            "show_remaining": False,
            "selected_visualizer": "None",  # nazwa elementu albo "None"
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

        self.available_visualizers = []  # [(name, longname)]
        self.selected_visualizer = self.config.get("selected_visualizer", "None")

    # -------- UI --------
    def _build_window(self):
        self.window = Gtk.Window()
        self.window.set_title("Music Player - Carbon Edition v4.0")
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
        self.search_entry.set_placeholder_text("Szukaj w playliście…")
        self.search_entry.connect("changed", lambda e: self.playlist_filter.refilter())
        hb.pack_end(self.search_entry, False, False, 0)

        open_btn = Gtk.Button()
        open_btn.set_image(Gtk.Image.new_from_icon_name("document-open", Gtk.IconSize.LARGE_TOOLBAR))
        open_btn.set_tooltip_text("Otwórz pliki / playlistę")
        open_btn.connect("clicked", self._open_dialog)
        hb.pack_end(open_btn, False, False, 0)

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
        self.recent_combo.append_text("Wybierz ostatnią playlistę…")
        self.recent_combo.set_active(0)
        self.recent_combo.connect("changed", self._load_recent_from_combo)
        clear_recent = Gtk.Button.new_with_label("Wyczyść listę")
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

        toggle_remaining = Gtk.Button.new_with_label("Pokaż/Ukryj pozostały czas")
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

        self.viz_combo = Gtk.ComboBoxText()
        self.viz_combo.connect("changed", self._on_visualizer_changed)
        vbox.pack_start(self.viz_combo, False, False, 0)

        self.viz_video_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.viz_video_box.set_size_request(-1, 260)
        vbox.pack_start(self.viz_video_box, True, True, 0)

        viz_frame.add(vbox)
        right.pack_start(viz_frame, True, True, 0)

        h.pack_start(right, True, True, 0)
        self.main_box.pack_start(h, True, True, 0)

    def _apply_css(self):
        css = b"""
        window { background: #202124; }
        button { background: #3a3d40; color: #fff; border: 1px solid #5f6368; border-radius: 6px; padding: 6px; }
        button:hover { background: #44474a; }
        entry { background: #2b2f33; color: #fff; border: 1px solid #5f6368; border-radius: 6px; padding: 5px; }
        label { color: #e8eaed; }
        frame { background: #26282b; border: 1px solid #5f6368; border-radius: 8px; }
        frame > label { background: #3a3d40; color: #fff; padding: 3px 7px; border-radius: 6px; }
        scale trough { background: #2b2f33; border: 1px solid #5f6368; min-height: 10px; }
        scale slider { background: #8ab4f8; border: 1px solid #aab4be; border-radius: 8px; min-width: 16px; min-height: 16px; }
        """
        prov = Gtk.CssProvider()
        prov.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

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
        for i, title in enumerate(["File", "Artist", "Genre", "Album", "Title"]):
            r = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(title, r, text=i)
            col.set_resizable(True)
            col.set_sort_column_id(i)
            self.playlist_view.append_column(col)
        self.playlist_view.connect("row-activated", self._on_row_activated)

    def _playlist_toolbar(self):
        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_file = Gtk.Button.new_with_label("Add File")
        add_file.connect("clicked", self._add_file)
        add_dir = Gtk.Button.new_with_label("Add Folder")
        add_dir.connect("clicked", self._add_folder)
        save_pl = Gtk.Button.new_with_label("Save Playlist")
        save_pl.connect("clicked", self._save_playlist)
        clear_pl = Gtk.Button.new_with_label("Clear")
        clear_pl.connect("clicked", lambda b: (self.playlist_store.clear(), self._update_stats()))

        sort_combo = Gtk.ComboBoxText()
        sort_combo.append_text("Sort by…")
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
            for p in dlg.get_filenames():
                self._append_track(p)
        dlg.destroy()

    def _add_folder(self, btn):
        dlg = Gtk.FileChooserDialog(title="Add Folder", parent=self.window, action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
        if dlg.run() == Gtk.ResponseType.OK:
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

    def _append_track(self, path):
        if path.startswith(('http://', 'https://')):
            title = os.path.basename(path.split('?')[0]) or "Stream"
            self.playlist_store.append([path, "Online", "Stream", "Online", title])
        else:
            artist = genre = album = "Unknown"
            title = os.path.basename(path)
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
        self._play()

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
        autofit_btn.set_tooltip_text("Dopasuj suwaki EQ do bieżącego widma")
        autofit_btn.connect("clicked", lambda b: self._autofit_eq_from_spectrum())
        autofit_btn.set_sensitive(False)  # Disabled due to spectrum removal
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
            sc.set_inverted(True)
            sc.set_value(values[i])
            sc.set_size_request(36, 160)
            sc.connect("value-changed", lambda s, idx=i: self._on_eq_slider(idx, s.get_value()))
            vb.pack_start(lbl, False, False, 0)
            vb.pack_start(sc, True, True, 0)
            self.eq_sliders_box.pack_start(vb, False, False, 0)
            self.eq_sliders.append(sc)

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

    def _autofit_eq_from_spectrum(self):
        self._notify("AutoFit EQ Unavailable", "Spectrum processing is disabled in this configuration.")
        return

    # -------- GSTREAMER --------
    def _build_gstreamer(self):
        self.playbin = Gst.ElementFactory.make("playbin", "playbin")
        self.playbin.set_property("volume", self.config.get("last_volume", 0.6))

        # --- audio processing bin: audioconvert -> audioresample -> eq -> sink
        self.audio_bin = Gst.Bin.new("audio_bin")
        ac1 = Gst.ElementFactory.make("audioconvert", None)
        ar1 = Gst.ElementFactory.make("audioresample", None)

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

        for el in [ac1, ar1, self.eq_element, ac2, ar2, sink]:
            if el:
                self.audio_bin.add(el)

        chain = [ac1, ar1, self.eq_element, ac2, ar2, sink]
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
        """Zwraca listę ([(name, longname), ...]) elementów z klasy 'Visualization'."""
        out = []
        try:
            reg = Gst.Registry.get()
            feats = reg.get_feature_list(Gst.ElementFactory)
            print("Scanning for visualization plugins...")
            for f in feats:
                try:
                    klass = f.get_klass() or ""
                    name = f.get_name()
                    if ("Visualization" in klass or "Visual" in klass or "visual" in klass.lower() or
                        name in ["goom", "goom2k1", "synaesthesia", "monoscope", "libvisual_lv_scope", "libvisual_lv_analyzer"]):
                        elem = Gst.ElementFactory.make(name, None)
                        if elem:
                            longname = f.get_longname() or name
                            out.append((name, longname))
                            print(f"Found visualizer: {name} ({longname})")
                        else:
                            print(f"Failed to create element for: {name}")
                except Exception as e:
                    print(f"Error checking feature {f.get_name()}: {e}")
            if not out:
                print("No visualization plugins found. Install GStreamer visualization plugins (e.g., gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, gstreamer1.0-libvisual).")
                self._notify("Warning", "No visualization plugins detected. Install GStreamer plugins like gstreamer1.0-plugins-good or gstreamer1.0-libvisual.")
        except Exception as e:
            print("Visualizer detection error:", e)
            self._notify("Error", f"Visualizer detection failed: {str(e)}")

        seen = set()
        uniq = []
        for name, longname in out:
            if name not in seen:
                seen.add(name)
                uniq.append((name, longname))
        uniq.sort(key=lambda x: x[0].lower())
        return uniq

    def _fill_visualizer_combo(self):
        if hasattr(self.viz_combo, 'disconnect_by_func'):
            self.viz_combo.disconnect_by_func(self._on_visualizer_changed)
        self.viz_combo.remove_all()
        self.viz_combo.append_text("None")
        for name, longname in self.available_visualizers:
            self.viz_combo.append_text(f"{name} — {longname}")
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

    def _apply_visualizer(self, vis_name: str):
        """Podpina/odpina wizualizację GStreamera do playbin."""
        self.selected_visualizer = vis_name
        try:
            current_state = self.playbin.get_state(0)[1]
            self.playbin.set_state(Gst.State.PAUSED)

            if vis_name == "None":
                try:
                    self.playbin.set_property("vis-plugin", None)
                except Exception as e:
                    print("Clear vis-plugin error:", e)
            else:
                elem = Gst.ElementFactory.make(vis_name, None)
                if not elem:
                    print("Cannot create visualizer:", vis_name)
                    self.playbin.set_property("vis-plugin", None)
                else:
                    try:
                        self.playbin.set_property("vis-plugin", elem)
                    except Exception as e:
                        print("Set vis-plugin error:", e)
                        self.playbin.set_property("vis-plugin", None)

            try:
                flags = self.playbin.get_property("flags")
                self.playbin.set_property("flags", int(flags) | 0x0008)
            except Exception as e:
                print("Cannot set playbin VIS flag:", e)

            if current_state == Gst.State.PLAYING:
                self.playbin.set_state(Gst.State.PLAYING)
            else:
                self.playbin.set_state(current_state)
        except Exception as e:
            print("Apply visualizer error:", e)

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
                    print("EQ set error (3)", i, e)

    # -------- BUS / TAGS --------
    def _on_bus(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS:
            self._next()
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print("GStreamer ERROR:", err, debug)
            self._stop()
            self._notify("Playback Error", str(err))
        elif t == Gst.MessageType.TAG:
            taglist = message.parse_tag()
            self._update_from_tags(taglist)
            self._maybe_update_cover_from_tags(taglist)

    def _update_from_tags(self, taglist):
        if self.current_iter:
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
        """Aktualizuje cover art – obsługuje lokalne tagi GStreamer, URL-e oraz zdalne ID3."""
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
    
        for key in ("coverart-url", "image"):
            ok, url = taglist.get_string(key)
            if ok and url and url.startswith(("http://", "https://")):
                try:
                    with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0 (Carbon Player)"}, timeout=5)) as resp:
                        data = resp.read()
                        if _set_pixbuf_from_bytes(data):
                            return
                except Exception as e:
                    print("Cover art URL fetch failed:", url, e)
    
        if current_uri and current_uri.lower().startswith(("http://", "https://")) and EYE3D_OK:
            try:
                import io
                with urlopen(Request(current_uri, headers={"User-Agent": "Mozilla/5.0 (Carbon Player)"}, timeout=5)) as resp:
                    data = resp.read()
                mp3file = eyed3.load(io.BytesIO(data))
                if mp3file and mp3file.tag and mp3file.tag.images:
                    for img in mp3file.tag.images:
                        if _set_pixbuf_from_bytes(img.image_data):
                            return
            except Exception as e:
                print("Remote ID3 cover fetch failed:", e)
    
        if current_uri and current_uri.lower().startswith(("http://", "https://")):
            self._notify("No Cover Art", "Could not retrieve cover art for this stream.")

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
        elif not self.current_iter:
            self.current_iter = self.playlist_store.get_iter_first()
            if not self.current_iter:
                self._error("Playlist is empty")
                return

        if not self.current_iter:
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

        self.playbin.set_state(Gst.State.NULL)
        if path.startswith(('http://', 'https://')):
            uri = path
        else:
            uri = f"file://{quote(os.path.abspath(path))}"
        self.playbin.set_property("uri", uri)
        self.playbin.set_state(Gst.State.PLAYING)

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
