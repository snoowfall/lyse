# lyse
Realtime synced lyrics in your terminal, for whatever's playing.

<img width="1541" height="1086" alt="2026-06-25-163007_hyprshot" src="https://github.com/user-attachments/assets/64a25cd0-8f97-475c-a62c-577c1d71ec48" />

## Install

**Requirements:** `python3`, `playerctl`

### AUR
```bash
yay -S lyse
paru -S lyse
```

### Manual
```bash
# Install playerctl
sudo pacman -S playerctl   # Arch
sudo apt install playerctl # Debian/Ubuntu

# Clone and run
git clone https://github.com/snoowfall/lyse.git --depth 1
cd lyse
chmod +x lyse.py
./lyse.py
```
<br/>

> [!TIP]
> To run `lyse` from anywhere, symlink or copy `lyse.py` to somewhere on your `$PATH`.<br/>
> ```
> ln -s $PWD/lyse.py ~/.local/bin/lyse
> ```
> **This is done automatically when installing via the AUR.**


## Keys

| Key     | Action                        |
|---------|-------------------------------|
| `j`/`k` | adjust lyric offset (±0.25s)  |
| `←`/`→` | seek ±5 seconds               |
| `u`     | toggle UI bar                 |
| `b`     | toggle bold on current line   |
| `c`     | toggle centered lyrics        |
| `U`     | toggle uppercase current line |
| `i`     | toggle dim inactive lines     |
| `/`     | search for lyrics manually    |
| `r`     | retry lyrics fetch            |
| `?`     | show help overlay             |
| `q`/Esc | quit                          |

## Arguments

```
--pipe              print the current lyric line to stdout and exit
--live              with --pipe: stream lyrics continuously as they change
--interval SECS     polling interval for --live (default: 0.8)
--offset SECS       override the lyric time offset
--player NAME       target a specific playerctl player
--reset             reset saved settings to defaults
--debug             write debug logs to ~/.cache/lyse/debug.log
```

**Example — pipe current lyric to waybar/polybar:**
```bash
lyse --pipe --live
```

## Misc

- Lyrics are fetched from [lrclib.net](https://lrclib.net) and cached at `~/.cache/lyse/`
- Settings auto-save to `~/.config/lyse/settings.json`
- Reset settings: `lyse --reset`
