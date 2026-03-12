# lyse
Terminal synced lyrics viewer for your currently playing music.

<img width="1313" height="757" alt="image" src="https://github.com/user-attachments/assets/efa6eff7-3a3d-4011-8bbe-3079567ac8d4" />

## Install

**Requirements:** Python 3.6+, `playerctl`

### AUR install
```bash
yay -S lyse 
paru -S lyse # for paru users
```

### Manual install
#### Install playerctl
```bash
sudo pacman -S playerctl  # Arch
sudo apt install playerctl  # Debian/Ubuntu
```

#### Run lyse
```bash
git clone https://github.com/snoowfall/lyse.git --depth 1
cd lyse
chmod +x lyse.py
./lyse.py
```

## Keys

- `q` - quit
- `↑/↓` - adjust sync offset
- `u` - toggle UI
- `c` - toggle centered
- `d` - toggle dynamic colors
- `i` - toggle dim inactive
- `shift+u` - toggle uppercase<br/>
  
> [!TIP]
> You can also adjust offset with the scroll wheel.

Settings auto-save to `~/.config/lyse/settings.json`

Reset all settings: `./lyse.py --reset`

<br/>
<h6>© 2026 snoowfall</h6>  
<h6>This documentation is licensed under CC BY-NC 4.0. Do not reuse without permission.</h6>
