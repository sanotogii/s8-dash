#!/usr/bin/env python3
"""S8 proot dashboard backend. No dependencies. Run: python3 server.py [port]"""
import json, os, re, sys, time, shutil, socket, threading, pwd
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
PAGE = os.sysconf("SC_PAGE_SIZE")


def rd(p, d=None):
    try:
        with open(p) as f:
            return f.read().strip()
    except Exception:
        return d


def num(p):
    try:
        return float(rd(p))
    except Exception:
        return None


# ---------- CPU sampler (background) ----------
cpu_pct = None


def cpu_times():
    l = rd("/proc/stat")
    if not l:
        return None
    p = [int(x) for x in l.splitlines()[0].split()[1:]]
    return p[3] + (p[4] if len(p) > 4 else 0), sum(p)


def sampler():
    global cpu_pct
    last = cpu_times()
    while True:
        time.sleep(1)
        cur = cpu_times()
        if last and cur and cur[1] > last[1]:
            cpu_pct = round(100 * (1 - (cur[0] - last[0]) / (cur[1] - last[1])), 1)
        last = cur


# ---------- Battery / temperature ----------
def battery():
    for b in ("battery", "Battery", "bms"):
        base = f"/sys/class/power_supply/{b}"
        if os.path.isdir(base):
            cap = num(base + "/capacity")
            if cap is None:
                continue
            t = num(base + "/temp")
            v = num(base + "/voltage_now")
            c = num(base + "/current_now")
            return {
                "percent": cap,
                "status": rd(base + "/status", "Unknown"),
                "health": rd(base + "/health"),
                "temp": t / 10 if t is not None else None,
                "voltage": (v / 1e6 if v and v > 1000 else v),
                "current_ma": (c / 1000 if c and abs(c) > 10000 else c),
            }
    return None


def thermal():
    out = []
    try:
        zones = sorted(d for d in os.listdir("/sys/class/thermal") if d.startswith("thermal_zone"))
    except Exception:
        return out
    for z in zones:
        t = num(f"/sys/class/thermal/{z}/temp")
        if t is None:
            continue
        if abs(t) > 1000:
            t /= 1000
        elif abs(t) > 150:
            t /= 10
        out.append({"name": rd(f"/sys/class/thermal/{z}/type", z), "temp": round(t, 1)})
    return out


# ---------- Memory / disk / net ----------
def memory():
    m = {}
    for line in (rd("/proc/meminfo", "") or "").splitlines():
        k, _, v = line.partition(":")
        try:
            m[k] = int(v.split()[0]) * 1024
        except Exception:
            pass
    total = m.get("MemTotal", 0)
    avail = m.get("MemAvailable", m.get("MemFree", 0))
    return {
        "total": total, "used": total - avail, "available": avail,
        "swap_total": m.get("SwapTotal", 0),
        "swap_used": m.get("SwapTotal", 0) - m.get("SwapFree", 0),
    }


def netdev():
    rx = tx = 0
    for line in (rd("/proc/net/dev", "") or "").splitlines()[2:]:
        name, _, rest = line.partition(":")
        if name.strip() == "lo":
            continue
        f = rest.split()
        try:
            rx += int(f[0]); tx += int(f[8])
        except Exception:
            pass
    return {"rx": rx, "tx": tx}


def local_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0]); s.close()
    except Exception:
        pass
    return sorted(ips)


# ---------- Processes / ports ----------
def procs():
    res = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            name = rd(f"/proc/{pid}/comm", "?")
            cmd = (rd(f"/proc/{pid}/cmdline", "") or "").replace("\x00", " ").strip()
            statm = rd(f"/proc/{pid}/statm", "0 0").split()
            rss = int(statm[1]) * PAGE
            try:
                user = pwd.getpwuid(os.stat(f"/proc/{pid}").st_uid).pw_name
            except Exception:
                user = "?"
            res[pid] = {"pid": int(pid), "name": name, "cmd": cmd[:140] or name, "rss": rss, "user": user}
        except Exception:
            continue
    return res


def inode_map(pids):
    m = {}
    for pid in pids:
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                try:
                    l = os.readlink(f"/proc/{pid}/fd/{fd}")
                    if l.startswith("socket:["):
                        m[l[8:-1]] = pid
                except Exception:
                    pass
        except Exception:
            pass
    return m


def parse_addr(h, v6):
    ip, port = h.split(":")
    port = int(port, 16)
    if not v6:
        return socket.inet_ntoa(bytes.fromhex(ip)[::-1]), port
    if set(ip) == {"0"}:
        return "::", port
    if ip == "0" * 31 + "1" or ip.upper() == "00000000000000000000000001000000":
        return "::1", port
    if ip.upper().startswith("0000000000000000FFFF0000"):
        return socket.inet_ntoa(bytes.fromhex(ip[24:])[::-1]), port
    return "ipv6", port


