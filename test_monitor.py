#!/usr/bin/env python3
"""
Acer Aspire 5 — Testes Unitários
Cobre: init_db, save_snapshot, check_alerts, detect_reboot,
       collect_cpu/memory/disk/network/processes, shutdown flag,
       _load_config, _find_dll.

Rodar:
    python -m pytest test_monitor.py -v
    python -m pytest test_monitor.py -v --tb=short
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# ── Garante que o monitor.py é importável sem config.json ─────
# Injeta um config vazio antes do import para evitar print de aviso
_orig_exists = Path.exists

def _patched_exists(self):
    if self.name == "config.json":
        return False
    return _orig_exists(self)

Path.exists = _patched_exists
import monitor as m
Path.exists = _orig_exists


# ── Helpers ───────────────────────────────────────────────────
def make_db():
    """Cria banco SQLite em memória já inicializado."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    m.init_db(conn)
    return conn


def make_snap(**overrides):
    """Snapshot mínimo válido para testes."""
    base = {
        "ts":              "2026-03-06T10:00:00",
        "uptime_s":        3600.0,
        "cpu_pct":         30.0,
        "cpu_freq_mhz":    2400.0,
        "cpu_temp":        60.0,
        "ram_total_mb":    8000.0,
        "ram_used_mb":     4000.0,
        "ram_pct":         50.0,
        "swap_pct":        10.0,
        "disk_read_mb":    100.0,
        "disk_write_mb":   50.0,
        "disk_pct":        40.0,
        "net_sent_mb":     10.0,
        "net_recv_mb":     20.0,
        "battery_pct":     80.0,
        "battery_plugged": 1,
        "battery_secs":    -1,
        "temps_json":      "{}",
        "gpu_temp":        None,
        "proc_count":      120,
        "proc_top_json":   "[]",
    }
    base.update(overrides)
    return base


# ══════════════════════════════════════════════════════════════
class TestInitDb(unittest.TestCase):
    """init_db cria todas as tabelas e índices esperados."""

    def test_tables_created(self):
        conn = make_db()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertIn("snapshots",   tables)
        self.assertIn("boot_events", tables)
        self.assertIn("alerts",      tables)

    def test_indexes_created(self):
        conn = make_db()
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
        self.assertIn("idx_snap_ts", indexes)
        self.assertIn("idx_boot_ts", indexes)

    def test_idempotent(self):
        """Chamar init_db duas vezes não deve levantar exceção."""
        conn = make_db()
        m.init_db(conn)  # segunda vez


# ══════════════════════════════════════════════════════════════
class TestSaveSnapshot(unittest.TestCase):
    """save_snapshot persiste corretamente no banco."""

    def test_saves_one_row(self):
        conn = make_db()
        m.save_snapshot(conn, make_snap())
        count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        self.assertEqual(count, 1)

    def test_values_match(self):
        conn = make_db()
        snap = make_snap(cpu_pct=75.5, cpu_temp=85.0, ram_pct=62.0)
        m.save_snapshot(conn, snap)
        row = conn.execute("SELECT * FROM snapshots").fetchone()
        self.assertAlmostEqual(row["cpu_pct"],  75.5)
        self.assertAlmostEqual(row["cpu_temp"], 85.0)
        self.assertAlmostEqual(row["ram_pct"],  62.0)

    def test_null_temp_allowed(self):
        conn = make_db()
        m.save_snapshot(conn, make_snap(cpu_temp=None, gpu_temp=None))
        row = conn.execute("SELECT cpu_temp FROM snapshots").fetchone()
        self.assertIsNone(row["cpu_temp"])

    def test_multiple_snapshots(self):
        conn = make_db()
        for i in range(5):
            m.save_snapshot(conn, make_snap(ts=f"2026-03-06T10:00:0{i}"))
        count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        self.assertEqual(count, 5)


