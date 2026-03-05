#!/usr/bin/env python3
"""
Acer Aspire 5 — Monitor de Reinicializações (Windows 11)
Usa LibreHardwareMonitor via DLL (pythonnet) — sem WMI, sem programa externo.

Requisitos:
    pip install psutil pythonnet

A DLL LibreHardwareMonitorLib.dll deve estar na mesma pasta deste script.
Como obter: extraia o .zip do LibreHardwareMonitor e copie a DLL para cá.

Rodar em background (sem janela):
    pythonw monitor.py

Ou configure o autostart via Task Scheduler — veja README.md
"""

import sqlite3
import time
import os
import sys
import json
import signal
import logging
import platform
import threading
import tkinter as tk
from tkinter import simpledialog, messagebox
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:
    print("Instale psutil: pip install psutil")
    sys.exit(1)

# ── Configuração ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent

def _load_config():
    config_path = BASE_DIR / "config.json"
    if not config_path.exists():
        print(f"config.json não encontrado em {BASE_DIR} — usando valores padrão.")
        return {}
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)

CFG           = _load_config()
DLL_DIR       = BASE_DIR / CFG.get("paths", {}).get("dll_dir", "libs")
DB_PATH       = BASE_DIR / CFG.get("paths", {}).get("database", "monitor.db")
LOG_PATH      = BASE_DIR / CFG.get("paths", {}).get("log", "monitor.log")
SHUTDOWN_FLAG = BASE_DIR / CFG.get("paths", {}).get("shutdown_flag", ".clean_shutdown")
DISK_PATH     = CFG.get("paths", {}).get("disk", "C:\\")
INTERVAL      = CFG.get("interval_seconds", 5)

_alerts       = CFG.get("alerts", {})
TEMP_WARN     = _alerts.get("cpu_temp_warning",  80)
TEMP_CRIT     = _alerts.get("cpu_temp_critical", 90)
CPU_CRIT      = _alerts.get("cpu_pct_critical",  95)
RAM_CRIT      = _alerts.get("ram_pct_critical",  90)
BAT_LOW       = _alerts.get("battery_pct_low",    5)

_collection       = CFG.get("collection", {})
TOP_PROCS_N       = _collection.get("top_processes", 5)
LOG_EVERY_N       = _collection.get("log_every_n_snapshots", 12)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("AcerMonitor")


# ── LibreHardwareMonitor via pythonnet ────────────────────────
_lhm_computer = None

