#!/usr/bin/env python3
"""
Acer Aspire 5 — Watchdog
Garante que o monitor.py está sempre em execução.
Verifica a cada 30 segundos e reinicia se necessário.

Este script deve ser iniciado pelo Task Scheduler no login.
Ele por sua vez gerencia o ciclo de vida do monitor.py.

Uso:
    pythonw watchdog.py
"""

import sys
import time
import logging
import subprocess
from pathlib import Path
from datetime import datetime

BASE_DIR    = Path(__file__).parent
MONITOR     = BASE_DIR / "monitor.py"
LOG_PATH    = BASE_DIR / "watchdog.log"
CHECK_EVERY = 30   # segundos entre verificações
PYTHONW     = sys.executable.replace("python.exe", "pythonw.exe")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ]
)
log = logging.getLogger("Watchdog")

_process = None


def is_running():
    """Verifica se o processo do monitor ainda está vivo."""
    return _process is not None and _process.poll() is None


def start_monitor():
    """Inicia o monitor.py como subprocesso."""
    global _process
    log.info("Iniciando monitor.py...")
    try:
        _process = subprocess.Popen(
            [PYTHONW, str(MONITOR)],
            cwd=str(BASE_DIR),
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        log.info(f"Monitor iniciado — PID {_process.pid}")
    except Exception as e:
        log.error(f"Falha ao iniciar monitor: {e}")
        _process = None


def main():
    log.info("=" * 50)
    log.info("  Watchdog iniciado")
    log.info(f"  Monitor: {MONITOR}")
    log.info(f"  Check a cada {CHECK_EVERY}s")
    log.info("=" * 50)

    if not MONITOR.exists():
        log.error(f"monitor.py não encontrado em {BASE_DIR}")
        sys.exit(1)

    start_monitor()

    while True:
        time.sleep(CHECK_EVERY)
        if not is_running():
            exit_code = _process.returncode if _process else "?"
            log.warning(f"Monitor encerrado (código {exit_code}) — reiniciando...")
            start_monitor()


if __name__ == "__main__":
    main()