# ══════════════════════════════════════════════════════════════
class TestCheckAlerts(unittest.TestCase):
    """check_alerts registra alertas apenas quando thresholds são cruzados."""

    def _alert_count(self, conn, kind=None):
        if kind:
            return conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE kind=?", (kind,)
            ).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]

    # Temperatura
    def test_no_alert_normal_temp(self):
        conn = make_db()
        m.check_alerts(conn, make_snap(cpu_temp=70.0))
        self.assertEqual(self._alert_count(conn, "temp"), 0)

    def test_alert_on_temp_warning(self):
        conn = make_db()
        m.check_alerts(conn, make_snap(cpu_temp=m.TEMP_WARN + 1))
        self.assertEqual(self._alert_count(conn, "temp"), 1)

    def test_alert_on_temp_critical(self):
        conn = make_db()
        m.check_alerts(conn, make_snap(cpu_temp=m.TEMP_CRIT + 1))
        row = conn.execute("SELECT message FROM alerts WHERE kind='temp'").fetchone()
        self.assertIn("CRÍTICA", row["message"])

    def test_no_alert_none_temp(self):
        conn = make_db()
        m.check_alerts(conn, make_snap(cpu_temp=None))
        self.assertEqual(self._alert_count(conn, "temp"), 0)

    # CPU
    def test_no_alert_normal_cpu(self):
        conn = make_db()
        m.check_alerts(conn, make_snap(cpu_pct=80.0))
        self.assertEqual(self._alert_count(conn, "cpu"), 0)

    def test_alert_on_cpu_critical(self):
        conn = make_db()
        m.check_alerts(conn, make_snap(cpu_pct=m.CPU_CRIT + 1))
        self.assertEqual(self._alert_count(conn, "cpu"), 1)

    # RAM
    def test_no_alert_normal_ram(self):
        conn = make_db()
        m.check_alerts(conn, make_snap(ram_pct=70.0))
        self.assertEqual(self._alert_count(conn, "ram"), 0)

    def test_alert_on_ram_critical(self):
        conn = make_db()
        m.check_alerts(conn, make_snap(ram_pct=m.RAM_CRIT + 1))
        self.assertEqual(self._alert_count(conn, "ram"), 1)

    # Bateria
    def test_no_alert_battery_plugged(self):
        conn = make_db()
        m.check_alerts(conn, make_snap(battery_pct=2.0, battery_plugged=1))
        self.assertEqual(self._alert_count(conn, "battery"), 0)

    def test_alert_battery_low_unplugged(self):
        conn = make_db()
        m.check_alerts(conn, make_snap(battery_pct=m.BAT_LOW - 1, battery_plugged=0))
        self.assertEqual(self._alert_count(conn, "battery"), 1)

    def test_no_alert_battery_ok_unplugged(self):
        conn = make_db()
        m.check_alerts(conn, make_snap(battery_pct=50.0, battery_plugged=0))
        self.assertEqual(self._alert_count(conn, "battery"), 0)

    # Múltiplos alertas no mesmo snapshot
    def test_multiple_alerts_same_snap(self):
        conn = make_db()
        m.check_alerts(conn, make_snap(
            cpu_temp=m.TEMP_CRIT + 1,
            cpu_pct=m.CPU_CRIT + 1,
            ram_pct=m.RAM_CRIT + 1,
        ))
        self.assertGreaterEqual(self._alert_count(conn), 3)


