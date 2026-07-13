"""
tui.py — Textual dashboard for the ESP32 Marauder rig (wifikit's default UI).

Turns the raw Marauder serial CLI into a single-screen, target-oriented
dashboard so you needn't memorise commands or juggle multiple terminals (the
classic aircrack-ng flow: airodump in one window, aireplay in another, aircrack
in a third). Here you scan, pick a target from a live table, act on it via a
menu or hotkeys, and run the Mac-side crack — all in one place.

Threading model
--------------
Serial I/O runs in :class:`~wifikit.session.Esp32Session`'s background thread.
Incoming text is pushed to a thread-safe queue and drained on the UI thread by
a timer, so every widget mutation stays single-threaded (Textual's rule).

Selection model
--------------
Target selection uses Marauder's ``list -a`` index, because ``select -a <idx>``
expects exactly that index; stations use the ``list -c`` global index with
``select -c``. While a scan is running both tables auto-populate by polling
``list -a`` and ``list -c`` on a timer (``scanall`` only streams unindexed hits),
and they refresh once more when the scan stops. Manual refresh is still ``r``.

Capture
-------
Capture is SD-free: the board is told to stream its pcap over the same USB serial
link (Marauder's ``-serial`` flag + the ``SavePCAP`` setting). During a capture we
tap the session's raw bytes into :class:`~wifikit.capture.SavePcapStreamParser`,
which demuxes the ``[BUF/BEGIN]…[BUF/CLOSE]`` blocks into a ``.pcap`` written under
``./captures`` — then the Crack tab is pre-filled with a hashcat command.
"""

from __future__ import annotations

import asyncio
import queue
import time
from collections import deque
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    RichLog,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from .capture import (
    SNIFF_COMMAND,
    SavePcapStreamParser,
    convert_hc22000,
    looks_like_pcap,
    pcap_frame_stats,
)
from .config import CONFIG_PATH, Config, load_config, save_config
from .marauder import Station, Target, parse_list_line, parse_station_lines
from .session import Esp32Session, find_port

# The Settings tab fields, as (config attribute, widget id, label, kind). ``kind``
# is "int" | "str" | "bool" | "theme" and drives which widget is rendered and how
# its value is coerced back into the Config.
SETTINGS_FIELDS = [
    ("capture_seconds", "set_capture_seconds", "Capture duration (seconds)", "int"),
    ("auto_deauth", "set_auto_deauth", "Auto-deauth before capture", "bool"),
    ("deauth_seconds", "set_deauth_seconds", "Deauth burst (seconds)", "int"),
    ("wordlist", "set_wordlist", "Default wordlist (blank = auto)", "str"),
    ("auto_convert", "set_auto_convert", "Auto-convert to hc22000", "bool"),
    ("captures_dir", "set_captures_dir", "Capture output folder", "str"),
    ("port", "set_port", "Serial port (blank = auto-detect)", "str"),
    ("theme", "set_theme", "Theme", "theme"),
]


