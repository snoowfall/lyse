# lyse
Terminal synced lyrics viewer for your currently playing music.

<img width="1250" height="901" alt="2026-03-13-142513_hyprshot" src="https://github.com/user-attachments/assets/246943a6-0c90-4aea-b67f-9032337c4539" />

## Install

**Requirements:** `python`, `playerctl`

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

> [!TIP]
> Run `lyse -h` to see additional arguments.
  
## Keys

- `q` - quit
- `j/k` - adjust sync offset
- `u` - toggle UI
- `b` - toggle bold active
- `c` - toggle centered
- `d` - toggle dynamic colors
- `i` - toggle dim inactive
- `</>` - seek 5 seconds
- `shift+u` - toggle uppercase<br/>  

## Miscellanous
Settings auto-save to `~/.config/lyse/settings.json`  
Reset all settings: `lyse --reset`  

<br/>  
<h6>© 2026 snoowfall |This documentation is licensed under CC BY-NC 4.0. Do not reuse without permission.</h6>