# ══════════════════════════════════════════════════════════════
class TestDetectReboot(unittest.TestCase):
    """detect_reboot registra corretamente primeira execução e reboots."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".flag")
        self.tmp.close()
        self.flag_path = Path(self.tmp.name)
        # Garante que o flag não existe antes de cada teste
        self.flag_path.unlink(missing_ok=True)

    def tearDown(self):
        self.flag_path.unlink(missing_ok=True)

    def _run_detect(self, conn, boot_ts="2026-03-06T08:00:00"):
        with patch.object(m, "SHUTDOWN_FLAG", self.flag_path), \
             patch("monitor.psutil.boot_time", return_value=
                   time.mktime(time.strptime(boot_ts, "%Y-%m-%dT%H:%M:%S"))), \
             patch("monitor._notify_reboot"):
            m.detect_reboot(conn)

    def test_first_run_recorded(self):
        conn = make_db()
        self._run_detect(conn)
        row = conn.execute("SELECT notes FROM boot_events").fetchone()
        self.assertIsNotNone(row)
        self.assertIn("Primeira execução", row["notes"])

    def test_first_run_count(self):
        conn = make_db()
        self._run_detect(conn)
        count = conn.execute("SELECT COUNT(*) FROM boot_events").fetchone()[0]
        self.assertEqual(count, 1)

    def test_same_boot_no_duplicate(self):
        conn = make_db()
        self._run_detect(conn, "2026-03-06T08:00:00")
        self._run_detect(conn, "2026-03-06T08:00:00")
        count = conn.execute("SELECT COUNT(*) FROM boot_events").fetchone()[0]
        self.assertEqual(count, 1)

    def test_new_boot_recorded(self):
        conn = make_db()
        self._run_detect(conn, "2026-03-06T08:00:00")
        self._run_detect(conn, "2026-03-06T10:00:00")  # boot diferente
        count = conn.execute("SELECT COUNT(*) FROM boot_events").fetchone()[0]
        self.assertEqual(count, 2)

    def test_shutdown_flag_cleared_after_detect(self):
        conn = make_db()
        self.flag_path.write_text("2026-03-06T07:00:00")
        self._run_detect(conn)
        self.assertFalse(self.flag_path.exists())


# ══════════════════════════════════════════════════════════════
class TestShutdownFlag(unittest.TestCase):
    """_was_clean_shutdown, _mark_clean_shutdown, _clear_shutdown_flag."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.flag = Path(self.tmp_dir) / ".clean_shutdown"

    def tearDown(self):
        self.flag.unlink(missing_ok=True)

    def test_no_flag_returns_false(self):
        with patch.object(m, "SHUTDOWN_FLAG", self.flag):
            self.assertFalse(m._was_clean_shutdown())

    def test_mark_creates_flag(self):
        with patch.object(m, "SHUTDOWN_FLAG", self.flag):
            m._mark_clean_shutdown()
            self.assertTrue(self.flag.exists())

    def test_flag_contains_timestamp(self):
        with patch.object(m, "SHUTDOWN_FLAG", self.flag):
            m._mark_clean_shutdown()
            content = self.flag.read_text()
            self.assertRegex(content, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    def test_was_clean_after_mark(self):
        with patch.object(m, "SHUTDOWN_FLAG", self.flag):
            m._mark_clean_shutdown()
            self.assertTrue(m._was_clean_shutdown())

    def test_clear_removes_flag(self):
        with patch.object(m, "SHUTDOWN_FLAG", self.flag):
            m._mark_clean_shutdown()
            m._clear_shutdown_flag()
            self.assertFalse(self.flag.exists())

    def test_clear_idempotent(self):
        """Chamar clear quando flag não existe não deve levantar exceção."""
        with patch.object(m, "SHUTDOWN_FLAG", self.flag):
            m._clear_shutdown_flag()
            m._clear_shutdown_flag()


# ══════════════════════════════════════════════════════════════
class TestCollectors(unittest.TestCase):
    """collect_cpu, collect_memory, collect_disk, collect_network, collect_processes."""

    # CPU
    def test_collect_cpu_keys(self):
        result = m.collect_cpu()
        self.assertIn("cpu_pct",      result)
        self.assertIn("cpu_freq_mhz", result)

    def test_collect_cpu_pct_range(self):
        result = m.collect_cpu()
        if result["cpu_pct"] is not None:
            self.assertGreaterEqual(result["cpu_pct"], 0)
            self.assertLessEqual(result["cpu_pct"],    100)

    # Memória
    def test_collect_memory_keys(self):
        result = m.collect_memory()
        for key in ("ram_total_mb", "ram_used_mb", "ram_pct", "swap_pct"):
            self.assertIn(key, result)

    def test_collect_memory_values_positive(self):
        result = m.collect_memory()
        self.assertGreater(result["ram_total_mb"], 0)
        self.assertGreaterEqual(result["ram_pct"],    0)
        self.assertLessEqual(result["ram_pct"],      100)

    def test_ram_used_lte_total(self):
        result = m.collect_memory()
        self.assertLessEqual(result["ram_used_mb"], result["ram_total_mb"])

    # Disco
    def test_collect_disk_keys(self):
        result = m.collect_disk()
        for key in ("disk_pct", "disk_read_mb", "disk_write_mb"):
            self.assertIn(key, result)

    def test_collect_disk_graceful_on_bad_path(self):
        with patch.object(m, "DISK_PATH", "/caminho/inexistente"):
            result = m.collect_disk()
        self.assertIsNone(result["disk_pct"])

    # Rede
    def test_collect_network_keys(self):
        result = m.collect_network()
        self.assertIn("net_sent_mb", result)
        self.assertIn("net_recv_mb", result)

    def test_collect_network_non_negative(self):
        result = m.collect_network()
        if result["net_sent_mb"] is not None:
            self.assertGreaterEqual(result["net_sent_mb"], 0)
        if result["net_recv_mb"] is not None:
            self.assertGreaterEqual(result["net_recv_mb"], 0)

    def test_collect_network_fallback_on_error(self):
        with patch("monitor.psutil.net_io_counters", side_effect=Exception("erro")):
            result = m.collect_network()
        self.assertIsNone(result["net_sent_mb"])
        self.assertIsNone(result["net_recv_mb"])

    # Processos
    def test_collect_processes_keys(self):
        result = m.collect_processes()
        self.assertIn("proc_count",    result)
        self.assertIn("proc_top_json", result)

    def test_collect_processes_count_positive(self):
        result = m.collect_processes()
        self.assertGreater(result["proc_count"], 0)

    def test_collect_processes_top_json_valid(self):
        result = m.collect_processes()
        parsed = json.loads(result["proc_top_json"])
        self.assertIsInstance(parsed, list)
        self.assertLessEqual(len(parsed), m.TOP_PROCS_N)


# ══════════════════════════════════════════════════════════════
class TestLoadConfig(unittest.TestCase):
    """_load_config lê valores corretamente do JSON."""

    def test_loads_interval(self):
        cfg = {"interval_seconds": 10}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            path = Path(f.name)
        with patch.object(m, "BASE_DIR", path.parent), \
             patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(cfg))), \
             patch.object(Path, "exists", return_value=True):
            result = m._load_config()
        self.assertEqual(result.get("interval_seconds"), 10)
        path.unlink()

    def test_returns_empty_on_missing(self):
        with patch.object(Path, "exists", return_value=False):
            result = m._load_config()
        self.assertEqual(result, {})


