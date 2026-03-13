#!/usr/bin/env python3
__version__ = "2.0.0"
# full rewrite to remove traces of ex-fork code
 
import os
import sys
import time
import threading
import signal
import urllib.request
import urllib.parse
import json
import re
import subprocess
import curses

LRCLIB_URL = "https://lrclib.net/api/get"
POLL_INTERVAL = 0.5 # :3
OFFSET_STEP = 0.25

CONFIG_DIR  = os.path.expanduser("~/.config/lyse")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")
CACHE_DIR   = os.path.expanduser("~/.cache/lyse")


class poller:
    def _cmd(self, args):
        try:
            out = subprocess.check_output(["playerctl"] + args, stderr=subprocess.DEVNULL)
            return out.decode().strip()
        except:
            return None

    def now_playing(self):
        status = self._cmd(["status"])
        if status not in ("Playing", "Paused"):
            return None

        fmt = "{{title}}|{{artist}}|{{album}}|{{mpris:length}}|{{mpris:trackid}}"
        meta = self._cmd(["metadata", "--format", fmt])
        if not meta:
            return None

        parts = meta.split("|")
        if len(parts) < 5:
            return None

        title, artist, album, length, track_id = parts

        try:
            duration = int(length) / 1_000_000
        except:
            duration = 0

        try:
            pos = float(self._cmd(["position"]) or "0")  # playerctl lies sometimes fr
        except:
            pos = 0

        return {
            "title": title,
            "artist": artist,
            "album": album,
            "duration": duration,
            "progress": pos,
            "track_id": track_id,
        }