class ActionsScreen(ModalScreen[str]):
    """
    Modal popup listing the actions available for a selected target.

    Dismisses with the chosen action id (or ``None`` if cancelled). Openable by
    keyboard (Enter/``a``) or mouse (right-click) over a table row.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, target: Target) -> None:
        super().__init__()
        self._target = target

    def action_cancel(self) -> None:
        self.dismiss(None)

    def compose(self) -> ComposeResult:
        t = self._target
        with Vertical(id="actions_box"):
            yield Static(
                f" Target [{t.idx}] {t.name}  CH:{t.ch}  {t.rssi} dBm ",
                id="actions_title",
            )
            yield OptionList(
                Option("Select as target", id="select"),
                Option("Deauth (force disconnect)", id="deauth"),
                Option("Capture (stream handshake/PMKID to Mac)", id="capture"),
                Option("Set radio to this channel", id="channel"),
                Option("Stop all activity", id="stop"),
                id="actions_list",
            )

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)


class WifikitApp(App):
    """The main Textual application driving the ESP32 Marauder rig."""

    TITLE = "wifikit"
    SUB_TITLE = "ESP32 Marauder control deck"

    # How often (seconds) to poll ``list -a``/``list -c`` while a scan is running
    # so the target and station tables fill in live. ``scanall`` streams hits to
    # the console but only the ``list`` commands emit the indexed rows the tables
    # can parse, so we must poll them. Kept modest to avoid flooding the
    # 115200-baud serial link.
    SCAN_REFRESH_SECS = 3.0

    CSS = """
    #status { dock: top; height: 1; background: $panel; color: $text; padding: 0 1; }
    #ap_table { height: 1fr; }
    #sta_table { height: 1fr; }
    RichLog { height: 1fr; border: round $primary; }
    #actions_box { width: 56; height: auto; border: round $primary;
                   background: $surface; padding: 1; margin: 2 4; }
    #actions_title { text-style: bold; padding: 0 0 1 0; }
    #actions_list { height: auto; }
    #settings_box { padding: 1 2; }
    #settings_box Label { margin: 1 0 0 0; color: $text-muted; }
    #settings_box Input { dock: initial; width: 48; }
    #settings_box Select { width: 48; }
    Input { dock: bottom; }
    """

    BINDINGS = [
        Binding("s", "scan", "Scan"),
        Binding("x", "stop", "Stop"),
        Binding("r", "refresh", "Refresh"),
        Binding("a", "actions", "Actions"),
        Binding("d", "deauth", "Deauth"),
        Binding("c", "capture", "Capture"),
        Binding("y", "yank", "Copy"),
        Binding("ctrl+r", "reconnect", "Reconnect"),
        Binding("q", "quit", "Quit"),
        # Jump straight to a tab by number (1-5); hidden from the footer.
        Binding("1", "show_tab('targets')", "Targets", show=False),
        Binding("2", "show_tab('stations')", "Stations", show=False),
        Binding("3", "show_tab('console')", "Console", show=False),
        Binding("4", "show_tab('crack')", "Crack", show=False),
        Binding("5", "show_tab('settings')", "Settings", show=False),
    ]

    def __init__(self, port: str | None = None, demo: bool = False) -> None:
        super().__init__()
        # Persistent user settings (capture length, auto-deauth, wordlist, theme…)
        # edited from the Settings tab; the config file is created on first save.
        self.config: Config = load_config()
        # Explicit --port wins over the configured port, which wins over auto.
        self._port_arg = port or (self.config.port or None)
        # Demo mode seeds the tables with fake targets/stations and never opens a
        # serial port — for screenshots/GIFs and for trying the UI with no board.
        self.demo = demo
        self.session: Esp32Session | None = None
        self.port: str | None = "/dev/cu.usbserial-DEMO" if demo else None
        self._rxq: queue.Queue[str] = queue.Queue()
        self._linebuf = ""
        self.targets: dict[int, Target] = {}  # keyed by Marauder index
        self.aps: list[Target] = []  # display order (== table rows)
        self.stations: list[Station] = []  # display order (== station rows)
        self.scanning = False
        self.capturing = False
        # Repeating timer that polls ``list -a``/``list -c`` during a scan.
        self._scan_poll_timer = None
        # Bounded ring of recent *raw* (un-stripped) serial lines. ``list -c``
        # output is grouped by AP and indentation-significant, so its stateful
        # parser needs the original lines, not the stripped ones dispatched to
        # ``_on_line``.
        self._raw_lines: deque[str] = deque(maxlen=400)

    # ---- composition -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        # markup=False: the status text contains literal characters (bullets,
        # hint letters) that must NOT be parsed as Rich markup — otherwise a
        # fragment like "[s]can" is read as a strikethrough tag.
        yield Static("starting…", id="status", markup=False)
        with TabbedContent(initial="targets"):
            with TabPane("Targets", id="targets"):
                yield DataTable(id="ap_table", cursor_type="row", zebra_stripes=True)
            with TabPane("Stations", id="stations"):
                yield DataTable(id="sta_table", cursor_type="row", zebra_stripes=True)
            with TabPane("Console", id="console"):
                yield RichLog(
                    id="console_log", markup=False, wrap=True, auto_scroll=True
                )
                yield Input(
                    placeholder="Marauder command (e.g. scanall)…", id="cmd_input"
                )
            with TabPane("Crack", id="crack"):
                yield RichLog(id="crack_log", markup=False, wrap=True, auto_scroll=True)
                yield Input(
                    placeholder="hashcat/aircrack-ng command — press Enter to run "
                    "it on your machine (auto-filled after a capture)",
                    id="crack_input",
                )
            with TabPane("Settings", id="settings"):
                with VerticalScroll(id="settings_box"):
                    yield Static(
                        f" Settings — saved to {CONFIG_PATH} ",
                        id="settings_title",
                        markup=False,
                    )
                    for _attr, wid, label, kind in SETTINGS_FIELDS:
                        yield Label(label)
                        if kind == "bool":
                            yield Switch(id=wid)
                        elif kind == "theme":
                            current = (
                                self.config.theme
                                if self.config.theme in self.available_themes
                                else "textual-dark"
                            )
                            yield Select(
                                [(n, n) for n in sorted(self.available_themes)],
                                id=wid,
                                value=current,
                                allow_blank=False,
                            )
                        else:
                            yield Input(
                                id=wid,
                                type="integer" if kind == "int" else "text",
                            )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#ap_table", DataTable)
        table.add_columns("Idx", "CH", "ESSID / BSSID", "RSSI")
        sta = self.query_one("#sta_table", DataTable)
        sta.add_columns("Idx", "MAC", "AP", "sel")
        # Focus the table so arrow keys drive the target list right away; Tab
        # moves focus to the tab bar when you want to switch tabs.
        table.focus()
        self.query_one("#crack_log", RichLog).write(
            "Crack tab: a hashcat command is auto-filled here after a capture — "
            "just press Enter in the box below to run it (or type your own). It "
            "runs on your machine and streams here. Captures land in "
            f"./{self.config.captures_dir} (streamed over USB, no SD card)."
        )
        self._apply_theme()
        self._load_settings_form()
        if self.demo:
            self._seed_demo()
            return
        self.set_interval(0.05, self._drain_serial)
        self.connect()

    # ---- settings ----------------------------------------------------------

    def _apply_theme(self) -> None:
        """Apply the configured theme, ignoring an unknown/removed theme name."""
        if self.config.theme in self.available_themes:
            self.theme = self.config.theme

    def _load_settings_form(self) -> None:
        """Populate the Settings tab widgets from the current config."""
        for attr, wid, _label, kind in SETTINGS_FIELDS:
            if kind == "theme":
                continue  # the Select is built with its options/value in compose
            value = getattr(self.config, attr)
            widget = self.query_one(f"#{wid}")
            if kind == "bool":
                widget.value = bool(value)
            else:
                widget.value = str(value)

    def _save_setting(self, attr: str, value: object) -> None:
        """Update one config field, persist, and re-notify the user."""
        setattr(self.config, attr, value)
        save_config(self.config)
        self.notify(f"Saved: {attr} = {value}", timeout=3)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        for attr, wid, _label, kind in SETTINGS_FIELDS:
            if kind == "bool" and event.switch.id == wid:
                self._save_setting(attr, event.value)
                return

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "set_theme" and event.value != Select.BLANK:
            self.theme = str(event.value)
            self._save_setting("theme", str(event.value))

    def _seed_demo(self) -> None:
        """Populate the tables with sample data for screenshots / no-board demos."""
        self.targets = {
            0: Target(0, 6, "rb_alderson", -52),
            1: Target(1, 6, "rb_alderson", -58),
            2: Target(2, 11, "Cafe_Guest", -67),
            3: Target(3, 1, "0e:ef:15:a9:3b:d2", -81),
        }
        self.stations = [
            Station(4, "A4:83:E7:11:22:33", ap_idx=0, ap_name="rb_alderson"),
            Station(7, "DE:AD:BE:EF:00:01", ap_idx=2, ap_name="Cafe_Guest"),
        ]
        self._refresh_table()
        sta = self.query_one("#sta_table", DataTable)
        sta.clear()
        for s in self.stations:
            sta.add_row(str(s.idx), s.mac, s.ap_name or "?", "✓" if s.selected else "")
        self._log("[demo] seeded sample data — no board connected")
        self._log(">>> scanall")
        self._log("Scanning for APs and Stations. Stop with stopscan")
        # Show a realistic post-capture state in the Crack tab (for demos/GIFs).
        crack = self.query_one("#crack_log", RichLog)
        crack.write(
            "[capture] wrote captures/capture.pcap "
            "(73075 bytes, 302 frames, EAPOL: 2, valid pcap)."
        )
        crack.write("[capture] hc22000 ready (2 EAPOL) - press Enter below to crack:")
        self.query_one(
            "#crack_input", Input
        ).value = "hashcat -m 22000 captures/capture.hc22000 wordlists/rockyou.txt"
        self._update_status()

    # ---- serial plumbing ---------------------------------------------------

    def connect(self) -> None:
        """(Re)open the serial session; never crash if the board is absent."""
        if self.session:
            self.session.close()
            self.session = None
        try:
            self.port = find_port(self._port_arg)
            self.session = Esp32Session(self.port, on_data=self._rxq.put)
            self.session.open(reset=True)
            self._log(f"[connected {self.port} @ 115200]")
        except SystemExit as exc:
            self.port = None
            self._log(f"[not connected] {exc}")
        self._update_status()

    def _drain_serial(self) -> None:
        """Timer callback: pull queued serial text, split to lines, dispatch."""
        got = False
        try:
            while True:
                self._linebuf += self._rxq.get_nowait()
                got = True
        except queue.Empty:
            pass
        if not got:
            return
        *lines, self._linebuf = self._linebuf.split("\n")
        log = self.query_one("#console_log", RichLog)
        for line in lines:
            log.write(line)
            # Keep the raw (indented) line for the stateful ``list -c`` parser…
            self._raw_lines.append(line)
            # …and dispatch the stripped form for single-line AP/status parsing.
            self._on_line(line.strip())
        # Re-derive the station table from the recent raw buffer. Skipped during
        # a capture, when the console carries binary pcap noise, not list output.
        if not self.capturing:
            self._refresh_stations_table()

    def _on_line(self, line: str) -> None:
        """Interpret one line of Marauder output and update UI state."""
        target = parse_list_line(line)
        if target is not None:
            self.targets[target.idx] = target
            self._refresh_table()
            return
        low = line.lower()
        if "scanning for" in low:
            self.scanning = True
            self._update_status()
            # Firmware confirmed the scan is live — start polling the indexed
            # list so the table populates as APs are discovered, no keypress.
            self._start_scan_poll()
        elif "stopping wifi" in low:
            self.scanning = False
            self._update_status()
            self._stop_scan_poll()
            # Auto-pull the indexed AP + station lists one last time so the final
            # set of discovered APs/clients lands in the tables as selectable rows.
            self.set_timer(0.8, lambda: self.tx("list -a", echo=False))
            self.set_timer(1.0, lambda: self.tx("list -c", echo=False))

    # ---- UI helpers --------------------------------------------------------

    def _refresh_table(self) -> None:
        table = self.query_one("#ap_table", DataTable)
        self.aps = sorted(self.targets.values(), key=lambda t: t.idx)
        table.clear()
        for t in self.aps:
            table.add_row(str(t.idx), str(t.ch), t.name, f"{t.rssi}")

    def _refresh_stations_table(self) -> None:
        """Rebuild the Stations table from the recent ``list -c`` raw buffer."""
        parsed = parse_station_lines(self._raw_lines)
        # Dedupe by global station index (two poll cycles may both be in the
        # ring buffer); last occurrence wins, then present in index order.
        by_idx = {s.idx: s for s in parsed}
        stations = sorted(by_idx.values(), key=lambda s: s.idx)
        # Avoid needless table churn (and cursor jumps) when nothing changed.
        if stations == self.stations:
            return
        self.stations = stations
        table = self.query_one("#sta_table", DataTable)
        table.clear()
        for s in self.stations:
            ap = s.ap_name if s.ap_name is not None else "?"
            table.add_row(str(s.idx), s.mac, ap, "✓" if s.selected else "")

    def _update_status(self) -> None:
        conn = f"● {self.port}" if (self.session or self.demo) else "○ disconnected"
        if self.capturing:
            state = "CAPTURING"
        elif self.scanning:
            state = "SCANNING"
        else:
            state = "idle"
        self.query_one("#status", Static).update(
            f" {conn}    {state}    APs: {len(self.targets)}  "
            f"STAs: {len(self.stations)}    "
            f"keys: s scan · x stop · c capture · enter actions "
        )

    def _log(self, msg: str) -> None:
        self.query_one("#console_log", RichLog).write(msg)

    def tx(self, cmd: str, echo: bool = True) -> None:
        """Send a command to the board (no-op with a notice if disconnected)."""
        if not self.session:
            self.notify("Not connected — press Ctrl-R", severity="warning")
            return
        if echo:
            self._log(f">>> {cmd}")
        self.session.send(cmd)

    def current_target(self) -> Target | None:
        """Return the Target under the table cursor, if any."""
        if not self.aps:
            return None
        row = self.query_one("#ap_table", DataTable).cursor_row
        if 0 <= row < len(self.aps):
            return self.aps[row]
        return None

    # ---- actions -----------------------------------------------------------

    def action_scan(self) -> None:
        self.targets.clear()
        self._refresh_table()
        self.tx("scanall")
        # Begin polling immediately rather than waiting for the firmware's
        # "scanning for" line, so the table starts filling right away even if
        # that confirmation string is missed. Idempotent — safe to call twice.
        self._start_scan_poll()

    def action_stop(self) -> None:
        self.tx("stopscan")
        self._stop_scan_poll()

    def _start_scan_poll(self) -> None:
        """Start (once) the repeating ``list`` poll that fills the tables live."""
        if self._scan_poll_timer is None:
            self._scan_poll_timer = self.set_interval(
                self.SCAN_REFRESH_SECS, self._poll_lists
            )

    def _poll_lists(self) -> None:
        """Ask the firmware to re-emit the indexed AP and station lists."""
        self.tx("list -a", echo=False)
        self.tx("list -c", echo=False)

    def _stop_scan_poll(self) -> None:
        """Stop the live ``list`` poll if it is running."""
        if self._scan_poll_timer is not None:
            self._scan_poll_timer.stop()
            self._scan_poll_timer = None

    def action_refresh(self) -> None:
        self.tx("list -a")
        self.tx("list -c")

    def action_reconnect(self) -> None:
        self.connect()

    def action_show_tab(self, tab: str) -> None:
        """Jump straight to a tab by id (number-key shortcut 1-5)."""
        self.query_one(TabbedContent).active = tab

    def action_yank(self) -> None:
        """
        Copy the current context to the system clipboard (vim-style ``y``).

        What gets copied depends on the active tab: the highlighted AP's
        name/channel/RSSI (Targets), the station MAC (Stations), the pre-filled
        hashcat command (Crack), the console command (Console), or the focused
        setting / config path (Settings). Uses the terminal clipboard (OSC 52).
        """
        tab = self.query_one(TabbedContent).active
        text, what = "", "text"
        if tab == "targets" and (t := self.current_target()):
            text, what = f"{t.name} CH:{t.ch} {t.rssi}dBm", "target"
        elif tab == "stations" and (s := self.current_station()):
            text, what = s.mac, "station MAC"
        elif tab == "crack":
            text, what = self.query_one("#crack_input", Input).value, "crack command"
        elif tab == "console":
            text, what = self.query_one("#cmd_input", Input).value, "command"
        elif tab == "settings":
            focused = self.focused
            if isinstance(focused, Input) and focused.value:
                text, what = focused.value, "setting"
            else:
                text, what = str(CONFIG_PATH), "config path"
        if not text:
            self.notify("Nothing to copy on this tab")
            return
        self.copy_to_clipboard(text)
        preview = text if len(text) <= 48 else text[:45] + "…"
        self.notify(f"Copied {what}: {preview}")

    def action_deauth(self) -> None:
        self._run_target_action("deauth")

    def action_capture(self) -> None:
        """Hotkey (``c``): SD-free capture of the highlighted AP."""
        self._start_capture()

    def action_actions(self) -> None:
        """Open the Actions modal for the highlighted target."""
        t = self.current_target()
        if not t:
            self.notify("No target selected — scan first (s); the table fills in live")
            return
        self.push_screen(ActionsScreen(t), self._on_action_chosen)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # Enter on an AP row opens the Actions menu; on a station row it deauths
        # that specific client.
        if event.data_table.id == "sta_table":
            self._deauth_station()
        else:
            self.action_actions()

    def current_station(self) -> Station | None:
        """Return the Station under the Stations-table cursor, if any."""
        if not self.stations:
            return None
        row = self.query_one("#sta_table", DataTable).cursor_row
        if 0 <= row < len(self.stations):
            return self.stations[row]
        return None

    def _deauth_station(self) -> None:
        """Deauth the highlighted station via its global ``select -c`` index."""
        s = self.current_station()
        if not s:
            self.notify("No station selected — scan first (s)")
            return
        # `attack -t deauth -c` targets the *selected station list* rather than
        # a whole AP, so select this station first, then fire.
        self.tx(f"select -c {s.idx}")
        self.tx("attack -t deauth -c")

    def _on_action_chosen(self, action: str | None) -> None:
        if action == "capture":
            self._start_capture()
        elif action:
            self._run_target_action(action)

    def _run_target_action(self, action: str) -> None:
        """Translate a chosen action into the right Marauder command sequence."""
        t = self.current_target()
        if not t:
            self.notify("No target selected")
            return
        seqs = {
            "select": [f"select -a {t.idx}"],
            "channel": [f"channel -s {t.ch}"],
            "deauth": [f"channel -s {t.ch}", f"select -a {t.idx}", "attack -t deauth"],
            "stop": ["stopscan"],
        }
        for cmd in seqs.get(action, []):
            self.tx(cmd)
        if action == "deauth":
            self.notify(
                f"Deauth sent to {t.name} (ch {t.ch}). No effect if the AP uses "
                "PMF/802.11w (common on mesh & WPA3).",
                timeout=6,
            )

    # ---- SD-free capture (Marauder -serial → host pcap) --------------------

    def _start_capture(self) -> None:
        """Kick off a streaming capture of the highlighted AP, if possible."""
        if self.capturing:
            self.notify("A capture is already running")
            return
        t = self.current_target()
        if not t:
            self.notify("No target selected — scan first (s), pick an AP")
            return
        if not self.session:
            self.notify("Not connected — press Ctrl-R", severity="warning")
            return
        # Make the capture visible: notify + switch to the Crack tab where the
        # live progress and result are logged (otherwise it looks like nothing
        # happened). Duration and auto-deauth come from Settings.
        extra = " (auto-deauth first)" if self.config.auto_deauth else ""
        self.notify(
            f"Capturing {t.name} (ch {t.ch}) for "
            f"{self.config.capture_seconds}s{extra} — watch the Crack tab."
        )
        self.query_one(TabbedContent).active = "crack"
        self.run_worker(self._run_capture(t), exclusive=False)

    async def _run_capture(self, target: Target) -> None:
        """
        Stream a pcap off the board via Marauder's ``-serial`` and save it.

        Taps the session's raw byte stream into a
        :class:`~wifikit.capture.SavePcapStreamParser`; optionally fires a deauth
        first (Settings → auto-deauth) to force a handshake; sniffs on the
        target's channel for ``config.capture_seconds``; then assembles the
        ``.pcap`` — no SD card. Auto-converts to ``hc22000`` and pre-fills the
        Crack tab so cracking is one Enter press.
        """
        cfg = self.config
        log = self.query_one("#crack_log", RichLog)
        parser = SavePcapStreamParser()
        # Stop the live list poll so it doesn't interleave `list` output with the
        # capture (and keep the single radio focused on the sniff).
        self._stop_scan_poll()
        self.capturing = True
        self._update_status()
        self.session.on_raw = parser.feed
        try:
            self.tx("settings -s SavePCAP true", echo=False)
            await asyncio.sleep(0.5)
            if cfg.auto_deauth:
                # Force a reassociation: deauth the AP's clients, then sniff the
                # reconnect. (No effect against PMF/802.11w networks.)
                log.write(
                    f"[capture] auto-deauth {cfg.deauth_seconds}s on ch {target.ch}…"
                )
                self.tx(f"channel -s {target.ch}", echo=False)
                self.tx(f"select -a {target.idx}", echo=False)
                self.tx("attack -t deauth", echo=False)
                await asyncio.sleep(cfg.deauth_seconds)
                self.tx("stopscan", echo=False)
                await asyncio.sleep(0.5)
            log.write(
                f"[capture] sniffing '{target.name}' ch {target.ch} for "
                f"{cfg.capture_seconds}s — needs SavePCAP + -serial firmware."
            )
            self.tx(SNIFF_COMMAND.format(channel=target.ch), echo=False)
            await asyncio.sleep(0.2)
            # Sleep in chunks for a live heartbeat — a long silent wait is exactly
            # what reads as "nothing is happening".
            elapsed = 0.0
            while elapsed < cfg.capture_seconds:
                await asyncio.sleep(min(5.0, cfg.capture_seconds - elapsed))
                elapsed += 5.0
                frames, eapol = pcap_frame_stats(parser.pcap_bytes())
                log.write(
                    f"[capture] {min(elapsed, cfg.capture_seconds):.0f}/"
                    f"{cfg.capture_seconds}s — {frames} frames, EAPOL {eapol}"
                )
            self.tx("stopscan", echo=False)
            await asyncio.sleep(0.5)
        finally:
            self.session.on_raw = None
            self.capturing = False
            self._update_status()

        pcap = parser.pcap_bytes()
        if not pcap:
            log.write(
                "[capture] no pcap bytes received. Confirm the firmware supports "
                "-serial and that there was traffic on the channel."
            )
            self.notify("Capture produced no frames", severity="warning")
            return
        outdir = Path(cfg.captures_dir)
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / f"capture-{int(time.time())}.pcap"
        out.write_bytes(pcap)
        frames, eapol = pcap_frame_stats(pcap)
        valid = "valid" if looks_like_pcap(pcap) else "UNRECOGNISED"
        log.write(
            f"[capture] wrote {out} ({len(pcap)} bytes, {frames} frames, "
            f"EAPOL: {eapol}, {valid} pcap)."
        )
        crack_input = self.query_one("#crack_input", Input)
        convert_cmd = f"hcxpcapngtool -o {out.with_suffix('.hc22000')} {out}"
        if eapol == 0:
            log.write(
                "[capture] no EAPOL captured — nothing crackable yet. Turn on "
                "auto-deauth in Settings (or press d) to force a reconnect; note "
                "PMF/802.11w networks resist this."
            )
            crack_input.value = convert_cmd
        elif cfg.auto_convert and (hc := convert_hc22000(str(out))):
            log.write(
                f"[capture] hc22000 ready ({eapol} EAPOL) — ▶ press Enter below "
                "to crack it:"
            )
            crack_input.value = f"hashcat -m 22000 {hc} {cfg.resolved_wordlist()}"
        else:
            log.write(
                "[capture] EAPOL captured — install hcxtools (brew install "
                "hcxtools), then press Enter below to convert:"
            )
            crack_input.value = convert_cmd
        self.query_one(TabbedContent).active = "crack"
        crack_input.focus()

    # ---- inputs ------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        wid = event.input.id
        # Settings fields persist on Enter and keep their value on screen.
        for attr, sid, _label, kind in SETTINGS_FIELDS:
            if wid == sid and kind in ("int", "str"):
                raw = event.value.strip()
                if kind == "int":
                    try:
                        self._save_setting(attr, int(raw))
                    except ValueError:
                        self.notify(
                            f"{attr} must be a whole number", severity="warning"
                        )
                else:
                    self._save_setting(attr, raw)
                return
        value = event.value.strip()
        event.input.value = ""
        if not value:
            return
        if wid == "cmd_input":
            self.tx(value)
        elif wid == "crack_input":
            self.run_worker(self._run_crack(value), exclusive=False)

    async def _run_crack(self, cmd: str) -> None:
        """Run a host-side shell command (hashcat/aircrack-ng) and stream output."""
        log = self.query_one("#crack_log", RichLog)
        log.write(f"$ {cmd}")
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            log.write(f"[failed to start] {exc}")
            return
        assert proc.stdout is not None
        async for raw in proc.stdout:
            log.write(raw.decode(errors="replace").rstrip("\n"))
        rc = await proc.wait()
        log.write(f"[exit {rc}]")

    def on_unmount(self) -> None:
        self._stop_scan_poll()
        if self.session:
            self.session.close()


def run(port: str | None = None, demo: bool = False) -> int:
    """Entry point: launch the TUI. Returns a process exit code."""
    WifikitApp(port=port, demo=demo).run()
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(run(sys.argv[1] if len(sys.argv) > 1 else None))