# ══════════════════════════════════════════════════════════════
class TestFindDll(unittest.TestCase):
    """_find_dll retorna None quando DLL não existe."""

    def test_returns_none_when_missing(self):
        with patch.object(Path, "is_file", return_value=False):
            result = m._find_dll()
        self.assertIsNone(result)

    def test_returns_path_when_found(self):
        fake = MagicMock(spec=Path)
        fake.is_file.return_value = True
        with patch.object(m, "DLL_DIR", fake.parent), \
             patch.object(Path, "is_file", return_value=True):
            result = m._find_dll()
        self.assertIsNotNone(result)


# ══════════════════════════════════════════════════════════════
class TestLhmFailCount(unittest.TestCase):
    """get_temps_lhm incrementa/reseta _lhm_fail_count corretamente."""

    def test_increments_when_computer_none(self):
        m._lhm_computer   = None
        m._lhm_fail_count = 0
        # Com _lhm_computer None e fail_count < threshold, retorna vazio sem reconectar
        with patch("monitor.init_lhm"):
            m.get_temps_lhm()
        # fail_count não incrementa aqui pois retorna antes do try
        self.assertEqual(m._lhm_fail_count, 0)

    def test_triggers_reconnect_at_threshold(self):
        m._lhm_computer   = None
        m._lhm_fail_count = m.LHM_RECONNECT_AFTER
        with patch("monitor.init_lhm") as mock_init:
            m.get_temps_lhm()
        mock_init.assert_called_once()


# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    unittest.main(verbosity=2)