def _find_dll():
    candidates = [
        DLL_DIR / "LibreHardwareMonitorLib.dll",   # pasta libs/ (preferencial)
        BASE_DIR / "LibreHardwareMonitorLib.dll",  # raiz do projeto (fallback)
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def init_lhm():
    global _lhm_computer
    try:
        import clr
        dll = _find_dll()
        if dll is None:
            log.warning("LibreHardwareMonitorLib.dll não encontrada — temperatura desativada.")
            log.warning(f"Copie as DLLs para: {DLL_DIR}")
            return False
        clr.AddReference(str(dll))
        from LibreHardwareMonitor.Hardware import Computer
        c = Computer()
        c.IsCpuEnabled         = True
        c.IsGpuEnabled         = True
        c.IsMemoryEnabled      = True
        c.IsMotherboardEnabled = True
        c.IsBatteryEnabled     = True
        c.IsStorageEnabled     = True
        c.Open()
        _lhm_computer = c
        log.info(f"LibreHardwareMonitor inicializado via DLL: {dll.name}")
        return True
    except ImportError:
        log.warning("pythonnet não instalado — rode: pip install pythonnet")
        return False
    except Exception as e:
        log.warning(f"Erro ao inicializar LHM: {e}")
        return False


def get_temps_lhm():
    if _lhm_computer is None:
        return None, None, {}
    try:
        temps    = {}
        cpu_temp = None
        gpu_temp = None

        for hw in _lhm_computer.Hardware:
            hw.Update()
            for sub in hw.SubHardware:
                sub.Update()

            hw_type = str(hw.HardwareType)
            hw_name = str(hw.Name)

            def read_sensors(sensors, key):
                nonlocal cpu_temp, gpu_temp
                for s in sensors:
                    if str(s.SensorType) != "Temperature":
                        continue
                    val = s.Value
                    if val is None:
                        continue
                    val   = float(val)
                    label = str(s.Name)
                    if key not in temps:
                        temps[key] = []
                    temps[key].append({"label": label, "current": val, "hardware": hw_name})
                    if "Cpu" in hw_type and (cpu_temp is None or "Package" in label):
                        cpu_temp = val
                    if "Gpu" in hw_type and gpu_temp is None:
                        gpu_temp = val

            read_sensors(hw.Sensors, hw_type)
            for sub in hw.SubHardware:
                read_sensors(sub.Sensors, f"{hw_type}/{sub.Name}")

        return cpu_temp, gpu_temp, temps
    except Exception as e:
        log.error(f"Erro ao ler temperatura: {e}")
        return None, None, {}


# ── Bateria ───────────────────────────────────────────────────
def get_battery():
    bat = psutil.sensors_battery()
    if not bat:
        return None, None, None
    secs = bat.secsleft
    if secs == psutil.POWER_TIME_UNLIMITED:
        secs = -1
    return bat.percent, bat.power_plugged, secs


# ── Banco de dados ────────────────────────────────────────────
def init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts              TEXT NOT NULL,
            uptime_s        REAL,
            cpu_pct         REAL,
            cpu_freq_mhz    REAL,
            cpu_temp        REAL,
            ram_total_mb    REAL,
            ram_used_mb     REAL,
            ram_pct         REAL,
            swap_pct        REAL,
            disk_read_mb    REAL,
            disk_write_mb   REAL,
            disk_pct        REAL,
            net_sent_mb     REAL,
            net_recv_mb     REAL,
            battery_pct     REAL,
            battery_plugged INTEGER,
            battery_secs    REAL,
            temps_json      TEXT,
            gpu_temp        REAL,
            proc_count      INTEGER,
            proc_top_json   TEXT
        );
        CREATE TABLE IF NOT EXISTS boot_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ts           TEXT NOT NULL,
            boot_time    TEXT,
            last_snap_ts TEXT,
            kind         TEXT DEFAULT 'desconhecido',  -- 'crash', 'intencional', 'desconhecido'
            notes        TEXT
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            ts      TEXT NOT NULL,
            kind    TEXT,
            value   REAL,
            message TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_snap_ts ON snapshots(ts);
        CREATE INDEX IF NOT EXISTS idx_boot_ts ON boot_events(ts);
    """)
    conn.commit()
    log.info(f"Banco iniciado: {DB_PATH}")


def _was_clean_shutdown():
    """Retorna True se o último encerramento foi limpo (arquivo de flag existe)."""
    return SHUTDOWN_FLAG.exists()


def _mark_clean_shutdown():
    """Cria o arquivo de flag de shutdown limpo."""
    SHUTDOWN_FLAG.write_text(datetime.now().isoformat(), encoding="utf-8")


def _clear_shutdown_flag():
    """Remove o arquivo de flag (chamado no início de cada sessão)."""
    try:
        SHUTDOWN_FLAG.unlink(missing_ok=True)
    except Exception:
        pass


def _ask_reboot_reason(boot_event_id, conn):
    """
    Abre um popup perguntando se a reinicialização foi intencional.
    Roda em thread separada para não bloquear a coleta.
    """
    def ask():
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)

            answer = messagebox.askyesnocancel(
                "Acer Crash Monitor",
                "Uma reinicialização foi detectada.\n\n"
                "Foi uma reinicialização INTENCIONAL\n"
                "(você mesmo reiniciou ou desligou o PC)?\n\n"
                "  Sim  → Intencional (manual)\n"
                "  Não  → Crash / reinicialização inesperada\n"
                "  Cancelar → Não sei / pular",
                icon="question"
            )
            root.destroy()

            if answer is True:
                kind = "intencional"
                note = "Reinicialização manual pelo usuário"
            elif answer is False:
                kind = "crash"
                note = "Crash / reinicialização inesperada (confirmado pelo usuário)"
            else:
                kind = "desconhecido"
                note = "Reinicialização detectada — tipo não informado"

            conn.execute(
                "UPDATE boot_events SET kind = ?, notes = ? WHERE id = ?",
                (kind, note, boot_event_id)
            )
            conn.commit()
            log.info(f"Reinicialização classificada como: {kind}")

        except Exception as e:
            log.warning(f"Erro ao exibir popup de classificação: {e}")

    threading.Thread(target=ask, daemon=True).start()


def detect_reboot(conn):
    boot_time = datetime.fromtimestamp(psutil.boot_time()).isoformat()
    last = conn.execute(
        "SELECT boot_time FROM boot_events ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if last is None or last[0] != boot_time:
        last_snap = conn.execute(
            "SELECT ts FROM snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()

        is_first = last is None
        clean    = _was_clean_shutdown()

        if is_first:
            kind = "desconhecido"
            note = "Primeira execução"
        elif clean:
            # Shutdown limpo: provavelmente intencional, mas pergunta mesmo assim
            kind = "desconhecido"
            note = "Reinicialização após encerramento limpo do monitor"
        else:
            # Sem flag de shutdown → processo foi interrompido abruptamente
            kind = "desconhecido"
            note = "Reinicialização detectada — monitor não foi encerrado normalmente (possível crash)"

        cursor = conn.execute(
            "INSERT INTO boot_events (ts, boot_time, last_snap_ts, kind, notes) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(), boot_time,
             last_snap[0] if last_snap else None, kind, note)
        )
        conn.commit()
        boot_event_id = cursor.lastrowid

        if not is_first:
            flag_str = "✅ encerramento limpo anterior" if clean else "⚠️  sem flag de shutdown"
            log.warning(f"🔄 REINICIALIZAÇÃO DETECTADA ({flag_str}) — boot {boot_time}")
            # Abre popup para o usuário classificar
            _ask_reboot_reason(boot_event_id, conn)
        else:
            log.info(f"▶ Primeira execução — boot {boot_time}")

    # Remove flag para a próxima sessão detectar corretamente
    _clear_shutdown_flag()


# ── Coletores individuais ─────────────────────────────────────
def collect_cpu():
    cpu_pct      = psutil.cpu_percent(interval=1)
    cpu_freq     = psutil.cpu_freq()
    cpu_freq_mhz = cpu_freq.current if cpu_freq else None
    return {"cpu_pct": cpu_pct, "cpu_freq_mhz": cpu_freq_mhz}


def collect_memory():
    mem  = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "ram_total_mb": mem.total / 1e6,
        "ram_used_mb":  mem.used  / 1e6,
        "ram_pct":      mem.percent,
        "swap_pct":     swap.percent,
    }


def collect_disk():
    result = {"disk_pct": None, "disk_read_mb": None, "disk_write_mb": None}
    try:
        result["disk_pct"] = psutil.disk_usage(DISK_PATH).percent
    except Exception:
        pass
    try:
        io = psutil.disk_io_counters()
        if io:
            result["disk_read_mb"]  = io.read_bytes  / 1e6
            result["disk_write_mb"] = io.write_bytes / 1e6
    except Exception:
        pass
    return result


def collect_network():
    try:
        net = psutil.net_io_counters()
        return {"net_sent_mb": net.bytes_sent / 1e6, "net_recv_mb": net.bytes_recv / 1e6}
    except Exception:
        return {"net_sent_mb": None, "net_recv_mb": None}


def collect_processes():
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            procs.append(p.info)
        except Exception:
            pass
    procs.sort(key=lambda x: x.get("cpu_percent") or 0, reverse=True)
    return {
        "proc_count":    len(psutil.pids()),
        "proc_top_json": json.dumps(procs[:TOP_PROCS_N]),
    }


# ── Snapshot agregado ─────────────────────────────────────────
def collect_snapshot():
    bat_pct, bat_plugged, bat_secs = get_battery()
    cpu_temp, gpu_temp, temps      = get_temps_lhm()

    snap = {
        "ts":              datetime.now().isoformat(),
        "uptime_s":        time.time() - psutil.boot_time(),
        "cpu_temp":        cpu_temp,
        "gpu_temp":        gpu_temp,
        "temps_json":      json.dumps(temps),
        "battery_pct":     bat_pct,
        "battery_plugged": int(bat_plugged) if bat_plugged is not None else None,
        "battery_secs":    bat_secs,
    }
    snap.update(collect_cpu())
    snap.update(collect_memory())
    snap.update(collect_disk())
    snap.update(collect_network())
    snap.update(collect_processes())
    return snap


def save_snapshot(conn, snap):
    conn.execute("""
        INSERT INTO snapshots (
            ts, uptime_s, cpu_pct, cpu_freq_mhz, cpu_temp,
            ram_total_mb, ram_used_mb, ram_pct, swap_pct,
            disk_read_mb, disk_write_mb, disk_pct,
            net_sent_mb, net_recv_mb,
            battery_pct, battery_plugged, battery_secs,
            temps_json, gpu_temp, proc_count, proc_top_json
        ) VALUES (
            :ts, :uptime_s, :cpu_pct, :cpu_freq_mhz, :cpu_temp,
            :ram_total_mb, :ram_used_mb, :ram_pct, :swap_pct,
            :disk_read_mb, :disk_write_mb, :disk_pct,
            :net_sent_mb, :net_recv_mb,
            :battery_pct, :battery_plugged, :battery_secs,
            :temps_json, :gpu_temp, :proc_count, :proc_top_json
        )
    """, snap)
    conn.commit()


def check_alerts(conn, snap):
    alerts = []
    if snap["cpu_temp"]:
        if snap["cpu_temp"] > TEMP_CRIT:
            alerts.append(("temp", snap["cpu_temp"], f"CPU CRÍTICA: {snap['cpu_temp']:.0f}°C"))
        elif snap["cpu_temp"] > TEMP_WARN:
            alerts.append(("temp", snap["cpu_temp"], f"CPU alta: {snap['cpu_temp']:.0f}°C"))
    if snap["cpu_pct"] and snap["cpu_pct"] > CPU_CRIT:
        alerts.append(("cpu", snap["cpu_pct"], f"CPU: {snap['cpu_pct']:.0f}%"))
    if snap["ram_pct"] and snap["ram_pct"] > RAM_CRIT:
        alerts.append(("ram", snap["ram_pct"], f"RAM: {snap['ram_pct']:.0f}%"))
    if snap["battery_pct"] is not None and snap["battery_pct"] < BAT_LOW and not snap["battery_plugged"]:
        alerts.append(("battery", snap["battery_pct"], f"Bateria crítica: {snap['battery_pct']:.0f}%"))
    for kind, value, msg in alerts:
        conn.execute(
            "INSERT INTO alerts (ts, kind, value, message) VALUES (?,?,?,?)",
            (snap["ts"], kind, value, msg)
        )
        log.warning(f"⚠️  {msg}")
    if alerts:
        conn.commit()


# ── Loop principal ─────────────────────────────────────────────
running = True

def handle_signal(sig, frame):
    global running
    log.info("Encerrando monitor...")
    running = False

signal.signal(signal.SIGINT,  handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


def main():
    log.info("=" * 60)
    log.info("  Acer Aspire 5 — Monitor Windows 11 (pythonnet/LHM)")
    log.info(f"  {platform.system()} {platform.release()}")
    log.info(f"  Intervalo: {INTERVAL}s | DB: {DB_PATH}")
    log.info(f"  Alertas — Temp warn: {TEMP_WARN}°C | crit: {TEMP_CRIT}°C | CPU: {CPU_CRIT}% | RAM: {RAM_CRIT}%")
    log.info("=" * 60)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    detect_reboot(conn)
    init_lhm()

    counter = 0
    while running:
        try:
            snap = collect_snapshot()
            save_snapshot(conn, snap)
            check_alerts(conn, snap)
            counter += 1

            if counter % LOG_EVERY_N == 0:
                temp_str = f"{snap['cpu_temp']:.0f}°C" if snap["cpu_temp"] else "N/A"
                bat_str  = f"{snap['battery_pct']:.0f}%" if snap["battery_pct"] is not None else "N/A"
                log.info(
                    f"CPU {snap['cpu_pct']:.0f}% | "
                    f"Temp {temp_str} | "
                    f"RAM {snap['ram_pct']:.0f}% | "
                    f"Bat {bat_str}"
                )
        except Exception as e:
            log.error(f"Erro na coleta: {e}")

        time.sleep(INTERVAL)

    if _lhm_computer:
        _lhm_computer.Close()
    conn.close()
    _mark_clean_shutdown()
    log.info("Monitor encerrado limpo.")


if __name__ == "__main__":
    main()