#!/usr/bin/env python3

# lyse | realtime tui lyrics for your favorite songs, directly in the terminal.
# make a pr if you have something to share, or suggest cool stuff in discussions
# https://github.com/snoowfall/lyse

__version__ = "3.0.0"
# full rewrite done in 2.0.0 to remove traces of ex-fork code
# qol updates in 2.1.0
# stdout piping in 2.1.1 (suggested by u/shadowe1ite) 
# 2.1.2-2.1.3 fixes 
# 2.2.0 customizable colors through the json (~/.config/lyse/), thanks hooxoo
# 2.2.1 mpris fix
# 2.2.2 another mpris fix
# 3.0.0 large rewrite of important functions along with more features

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
import logging
from dataclasses import dataclass, field, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed

LRCLIB_URL    = "https://lrclib.net/api/get"
LRCLIB_FB_URL = "https://lrclib.net/api/search"
POLL_INTERVAL = 0.25
OFFSET_STEP   = 0.25
POLL_BACKOFF_MAX = 2.0

CONFIG_DIR  = os.path.expanduser("~/.config/lyse")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")
CACHE_DIR   = os.path.expanduser("~/.cache/lyse")
DEBUG_LOG   = os.path.join(CACHE_DIR, "debug.log")

logger = logging.getLogger("lyse")


@dataclass
class Colors:
    current: int = 231
    ahead_close: int = 252
    ahead_mid: int = 249
    ahead_far: int = 245
    behind_close: int = 243
    behind_mid: int = 239
    behind_far: int = 237
    bar_filled: int = 249
    bar_empty: int = 237
    title: int = 252
    artist: int = 245
    status: int = 243