def ports(pmap):
    inodes = inode_map(pmap.keys())
    out, seen = [], set()
    for f, proto, v6, state in (
        ("/proc/net/tcp", "tcp", False, "0A"), ("/proc/net/tcp6", "tcp6", True, "0A"),
        ("/proc/net/udp", "udp", False, "07"), ("/proc/net/udp6", "udp6", True, "07"),
    ):
        for line in (rd(f, "") or "").splitlines()[1:]:
            p = line.split()
            if len(p) < 10 or p[3] != state:
                continue
            try:
                addr, port = parse_addr(p[1], v6)
            except Exception:
                continue
            if proto.startswith("udp") and port == 0:
                continue
            key = (proto, addr, port)
            if key in seen:
                continue
            seen.add(key)
            owner = pmap.get(inodes.get(p[9]))
            out.append({
                "proto": proto, "addr": addr, "port": port,
                "pid": owner["pid"] if owner else None,
                "process": owner["name"] if owner else None,
                "public": addr in ("0.0.0.0", "::"),
            })
    return sorted(out, key=lambda x: (x["port"], x["proto"]))


# (name, icon, regex matched against process command line, default ports)
APPS = [
    ("n8n", "🔗", r"\bn8n\b", [5678]),
    ("Node-RED", "🔴", r"node-red", [1880]),
    ("Nginx", "🌍", r"nginx", [80, 443]),
    ("Apache", "🪶", r"apache2|httpd", [80]),
    ("SSH", "🔐", r"sshd", [22, 8022]),
    ("Home Assistant", "🏠", r"homeassistant|hass\b", [8123]),
    ("Jupyter", "📓", r"jupyter", [8888]),
    ("code-server", "💻", r"code-server", []),
    ("Redis", "🧰", r"redis-server", [6379]),
    ("PostgreSQL", "🐘", r"postgres", [5432]),
    ("MySQL / MariaDB", "🐬", r"mysqld|mariadbd", [3306]),
    ("MongoDB", "🍃", r"mongod", [27017]),
    ("Syncthing", "🔄", r"syncthing", [8384]),
    ("Gitea", "🍵", r"gitea", [3000]),
    ("Vaultwarden", "🔑", r"vaultwarden", []),
    ("VNC", "🖥", r"vnc", [5901]),
    ("Ollama", "🦙", r"ollama", [11434]),
    ("This dashboard", "📊", r"server\.py", [PORT]),
]


def load_apps():
    """Built-in list + optional apps.json next to server.py:
    [{"name":"My app","icon":"🚀","match":"regex","ports":[1234]}]"""
    out = list(APPS)
    extra = rd(os.path.join(HERE, "apps.json"))
    if extra:
        try:
            for a in json.loads(extra):
                out.append((a["name"], a.get("icon", "📦"), a.get("match", re.escape(a["name"])), a.get("ports", [])))
        except Exception:
            pass
    return out


def apps(pmap, pl):
    res = []
    for name, icon, rx, aports in load_apps():
        try:
            r = re.compile(rx, re.I)
        except re.error:
            continue
        pids = [p for p in pmap.values() if r.search(p["cmd"]) or r.search(p["name"])]
        pidset = {p["pid"] for p in pids}
        lp = [x for x in pl if x["port"] in aports and x["proto"].startswith("tcp")]
        myports = {x["port"] for x in pl if x["pid"] in pidset} | {x["port"] for x in lp}
        res.append({
            "name": name, "icon": icon,
            "running": bool(pids or lp),
            "pids": [p["pid"] for p in pids][:4],
            "ports": sorted(myports),
            "rss": sum(p["rss"] for p in pids),
        })
    res.sort(key=lambda a: (not a["running"], a["name"]))
    return res


def stats():
    pmap = procs()
    pl = ports(pmap)
    listening_pids = {p["pid"] for p in pl if p["pid"]}
    plist = sorted(pmap.values(), key=lambda x: -x["rss"])[:25]
    for p in plist:
        p["listening"] = p["pid"] in listening_pids
    du = shutil.disk_usage("/")
    la = (rd("/proc/loadavg", "0 0 0") or "0 0 0").split()[:3]
    up = float((rd("/proc/uptime", "0") or "0").split()[0])
    return {
        "time": time.time(),
        "host": socket.gethostname(),
        "ips": local_ips(),
        "cpu": {"percent": cpu_pct, "cores": os.cpu_count(), "load": [float(x) for x in la]},
        "mem": memory(),
        "battery": battery(),
        "thermal": thermal(),
        "disk": {"total": du.total, "used": du.used},
        "net": netdev(),
        "uptime": up,
        "ports": pl,
        "apps": apps(pmap, pl),
        "procs": plist,
        "proc_count": len(pmap),
    }


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/stats":
            body, ctype = json.dumps(stats()).encode(), "application/json"
        elif path in ("/", "/index.html", "/dashboard.html"):
            try:
                with open(os.path.join(HERE, "dashboard.html"), "rb") as f:
                    body = f.read()
            except Exception:
                self.send_error(404, "dashboard.html must be next to server.py"); return
            ctype = "text/html; charset=utf-8"
        else:
            self.send_error(404); return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    threading.Thread(target=sampler, daemon=True).start()
    print(f"Dashboard running → http://localhost:{PORT}")
    for ip in local_ips():
        print(f"                  → http://{ip}:{PORT}  (from other devices on your Wi-Fi)")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()