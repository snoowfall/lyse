# lyse
Terminal synced lyrics viewer for your currently playing music.

<img width="1250" height="901" alt="2026-03-13-142513_hyprshot" src="https://github.com/user-attachments/assets/246943a6-0c90-4aea-b67f-9032337c4539" />

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
<h5>© 2026 snoowfall</h5>  
<h6>This documentation is licensed under CC BY-NC 4.0. Do not reuse without permission.</h6>
