#!/usr/bin/env python3

# lyse | realtime tui lyrics for your favorite songs, directly in the terminal.
# make a pr if you have something to share, or suggest cool stuff in discussions
# https://github.com/snoowfall/lyse 

__version__ = "2.2.1"
# full rewrite done in 2.0.0 to remove traces of ex-fork code
# qol updates in 2.1.0
# stdout piping in 2.1.1 (suggested by u/shadowe1ite) 
# 2.1.2-2.1.3 fixes 
# 2.2.0 customizable colors through the json (~/.config/lyse/), thanks hooxoo
# 2.2.1 mpris fix

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
import argparse
import shutil

LRCLIB_URL = "https://lrclib.net/api/get"
POLL_INTERVAL = 0.25 # :3
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

        parts = meta.split("|", 4)
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
        colors = saved.get("colors", {})
        self.col_current      = colors.get("current", 231)
        self.col_ahead_close  = colors.get("ahead_close", 252)
        self.col_ahead_mid    = colors.get("ahead_mid", 249)
        self.col_ahead_far    = colors.get("ahead_far", 245)
        self.col_behind_close = colors.get("behind_close", 243)
        self.col_behind_mid   = colors.get("behind_mid", 239)
        self.col_behind_far   = colors.get("behind_far", 237)
        self.col_bar_filled   = colors.get("bar_filled", 249)
        self.col_bar_empty    = colors.get("bar_empty", 243)
        self.col_title        = colors.get("title", 252)
        self.col_artist       = colors.get("artist", 252)
        self.col_status       = colors.get("status", 252)
        
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
                "colors": {
                    "current":      self.col_current,
                    "ahead_close":  self.col_ahead_close,
                    "ahead_mid":    self.col_ahead_mid,
                    "ahead_far":    self.col_ahead_far,
                    "behind_close": self.col_behind_close,
                    "behind_mid":   self.col_behind_mid,
                    "behind_far":   self.col_behind_far,
                    "bar_filled":   self.col_bar_filled,
                    "bar_empty":    self.col_bar_empty,
                    "title":        self.col_title,
                    "artist":       self.col_artist,
                    "status":       self.col_status,
                },
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

    def _poll(self): # should be fixed to support everything now idk
        while self.running:
            track = self.poller.now_playing()
            with self.lock:
                prev_track = self.track
                self.track = track
                if track:
                    id_changed    = track["track_id"] and track["track_id"] != self._last_id
                    title_changed = track["title"] != (prev_track or {}).get("title")
                    if id_changed or title_changed:
                        self._last_id = track["track_id"]
                        self.lyrics = [(0, "loading lyrics, hang on")]
                        self.synced = False
                        t = track.copy()
                        def _do_fetch(t=t):
                            lyrics, synced = self._fetch_lyrics(t["title"], t["artist"], t["album"], t["duration"])
                            with self.lock:
                                if self._last_id == t["track_id"] or self.track and self.track["title"] == t["title"]:
                                    self.lyrics = lyrics
                                    self.synced = synced
                        threading.Thread(target=_do_fetch, daemon=True).start()
            time.sleep(POLL_INTERVAL)

    def _apply_colors(self, scr):
        if curses.COLORS < 8:
            for i in range(1, 8):
                curses.init_pair(i, curses.COLOR_WHITE, -1)
            return
    
        curses.init_pair(1, self.col_current, -1)
        curses.init_pair(2, self.col_ahead_close, -1)
        curses.init_pair(3, self.col_ahead_mid, -1)
        curses.init_pair(4, self.col_ahead_far, -1)
        curses.init_pair(5, self.col_behind_close, -1)
        curses.init_pair(6, self.col_behind_mid, -1)
        curses.init_pair(7, self.col_behind_far, -1)
        curses.init_pair(8, self.col_bar_filled, -1)
        curses.init_pair(9, self.col_bar_empty, -1)
        curses.init_pair(10, self.col_title, -1)
        curses.init_pair(11, self.col_artist, -1)
        curses.init_pair(12, self.col_status, -1)

    def _place_line(self, text, width):
        if self.lyrics_centered:
            x = max(0, (width - len(text)) // 2)
        else:
            x = 0
        return x, text[:width - x - 1 or 1]

    def run(self):
        threading.Thread(target=self._poll, daemon=True).start()
        curses.wrapper(self._main_loop)

    def run_pipe_mode(self, live=False):
        self.offset = self._load_settings().get("offset", 0.0)  # probably will help someone someday
        track = self.poller.now_playing()
        if not track:
            print("No track playing", file=sys.stderr)
            sys.exit(1)
    
        self.lyrics, self.synced = self._fetch_lyrics(
            track["title"], track["artist"], track["album"], track["duration"]
        )
    
        if live:
            last_line = None
            try:
                while True:
                    track = self.poller.now_playing()
                    if not track:
                        if last_line is not None:   
                            print("nothing playing")
                            sys.stdout.flush()
                            last_line = None
                        time.sleep(2)
                        continue
    
                    progress = track["progress"] + self.offset
                    current = self._get_current_lyric(progress)
    
                    if current != last_line:
                        print(current)
                        sys.stdout.flush()
                        last_line = current
    
                    time.sleep(0.8)
            except KeyboardInterrupt:
                print("\nStopped", file=sys.stderr)
        else: # oneshot as in the game oneshot
            progress = track["progress"] + self.offset
            current = self._get_current_lyric(progress)
            print(current)

    def _get_current_lyric(self, progress):
        if not self.lyrics:
            return "No lyrics"
    
        if not self.synced:
            return " | ".join(text for _, text in self.lyrics) or "No lyrics"
    
        current = "♪"
        for ts, text in self.lyrics:
            if ts > progress:
                break
            current = text
        return current.strip() or "♪"
    
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

            if key == ord('k'):
                self.offset = round(self.offset + OFFSET_STEP, 2)
                self._save_settings()
            if key == ord('j'):
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

            if key == curses.KEY_RIGHT:
                subprocess.Popen(["playerctl", "position", f"{5}+"], stderr=subprocess.DEVNULL)
            if key == curses.KEY_LEFT:
                subprocess.Popen(["playerctl", "position", f"{5}-"], stderr=subprocess.DEVNULL)

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
                msg = idles[(int(time.time()) // 5) % len(idles)]
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
                scr.addstr(0, title_x, title,  curses.color_pair(10) | curses.A_BOLD)
                if artist and title_x + len(title) + len(artist) < status_x - 2:
                    scr.addstr(0, title_x + len(title), artist, curses.color_pair(11) | curses.A_DIM)

                scr.addstr(0, status_x, status, curses.color_pair(12) | curses.A_DIM)

                bar_left = 2
                bar_w    = w - 4          
                bar_w    = max(1, w - 4) 
                                
                prog = track["progress"]
                dur  = track["duration"] or 1
                filled_w = int(bar_w * min(prog / dur, 1))
                                
                bar_filled   = "━" * filled_w
                bar_unfilled = "━" * (bar_w - filled_w)
                                
                scr.addstr(1, bar_left, bar_filled,   curses.color_pair(8))
                if bar_unfilled:
                    scr.addstr(1,bar_left + filled_w, bar_unfilled, curses.color_pair(9) | curses.A_DIM)
                                
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
                    line = f"  {text}"
                    attr = curses.color_pair(1)
                else:
                    if dist == 0:
                        label = text.upper() if self.upper_current else text
                        line = f" ❯ {label}"
                        attr = curses.color_pair(1) | (curses.A_BOLD if self.bold_current else 0)
                    elif dist > 0:
                        line = f"  {text}"
                        if self.dim_inactive:
                            attr = curses.color_pair(2 if dist == 1 else 3 if dist <= 3 else 4)
                        else:
                            attr = curses.color_pair(1) # forgot to add these back in previously lolz
                    else:
                        line = f"  {text}"
                        if self.dim_inactive:
                            attr = curses.color_pair(5 if dist == -1 else 6 if dist >= -3 else 7)
                        else:
                            attr = curses.color_pair(1)

                x, clipped = self._place_line(line, w)
                scr.addstr(lyric_start + row, x, clipped, attr)

            scr.refresh()


def main():
    if not shutil.which("playerctl"):
        print("playerctl not found, install it first")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Lyse - terminal lyrics viewer")
    parser.add_argument('--reset', action='store_true', help="Reset settings")
    parser.add_argument('--pipe', action='store_true', help="Output current lyrics to stdout (non-interactive)")
    parser.add_argument('--live', action='store_true', help="With --pipe: continuously update stdout")
    args = parser.parse_args() 

    if args.reset:
        try:
            os.remove(CONFIG_FILE)
            print("config nuked")
        except:
            print("no config found")
        return
        
    if args.pipe:
        lyse = Lyse()
        lyse.run_pipe_mode(live=args.live)
        return
    
    signal.signal(signal.SIGINT, lambda *a: sys.exit(0))
    Lyse().run()


if __name__ == "__main__":
    main()