@dataclass
class Config:
    show_ui: bool = True
    lyrics_centered: bool = True
    bold_current: bool = True
    upper_current: bool = True
    dim_inactive: bool = True
    offset: float  = 0.0
    colors: Colors = field(default_factory=Colors)

    @staticmethod
    def load():
        try:
            with open(CONFIG_FILE) as f:
                raw = json.load(f)
            c = Config()
            for k, v in raw.items():
                if k == "colors" and isinstance(v, dict):
                    for ck, cv in v.items():
                        if hasattr(c.colors, ck):
                            setattr(c.colors, ck, cv)
                elif hasattr(c, k):
                    setattr(c, k, v)
            return c
        except Exception:
            return Config()

    def save(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            data = asdict(self)
            with open(CONFIG_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


def _char_width(ch):
    # pretty rough but gets the job done (gotta give credit to claude for this)
    cp = ord(ch)
    if (0x1100 <= cp <= 0x115F or 0x2E80 <= cp <= 0x303E or
            0x3040 <= cp <= 0xA4CF or 0xAC00 <= cp <= 0xD7A3 or
            0xF900 <= cp <= 0xFAFF or 0xFE10 <= cp <= 0xFE19 or
            0xFE30 <= cp <= 0xFE6F or 0xFF01 <= cp <= 0xFF60 or
            0xFFE0 <= cp <= 0xFFE6 or 0x1F300 <= cp <= 0x1FAFF):
        return 2
    return 1

def _str_width(s):
    return sum(_char_width(c) for c in s)

def _clip_to_width(s, max_w):
    out, w = [], 0
    for ch in s:
        cw = _char_width(ch)
        if w + cw > max_w:
            break
        out.append(ch)
        w += cw
    return "".join(out), w

def fmt_time(secs):
    secs = max(0, int(secs))
    return f"{secs // 60}:{secs % 60:02d}"


class Poller:
    def __init__(self, player=None):
        self.player = player
        self._base = ["playerctl"]
        if player:
            self._base += ["-p", player]

    def _cmd(self, args):
        try:
            out = subprocess.check_output(self._base + args, stderr=subprocess.DEVNULL)
            return out.decode().strip()
        except Exception:
            return None

    def now_playing(self):
        status = self._cmd(["status"])
        if status not in ("Playing", "Paused"):
            return None

        fmt  = "{{title}}|{{artist}}|{{album}}|{{mpris:length}}|{{mpris:trackid}}"
        meta = self._cmd(["metadata", "--format", fmt])
        if not meta:
            return None

        parts = meta.split("|", 4)
        if len(parts) < 5:
            return None

        title, artist, album, length, track_id = parts

        try:
            duration = int(length) / 1_000_000
        except Exception:
            duration = 0

        try:
            pos = float(self._cmd(["position"]) or "0")
        except Exception:
            pos = 0

        return {
            "title":    title,
            "artist":   artist,
            "album":    album,
            "duration": duration,
            "progress": pos,
            "track_id": track_id,
            "status":   status,
        }


class Lyse:
    def __init__(self, cfg: Config, poller: Poller):
        self.cfg    = cfg
        self.poller = poller
        self.track   = None
        self.lyrics  = []
        self.synced  = False
        self.lock    = threading.Lock()
        self.running = True
        self._fetch_gen  = 0  
        self._last_id    = None
        self._poll_fail  = 0 
        self._idle_start = time.monotonic()
        self._plain_cursor = 0
        self._seek_flash     = ""
        self._seek_flash_at  = 0.0
        self._searching    = False
        self._search_buf   = ""
        self._show_help = False
        self._executor = ThreadPoolExecutor(max_workers=4)

    def _cache_key(self, title, artist, album):
        raw = f"{artist}_{title}_{album}"
        return re.sub(r"[^\w]+", "_", raw).strip("_").lower()

    def _cache_get(self, key):
        path = os.path.join(CACHE_DIR, f"{key}.json")
        try:
            with open(path) as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            try:
                os.remove(path)
            except Exception:
                pass
            return None

    def _cache_set(self, key, synced, lyrics_text, duration):
        if duration <= 0:
            return 
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = os.path.join(CACHE_DIR, f"{key}.json")
        try:
            with open(path, "w") as f:
                json.dump({"synced": synced, "lyrics": lyrics_text}, f)
        except Exception:
            pass

    def _fetch_primary(self, title, artist, album, duration):
        params = urllib.parse.urlencode({
            "track_name":  title,
            "artist_name": artist,
            "duration":    int(duration),
        })
        try:
            with urllib.request.urlopen(f"{LRCLIB_URL}?{params}", timeout=10) as r:
                data = json.loads(r.read())
            if lrc := data.get("syncedLyrics"):
                return lrc, True
            if plain := data.get("plainLyrics"):
                return plain, False
        except Exception as e:
            logger.debug("primary fetch failed: %s", e)
        return None, False

    def _fetch_fallback(self, title, artist):
        params = urllib.parse.urlencode({"q": f"{artist} {title}"})
        try:
            with urllib.request.urlopen(f"{LRCLIB_FB_URL}?{params}", timeout=10) as r:
                results = json.loads(r.read())
            for entry in results:
                if entry.get("syncedLyrics"):
                    return entry["syncedLyrics"], True
            for entry in results:
                if entry.get("plainLyrics"):
                    return entry["plainLyrics"], False
        except Exception as e:
            logger.debug("fallback fetch failed: %s", e)
        return None, False

    def _fetch_lyrics(self, title, artist, album, duration, gen):
        key = self._cache_key(title, artist, album)
        cached = self._cache_get(key)
        if cached:
            logger.debug("cache hit: %s", key)
            if cached.get("synced"):
                return self._parse_lrc(cached["lyrics"]), True
            return [(0, l) for l in cached["lyrics"].splitlines() if l.strip()], False

        # fetching happens n parallel now so it should be faster
        fut_primary  = self._executor.submit(self._fetch_primary, title, artist, album, duration)
        fut_fallback = self._executor.submit(self._fetch_fallback, title, artist)

        text, synced = None, False
        for fut in as_completed([fut_primary, fut_fallback]):
            t, s = fut.result()
            if t and (s or not text):
                text, synced = t, s
            if text and synced:
                break  # this way theres no need to wait for other

        with self.lock:
            if self._fetch_gen != gen:
                logger.debug("stale fetch discarded (gen %s != %s)", gen, self._fetch_gen)
                return None, False

        if text:
            self._cache_set(key, synced, text, duration)
            if synced:
                return self._parse_lrc(text), True
            return [(0, l) for l in text.splitlines() if l.strip()], False

        return [(0, "no lyrics :(")], False

    def _parse_lrc(self, lrc):
        lines = []
        for line in lrc.splitlines():
            # i spent a solid 15 minutes on this
            m = re.match(r"\[(\d+):(\d+(?:[.:]\d+)?)\](.*)", line)
            if not m:
                continue
            mins = int(m.group(1))
            sec_str = m.group(2).replace(":", ".")
            try:
                secs = float(sec_str)
            except ValueError:
                continue
            text = m.group(3).strip()
            lines.append((mins * 60 + secs, text or "♪"))
        return sorted(lines)

    def fetch_manual(self, query):
        if " - " in query:
            artist, title = query.split(" - ", 1)
        else:
            artist, title = "", query
        with self.lock:
            self._fetch_gen += 1
            gen = self._fetch_gen
            self.lyrics = [(0, "searching…")]
            self.synced = False

        def _do():
            lyrics, synced = self._fetch_lyrics(title.strip(), artist.strip(), "", 0, gen)
            with self.lock:
                if self._fetch_gen != gen:
                    return
                self.lyrics = lyrics if lyrics is not None else [(0, "no lyrics :(")]
                self.synced = synced if lyrics is not None else False

        threading.Thread(target=_do, daemon=True).start()

    def retry_fetch(self):
        with self.lock:
            if not self.track:
                return
            t = self.track.copy()
            self._fetch_gen += 1
            gen = self._fetch_gen
            self.lyrics = [(0, "retrying…")]
            self.synced = False
            # bust cache so we actually retry
            key = self._cache_key(t["title"], t["artist"], t["album"])
            path = os.path.join(CACHE_DIR, f"{key}.json")
            try:
                os.remove(path)
            except Exception:
                pass

        def _do():
            lyrics, synced = self._fetch_lyrics(t["title"], t["artist"], t["album"], t["duration"], gen)
            with self.lock:
                if self._fetch_gen != gen:
                    return
                self.lyrics = lyrics if lyrics is not None else [(0, "no lyrics :(")]
                self.synced = synced if lyrics is not None else False

        threading.Thread(target=_do, daemon=True).start()

    def _poll(self):
        while self.running:
            try:
                track = self.poller.now_playing()
                self._poll_fail = 0
            except Exception as e:
                self._poll_fail += 1
                logger.debug("poll error: %s", e)
                sleep = min(POLL_INTERVAL * (2 ** self._poll_fail), POLL_BACKOFF_MAX)
                time.sleep(sleep)
                continue

            with self.lock:
                prev  = self.track
                self.track = track
                if track:
                    id_changed     = track["track_id"] and track["track_id"] != self._last_id
                    title_changed  = track["title"] != (prev or {}).get("title")
                    duration_fixed = track["duration"] > 0 and (prev or {}).get("duration", 0) == 0

                    if id_changed or title_changed or (self._last_id == track["track_id"] and duration_fixed):
                        self._last_id = track["track_id"]
                        self._fetch_gen += 1
                        gen = self._fetch_gen
                        self.lyrics = [(0, "loading…")]
                        self.synced = False
                        self._plain_cursor = 0
                        t = track.copy()

                        def _do(t=t, gen=gen):
                            lyrics, synced = self._fetch_lyrics(
                                t["title"], t["artist"], t["album"], t["duration"], gen
                            )
                            with self.lock:
                                if self._fetch_gen != gen:
                                    return
                                self.lyrics = lyrics if lyrics is not None else [(0, "no lyrics :(")]
                                self.synced = synced if lyrics is not None else False

                        threading.Thread(target=_do, daemon=True).start()

            time.sleep(POLL_INTERVAL)

    def _init_colors(self, scr):
        curses.start_color()
        curses.use_default_colors()
        c = self.cfg.colors

        def safe_pair(n, fg):
            try:
                curses.init_pair(n, fg if curses.COLORS >= 256 else curses.COLOR_WHITE, -1)
            except Exception:
                curses.init_pair(n, curses.COLOR_WHITE, -1)

        safe_pair(1, c.current)
        safe_pair(2, c.ahead_close)
        safe_pair(3, c.ahead_mid)
        safe_pair(4, c.ahead_far)
        safe_pair(5, c.behind_close)
        safe_pair(6, c.behind_mid)
        safe_pair(7, c.behind_far)
        safe_pair(8, c.bar_filled)
        safe_pair(9, c.bar_empty)
        safe_pair(10, c.title)
        safe_pair(11, c.artist)
        safe_pair(12, c.status)

    def _place_line(self, text, width):
        vis_w = _str_width(text)
        if self.cfg.lyrics_centered:
            x = max(0, (width - vis_w) // 2)
        else:
            x = 0
        clipped, _ = _clip_to_width(text, width - x - 1)
        return x, clipped

    def _draw_help(self, scr, h, w):
        lines = [
            "  lyse keybinds  ",
            "",
            "  j / k      shift offset ±0.25s",
            "  ← / →      seek ±5s",
            "  u          toggle ui bar",
            "  c          toggle centering",
            "  b          toggle bold current",
            "  U          toggle uppercase current",
            "  i          toggle dim inactive",
            "  /          search lyrics",
            "  r          retry fetch",
            "  ?          toggle this help",
            "  q / esc    quit",
        ]
        bh = len(lines) + 2
        bw = max(_str_width(l) for l in lines) + 4
        by = max(0, (h - bh) // 2)
        bx = max(0, (w - bw) // 2)

        for dy in range(bh):
            try:
                scr.addstr(by + dy, bx, " " * bw, curses.color_pair(12))
            except Exception:
                pass

        for i, line in enumerate(lines):
            try:
                attr = curses.color_pair(10) | curses.A_BOLD if i == 0 else curses.color_pair(12)
                scr.addstr(by + 1 + i, bx + 2, line, attr)
            except Exception:
                pass

    def _draw_search_bar(self, scr, h, w):
        query = self._search_buf
        prompt = "/"
        line = f"{prompt}{query}"
        try:
            scr.addstr(h - 1, 0, " " * (w - 1), curses.color_pair(12))
            scr.addstr(h - 1, 0, prompt, curses.color_pair(1) | curses.A_BOLD)
            scr.addstr(h - 1, len(prompt), query[:w - len(prompt) - 2], curses.color_pair(12) | curses.A_BOLD)
            cur_x = len(prompt) + len(query[:w - len(prompt) - 2])
            scr.addstr(h - 1, cur_x, " ", curses.color_pair(1) | curses.A_REVERSE)
        except Exception:
            pass

    def _handle_key(self, key):
        cfg = self.cfg

        if self._searching:
            if key in (10, 13, curses.KEY_ENTER):
                q = self._search_buf.strip()
                self._searching  = False
                self._search_buf = ""
                if q:
                    self.fetch_manual(q)
            elif key in (27,):
                self._searching  = False
                self._search_buf = ""
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                self._search_buf = self._search_buf[:-1]
            elif 32 <= key <= 126:
                self._search_buf += chr(key)
            return

        if key in (ord('q'), ord('Q'), 27):
            self.running = False
            return

        if key == ord('/'):
            self._searching    = True
            self._search_buf   = ""
            self._show_help    = False
            return

        if key == ord('?'):
            self._show_help = not self._show_help
            return

        if key == ord('r'):
            self.retry_fetch()

        if key == ord('k'):
            cfg.offset = round(cfg.offset + OFFSET_STEP, 2)
            cfg.save()
        if key == ord('j'):
            cfg.offset = round(cfg.offset - OFFSET_STEP, 2)
            cfg.save()

        if key == ord('u'):
            cfg.show_ui = not cfg.show_ui;   cfg.save()
        if key == ord('c'):
            cfg.lyrics_centered = not cfg.lyrics_centered; cfg.save()
        if key == ord('b'):
            cfg.bold_current = not cfg.bold_current; cfg.save()
        if key == ord('U'):
            cfg.upper_current = not cfg.upper_current; cfg.save()
        if key == ord('i'):
            cfg.dim_inactive = not cfg.dim_inactive; cfg.save()

        if key == curses.KEY_RIGHT:
            subprocess.Popen(["playerctl", "position", "5+"], stderr=subprocess.DEVNULL)
            self._seek_flash    = "+5s"
            self._seek_flash_at = time.monotonic()
        if key == curses.KEY_LEFT:
            subprocess.Popen(["playerctl", "position", "5-"], stderr=subprocess.DEVNULL)
            self._seek_flash    = "-5s"
            self._seek_flash_at = time.monotonic()

        # plain mode scroll thing
        if key == curses.KEY_UP:
            self._plain_cursor = max(0, self._plain_cursor - 1)
        if key == curses.KEY_DOWN:
            with self.lock:
                llen = len(self.lyrics)
            self._plain_cursor = min(llen - 1, self._plain_cursor + 1)

    def run(self):
        threading.Thread(target=self._poll, daemon=True).start()
        curses.wrapper(self._main_loop)

    def _main_loop(self, scr):
        curses.curs_set(0)
        scr.nodelay(True)
        scr.timeout(80)
        self._init_colors(scr)

        # i still love these sm
        idle_msgs = [
            "nothing playing",
            "silence is golden",
            "no tunes rn",
            "playerctl ghosted me",
            "where are the tunes",
        ]

        while self.running:
            key = scr.getch()
            if key != -1:
                self._handle_key(key)
            if not self.running:
                break

            with self.lock:
                track  = self.track
                lyrics = list(self.lyrics)
                synced = self.synced
                offset = self.cfg.offset

            h, w = scr.getmaxyx()
            scr.erase()

            if not track:
                elapsed = int(time.monotonic() - self._idle_start)
                msg = idle_msgs[(elapsed // 5) % len(idle_msgs)]
                try:
                    scr.addstr(h // 2, max(0, (w - len(msg)) // 2), msg, curses.A_DIM)
                except Exception:
                    pass
                scr.refresh()
                time.sleep(0.5)
                continue

            self._idle_start = time.monotonic() # we reset when track appears cuz otherwise scary :)

            lyric_start = 0

            if self.cfg.show_ui:
                title  = track["title"]  or "Unknown Title"
                artist = track["artist"] or ""
                badge  = "" if synced else "  unsynced"

                left = title
                if artist:
                    left += f"  —  {artist}"

                flash_active = bool(self._seek_flash) and time.monotonic() - self._seek_flash_at < 0.5
                if not flash_active:
                    self._seek_flash = ""
                right_parts = []
                if flash_active:
                    right_parts.append(self._seek_flash)
                if offset != 0.0:
                    right_parts.append(f"offset {offset:+.2f}s")
                if badge:
                    right_parts.append(badge.strip())
                right = "  ".join(right_parts)

                try:
                    cleft, _ = _clip_to_width(left, w - len(right) - 4)
                    scr.addstr(0, 1, cleft, curses.color_pair(10) | curses.A_BOLD)
                    if right:
                        rx = w - len(right) - 1
                        if flash_active:
                            scr.addstr(0, rx, self._seek_flash,
                                       curses.color_pair(1) | curses.A_BOLD)
                            rest = right[len(self._seek_flash):]
                            if rest:
                                scr.addstr(0, rx + len(self._seek_flash), rest,
                                           curses.color_pair(12) | curses.A_DIM)
                        else:
                            scr.addstr(0, rx, right, curses.color_pair(12) | curses.A_DIM)
                except Exception:
                    pass

                prog  = track["progress"]
                dur   = track["duration"] or 1
                t_cur = fmt_time(prog)
                t_dur = fmt_time(dur)

                bar_left  = 1 + len(t_cur) + 2
                bar_right = w - len(t_dur) - 2
                bar_w     = max(1, bar_right - bar_left)
                filled_w  = int(bar_w * min(prog / dur, 1.0))

                try:
                    scr.addstr(1, 1, t_cur, curses.color_pair(12) | curses.A_DIM)
                    scr.addstr(1, bar_left, "─" * filled_w, curses.color_pair(8))
                    if bar_w - filled_w > 0:
                        scr.addstr(1, bar_left + filled_w, "─" * (bar_w - filled_w),
                                   curses.color_pair(9) | curses.A_DIM)
                    scr.addstr(1, w - len(t_dur) - 1, t_dur, curses.color_pair(12) | curses.A_DIM)
                except Exception:
                    pass

                lyric_start = 3

            progress = track["progress"] + offset
            area_h   = h - lyric_start - (1 if self._searching else 0)

            if synced:
                cur_idx = 0
                for i, (ts, _) in enumerate(lyrics):
                    if ts <= progress:
                        cur_idx = i

                half  = area_h // 2 + 1
                start = max(0, cur_idx - half)
                end   = min(len(lyrics), start + area_h)
                start = max(0, end - area_h)

                for row, idx in enumerate(range(start, end)):
                    if lyric_start + row >= h - (2 if self._searching else 1):
                        break
                    ts, text = lyrics[idx]
                    dist = idx - cur_idx

                    if dist == 0:
                        label = text.upper() if self.cfg.upper_current else text
                        line  = f" ❯ {label}"
                        attr  = curses.color_pair(1) | (curses.A_BOLD if self.cfg.bold_current else 0)
                    elif dist > 0:
                        line = f" {text}"
                        if self.cfg.dim_inactive:
                            attr = curses.color_pair(2 if dist == 1 else 3 if dist <= 3 else 4)
                        else:
                            attr = curses.color_pair(1)
                    else:
                        line = f" {text}"
                        if self.cfg.dim_inactive:
                            attr = curses.color_pair(5 if dist == -1 else 6 if dist >= -3 else 7)
                        else:
                            attr = curses.color_pair(1)

                    x, clipped = self._place_line(line, w)
                    try:
                        scr.addstr(lyric_start + row, x, clipped, attr)
                    except Exception:
                        pass

            else: # unsynced lyrics are now scrollable
                cur_idx = self._plain_cursor
                half    = area_h // 2
                start   = max(0, cur_idx - half)
                end     = min(len(lyrics), start + area_h)
                start   = max(0, end - area_h)

                for row, idx in enumerate(range(start, end)):
                    if lyric_start + row >= h - (2 if self._searching else 1):
                        break
                    _, text = lyrics[idx]
                    if idx == cur_idx:
                        line = f" {text}"
                        attr = curses.color_pair(2)
                    else:
                        line = f" {text}"
                        attr = curses.color_pair(2)

                    x, clipped = self._place_line(line, w)
                    try:
                        scr.addstr(lyric_start + row, x, clipped, attr)
                    except Exception:
                        pass

            if self._show_help:
                self._draw_help(scr, h, w)

            if self._searching:
                self._draw_search_bar(scr, h, w)

            scr.refresh()

    def run_pipe_mode(self, live=False, interval=0.8):
        track = self.poller.now_playing()
        if not track:
            print("no track playing", file=sys.stderr)
            sys.exit(1)

        with self.lock:
            self._fetch_gen += 1
            gen = self._fetch_gen

        self.lyrics, self.synced = self._fetch_lyrics(
            track["title"], track["artist"], track["album"], track["duration"], gen
        ) or ([(0, "no lyrics :(")], False)

        if live:
            last_line = None
            try:
                while True:
                    track = self.poller.now_playing()
                    if not track:
                        if last_line is not None:
                            print("", flush=True)
                            last_line = None
                        time.sleep(2)
                        continue
                    progress = track["progress"] + self.cfg.offset
                    current  = self._get_current_lyric(progress)
                    if current != last_line:
                        print(current, flush=True)
                        last_line = current
                    time.sleep(interval)
            except KeyboardInterrupt:
                pass
        else:
            progress = track["progress"] + self.cfg.offset
            print(self._get_current_lyric(progress))

    def _get_current_lyric(self, progress):
        if not self.lyrics:
            return "♪"
        if not self.synced:
            return " | ".join(t for _, t in self.lyrics) or "♪"
        current = "♪"
        for ts, text in self.lyrics:
            if ts > progress:
                break
            current = text
        return current.strip() or "♪"


def main():
    if not shutil.which("playerctl"):
        print("playerctl not found, install it first")
        sys.exit(1)

    # added debug aaand offset
    parser = argparse.ArgumentParser(description="lyse - terminal lyrics viewer")
    parser.add_argument("--reset",    action="store_true", help="reset saved settings")
    parser.add_argument("--pipe",     action="store_true", help="output current lyric to stdout")
    parser.add_argument("--live",     action="store_true", help="with --pipe: stream continuously")
    parser.add_argument("--interval", type=float, default=0.8, help="--live poll interval (default 0.8)")
    parser.add_argument("--offset",   type=float, default=None, help="override lyric offset (seconds)")
    parser.add_argument("--player",   type=str,   default=None, help="target a specific playerctl player")
    parser.add_argument("--debug",    action="store_true", help="log debug info to ~/.cache/lyse/debug.log")
    args = parser.parse_args()

    if args.debug:
        os.makedirs(CACHE_DIR, exist_ok=True)
        logging.basicConfig(filename=DEBUG_LOG, level=logging.DEBUG,
                            format="%(asctime)s %(levelname)s %(message)s")

    if args.reset:
        try:
            os.remove(CONFIG_FILE)
            print("config reset")
        except FileNotFoundError:
            print("no config found")
        return

    cfg = Config.load()
    if args.offset is not None:
        cfg.offset = args.offset

    poller = Poller(player=args.player)
    lyse   = Lyse(cfg=cfg, poller=poller)

    if args.pipe:
        lyse.run_pipe_mode(live=args.live, interval=args.interval)
        return

    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    lyse.run()


if __name__ == "__main__":
    main()