class Lyse:
    def __init__(self):
        self.poller = poller()
        self.track = None
        self.lyrics = []
        self.synced = False
        self.lock = threading.Lock()
        self.running = True
        self._last_id = None

        saved = self._load_settings()
        self.show_ui         = saved.get("show_ui", True)
        self.lyrics_centered = saved.get("lyrics_centered", True)
        self.bold_current    = saved.get("bold_current", True)
        self.upper_current   = saved.get("upper_current", True)
        self.double_current  = False
        self.standout        = False
        self.dim_inactive    = saved.get("dim_inactive", True)
        self.offset          = saved.get("offset", 0.0)

    def _load_settings(self):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except:
            return {}

    def _save_settings(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            data = {
                "show_ui": self.show_ui,
                "lyrics_centered": self.lyrics_centered,
                "bold_current": self.bold_current,
                "upper_current": self.upper_current,
                "double_current": self.double_current,
                "standout": self.standout,
                "dim_inactive": self.dim_inactive,
                "offset": self.offset,
            }
            with open(CONFIG_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except:
            pass

    def _fetch_lyrics(self, title, artist, album="", duration=0):
        os.makedirs(CACHE_DIR, exist_ok=True)
        key = re.sub(r"[^\w]+", "_", f"{artist}_{title}").strip("_").lower()
        cache_file = os.path.join(CACHE_DIR, f"{key}.json")

        try:
            with open(cache_file) as f:
                data = json.load(f)
            if data.get("synced"):
                return self._parse_lrc(data["lyrics"]), True
            else:
                return [(0, l) for l in data["lyrics"].splitlines()], False
        except FileNotFoundError:
            pass
        except json.JSONDecodeError:
            try: os.remove(cache_file) # nuke that
            except: pass

        params = urllib.parse.urlencode({
            "track_name": title,
            "artist_name": artist,
            "album_name": album,
            "duration": int(duration),
        })

        try:
            with urllib.request.urlopen(f"{LRCLIB_URL}?{params}", timeout=6) as req:
                data = json.loads(req.read())
            if synced_lyrics := data.get("syncedLyrics"):
                with open(cache_file, "w") as f:
                    json.dump({"synced": True, "lyrics": synced_lyrics}, f)
                return self._parse_lrc(synced_lyrics), True
            if plain := data.get("plainLyrics"):
                with open(cache_file, "w") as f:
                    json.dump({"synced": False, "lyrics": plain}, f)
                return [(0, l) for l in plain.splitlines()], False
        except:
            pass

        return [(0, "no lyrics :(")], False

    def _parse_lrc(self, lrc):
        lines = []
        for line in lrc.splitlines():
            if m := re.match(r"\[(\d+):(\d+\.\d+)\](.*)", line):
                mins = int(m.group(1))
                secs = float(m.group(2))
                text = m.group(3).strip() or "♪"
                lines.append((mins * 60 + secs, text))
        return sorted(lines)

    def _poll(self):
        while self.running:
            track = self.poller.now_playing()
            with self.lock:
                self.track = track
                if track and track["track_id"] != self._last_id:
                    self._last_id = track["track_id"]
                    self.lyrics, self.synced = self._fetch_lyrics(
                        track["title"], track["artist"], track["album"], track["duration"]
                    )
            time.sleep(POLL_INTERVAL)

    def _apply_colors(self, scr):
        # no truecolor for u :/
        if curses.COLORS < 8:
            for i in range(1, 8):
                curses.init_pair(i, curses.COLOR_WHITE, -1)
            return

        term = os.getenv("TERM", "").lower()
        if "kitty" in term or "alacritty" in term:
            curses.init_pair(1, 231, -1)
        else:
            curses.init_pair(1, 255, -1)

        curses.init_pair(2, 252, -1)
        curses.init_pair(3, 249, -1)
        curses.init_pair(4, 245, -1)
        curses.init_pair(5, 240, -1)
        curses.init_pair(6, 238, -1)
        curses.init_pair(7, 236, -1)

    def _place_line(self, text, width):
        if self.lyrics_centered:
            x = max(0, (width - len(text)) // 2)
        else:
            x = 0
        return x, text[:width - x - 1 or 1]

    def run(self):
        threading.Thread(target=self._poll, daemon=True).start()
        curses.wrapper(self._main_loop)

    def _main_loop(self, scr):
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        scr.nodelay(True)
        scr.timeout(80)
        self._apply_colors(scr)

        while self.running:
            key = scr.getch()

            if key in (ord('q'), ord('Q'), 27):
                break

            if key in (curses.KEY_UP, ord('k')):
                self.offset = round(self.offset + OFFSET_STEP, 2)
                self._save_settings()
            if key in (curses.KEY_DOWN, ord('j')):
                self.offset = round(self.offset - OFFSET_STEP, 2)
                self._save_settings()

            if key == ord('u'):
                self.show_ui = not self.show_ui
                self._save_settings()
            if key == ord('c'):
                self.lyrics_centered = not self.lyrics_centered
                self._save_settings()
            if key == ord('b'):
                self.bold_current = not self.bold_current
                self._save_settings()
            if key == ord('U'):
                self.upper_current = not self.upper_current
                self._save_settings()
            if key == ord('i'):
                self.dim_inactive = not self.dim_inactive
                self._save_settings()

            with self.lock:
                track  = self.track
                lyrics = list(self.lyrics)
                synced = self.synced
                offset = self.offset

            h, w = scr.getmaxyx()
            scr.erase()

            if not track:
                idles = [
                    "nothing playing",
                    "no tunes rn",
                    "silence is golden",
                    "playerctl ghosted me again",
                    "where are the tunes"
                ]
                msg = idles[int(time.time()) % len(idles)]
                scr.addstr(h//2, max(0, (w - len(msg))//2), msg, curses.A_DIM)
                scr.refresh()
                time.sleep(0.5)
                continue

            lyric_start = 0
            if self.show_ui:
                title  = track['title'] or "Unknown Title"
                artist = f" - {track['artist']}" if track['artist'] else ""
                status = f"offset {offset:+.2f}s  q=quit"

                status_x = max(20, w - len(status) - 2)

                title_x = 2
                scr.addstr(0, title_x, title,  curses.color_pair(3) | curses.A_BOLD)
                if artist and title_x + len(title) + len(artist) < status_x - 2:
                    scr.addstr(0, title_x + len(title), artist, curses.color_pair(2) | curses.A_DIM)

                scr.addstr(0, status_x, status, curses.color_pair(2) | curses.A_DIM)

                bar_left = 2
                bar_w    = w - 4          
                bar_w    = max(30, bar_w)
                                
                prog = track["progress"]
                dur  = track["duration"] or 1
                filled_w = int(bar_w * min(prog / dur, 1))
                                
                bar_filled   = "━" * filled_w
                bar_unfilled = "━" * (bar_w - filled_w)
                                
                scr.addstr(1, bar_left, bar_filled,   curses.color_pair(4))
                if bar_unfilled:
                    scr.addstr(1, bar_left + filled_w, bar_unfilled, curses.color_pair(5) | curses.A_DIM)
                                
                lyric_start = 3
                
            progress = track["progress"] + offset
            cur_idx = 0
            if synced:
                for i, (ts, _) in enumerate(lyrics):
                    if ts <= progress:
                        cur_idx = i

            area_h = h - lyric_start
            half   = area_h // 2 + 1
            # half   = area_h // 2 for absolute center
            start  = max(0, cur_idx - half)
            end    = min(len(lyrics), start + area_h)
            start  = max(0, end - area_h)

            for row, idx in enumerate(range(start, end)):
                if lyric_start + row >= h - 1:
                    break
                ts, text = lyrics[idx]
                dist = idx - cur_idx if synced else 0

                if not synced:
                    line = f" {text}"
                    attr = curses.color_pair(1)
                else:
                    if dist == 0:
                        label = text.upper() if self.upper_current else text
                        line = f" ❯ {label}"
                        attr = curses.color_pair(1) | (curses.A_BOLD if self.bold_current else 0)
                    elif dist > 0:
                        line = f"  {text}"
                        attr = curses.color_pair(2 if dist == 1 else 3 if dist <= 3 else 4)
                    else:
                        line = f"  {text}"
                        attr = curses.color_pair(5 if dist == -1 else 6 if dist >= -3 else 7)

                x, clipped = self._place_line(line, w)
                scr.addstr(lyric_start + row, x, clipped, attr)

            scr.refresh()


def main():
    if "--reset" in sys.argv:
        try:
            os.remove(CONFIG_FILE)
            print("config nuked")
        except:
            print("no config")
        return
    
    signal.signal(signal.SIGINT, lambda *a: sys.exit(0))
    Lyse().run()


if __name__ == "__main__":
    main()
