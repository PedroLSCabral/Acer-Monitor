# Acer Crash Monitor — Release Notes

---

## v1.0.0 — 2026-03-06

**First stable release.**

This version marks the completion of all planned features for the initial milestone. The monitor has been running in a real-world environment on an Acer Aspire 5 with confirmed crash detection, temperature monitoring, and reboot classification working end-to-end.

### What's included

**Core monitoring**
- Continuous background collection every 5 seconds: CPU usage and frequency, CPU and GPU temperature (via LibreHardwareMonitor DLL), RAM, swap, disk I/O, network I/O, battery state and top 5 processes by CPU
- All data persisted to a local SQLite database
- Configurable alert thresholds for temperature, CPU, RAM and battery via `config.json`

**Reboot detection and classification**
- Automatic reboot detection on startup by comparing current boot time against previous session
- Clean shutdown flag (`.clean_shutdown`) distinguishes graceful exits from abrupt process kills
- Windows toast notification on reboot detection (native PowerShell, no dependencies)
- `classify_reboot.py` — interactive PowerShell Forms dialog to manually classify each reboot as crash, intentional or unknown

**Resilience**
- `watchdog.py` monitors the monitor process and restarts it automatically on failure
- LHM auto-reconnect: temperature sensor reconnects after N consecutive failed reads (configurable)
- Task Scheduler XML configured to start watchdog at login with admin privileges

**Dashboard and analysis**
- `dashboard.py` generates a self-contained HTML report with Chart.js graphs for temperature, CPU and RAM over time
- Two-tab layout: Overview (charts + reboot history + alerts) and Crash Analysis (pre-crash metrics per event)
- `analyze.py` CLI tool for terminal-based pre-crash pattern analysis with configurable time window and crash-only filter

**Developer experience**
- `monitor.py --status` displays live process status, last snapshot metrics, total snapshots and pending classifications
- `AcerMonitor.bat` launcher with admin elevation and full command menu (start, stop, status, dashboard, analyze, classify, test, open folder)
- `config.json` centralizes all thresholds, paths and collection parameters
- Modular collectors: `collect_cpu()`, `collect_memory()`, `collect_disk()`, `collect_network()`, `collect_processes()`
- All scripts accept `--db` CLI argument for flexible database path

**Quality**
- 49 unit tests covering database initialization, snapshot persistence, alert thresholds, reboot detection, shutdown flag lifecycle, all collectors, config loading and LHM reconnect logic
- Zero test dependencies on real hardware, DLL or existing database — fully mockable

### Installation

```powershell
git clone https://github.com/pedroLSCabral/acer-crash-monitor.git
cd acer-crash-monitor
pip install psutil pythonnet pytest
# Copy LibreHardwareMonitor DLLs to libs/
# Run AcerMonitor.bat as Administrator
```

---

## Roadmap

### v1.1.0 — Process reliability
- Replace cmdline-based process detection in `--status` with a `monitor.pid` file for accurate and collision-free process identification
- Add `--db` argument to `monitor.py --status` for consistency with other scripts
- Extend unit test coverage to `cmd_status`, `collect_snapshot` integration and `dashboard.py` data pipeline

### v1.2.0 — Live web dashboard
- Replace static HTML generation with a FastAPI server serving a live dashboard
- WebSocket-based real-time chart updates (no manual regeneration needed)
- REST endpoints: `/status`, `/snapshots`, `/alerts`, `/boots`
- Integrate `classify_reboot` flow directly in the web UI

### v1.3.0 — ML pipeline (requires sufficient crash data)
- `prepare_dataset.py` — extracts labeled pre-crash windows from the database into a feature matrix CSV
- `train.py` — trains a crash prediction classifier (Random Forest / XGBoost) with class imbalance handling
- Inference integration in `monitor.py` — scores each snapshot in real time and raises alert when crash probability exceeds configurable threshold
- SHAP-based feature importance report to identify dominant crash predictors
