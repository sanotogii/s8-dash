# 📱 S8 Dashboard

A lightweight monitoring dashboard for a **proot Ubuntu** server running on a Samsung Galaxy S8 (Termux). It shows live battery, CPU, RAM, temperature, storage, network, open ports, running apps and processes in a single clean web page.

No dependencies: the backend is one Python file using only the standard library, and the front-end is one HTML file.

## Features

- 🔋 **Battery**: animated battery icon, charge status, voltage, current, temperature, health
- ⚙️ **CPU**: usage, load averages, core count, live graph
- 🧠 **Memory**: RAM and swap usage with history graph
- 🌡 **Temperature**: hottest sensor plus every readable thermal zone
- 💾 **Storage**: usage of the root filesystem
- 🌐 **Network**: live download/upload speed and totals since boot
- 🚀 **Apps**: detects n8n, Node-RED, nginx, Redis, SSH and more (add your own)
- 🔌 **Open ports**: listening TCP/UDP ports, public or local, with the owning process
- 🧩 **Processes**: top processes by memory, with listening ones highlighted
- 🌗 Automatic light/dark theme, mobile friendly, refreshes every 2 seconds

## Files

| File | Purpose |
|------|---------|
| `server.py` | Backend. Reads `/proc` and `/sys`, serves the page and the JSON API |
| `dashboard.html` | The dashboard UI (all CSS and JS inline) |
| `apps.json` | *(optional)* Your own apps to detect |

Keep `server.py` and `dashboard.html` in the **same folder**.

## Requirements

- Termux with `proot-distro` and an Ubuntu install
- Python 3 inside Ubuntu

```bash
apt update && apt install -y python3
```

## Setup

**1. Copy the files to the phone**, then in Termux (outside proot):

```bash
termux-setup-storage                 # tap Allow, only needed once
mkdir -p ~/dash
cp ~/storage/downloads/dashboard.html ~/storage/downloads/server.py ~/dash/
```

**2. Log in to Ubuntu with the folder mounted:**

```bash
proot-distro login ubuntu --bind ~/dash:/root/dash
```

**3. Start the server:**

```bash
cd /root/dash
python3 server.py            # default port 8080
python3 server.py 9000       # or choose a port
```

You'll see:

```
Dashboard running → http://localhost:8080
                  → http://192.168.1.50:8080  (from other devices on your Wi-Fi)
```

**4. Open it** in the phone's browser at `http://localhost:8080`, or from another device on the same Wi-Fi using the second address.

## Running in the background

```bash
nohup python3 server.py > /dev/null 2>&1 &    # start
pkill -f server.py                             # stop
```

The server stops when Termux is closed. Pull down the Termux notification and tap **Acquire wakelock** to keep it alive.

## Adding your own apps

Create `apps.json` next to `server.py`:

```json
[
  {"name": "My Bot", "icon": "🤖", "match": "bot\\.py", "ports": []},
  {"name": "Uptime Kuma", "icon": "📈", "match": "uptime-kuma", "ports": [3001]}
]
```

| Field | Meaning |
|-------|---------|
| `name` | Label shown on the card |
| `icon` | Emoji for the card (optional) |
| `match` | Regular expression tested against the process command line |
| `ports` | Ports that also count as "running" if listening (optional) |

Restart the server after editing. An app counts as running if its process matches **or** one of its ports is listening.

Built-in apps: n8n, Node-RED, Nginx, Apache, SSH, Home Assistant, Jupyter, code-server, Redis, PostgreSQL, MySQL/MariaDB, MongoDB, Syncthing, Gitea, Vaultwarden, VNC, Ollama.

## Customizing

- **Display name:** the header shows `S8`. Use `?name=` to change it without editing anything, e.g. `http://localhost:8080/?name=Galaxy`.
- **Refresh rate:** change `REFRESH` (milliseconds) near the top of the script in `dashboard.html`.

## API

`GET /api/stats` returns all data as JSON, handy for scripts or other dashboards:

```bash
curl http://localhost:8080/api/stats
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Address already in use" | Use another port: `python3 server.py 8081` |
| Page says it can't reach `/api/stats` | Open the page through the server address, not by opening `dashboard.html` as a file |
| Battery shows "unavailable" | proot may hide `/sys/class/power_supply`. The page falls back to the browser Battery API (percent and charging only) |
| Temperature shows "n/a" | Thermal sensors aren't readable. Check `ls /sys/class/thermal` |
| A port shows no process name | proot couldn't read that process's file descriptors. The port is still listed |
| An app shows as running but isn't | A detector is too loose. Tighten its `match` regex |
| n8n not detected | If it runs outside this proot, only the port check (5678) can catch it |

## Notes

- proot has no systemd, so "services" means running processes, not systemd units.
- Sensor availability depends on the Android version and ROM. Some values may be missing on your device.
- ⚠️ **Security:** the server listens on all interfaces (`0.0.0.0`) with **no authentication**. Anyone on your Wi-Fi can open it and see your processes and open ports. Only run it on networks you trust, or change `("0.0.0.0", PORT)` to `("127.0.0.1", PORT)` in `server.py` to allow access from the phone only.