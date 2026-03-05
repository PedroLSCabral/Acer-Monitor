#!/usr/bin/env python3
"""
Leitor de temperatura via LibreHardwareMonitor DLL (pythonnet).
Não depende de WMI nem de programa externo rodando.

Requisitos:
    pip install pythonnet psutil

A DLL do LibreHardwareMonitor (LibreHardwareMonitorLib.dll) deve estar
na mesma pasta deste script, ou você pode passar o caminho completo.

Como obter a DLL:
    1. Baixe o .zip do LibreHardwareMonitor no GitHub
    2. Extraia — a DLL está dentro da pasta
    3. Copie LibreHardwareMonitorLib.dll para a pasta do monitor
"""

import os
import sys
from pathlib import Path

# ── Localiza a DLL ────────────────────────────────────────────
def find_lhm_dll():
    """Procura a DLL em locais comuns."""
    candidates = [
        Path(__file__).parent / "LibreHardwareMonitorLib.dll",
        Path.home() / "acer_monitor" / "LibreHardwareMonitorLib.dll",
        Path("C:/Program Files/LibreHardwareMonitor/LibreHardwareMonitorLib.dll"),
        # Pasta do winget
        Path.home() / "AppData/Local/Microsoft/WinGet/Packages" ,
    ]
    for p in candidates:
        if p.is_file():
            return p
    # Busca recursiva em AppData
    winget_base = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    if winget_base.exists():
        for dll in winget_base.rglob("LibreHardwareMonitorLib.dll"):
            return dll
    return None


def init_lhm(dll_path=None):
    """
    Inicializa o LibreHardwareMonitor via pythonnet.
    Retorna o objeto Computer já aberto, ou None em caso de falha.
    """
    try:
        import clr
    except ImportError:
        print("❌ pythonnet não instalado. Rode: pip install pythonnet")
        return None

    if dll_path is None:
        dll_path = find_lhm_dll()

    if dll_path is None:
        print("❌ LibreHardwareMonitorLib.dll não encontrada.")
        print("   Copie a DLL para a mesma pasta do monitor.py")
        return None

    try:
        clr.AddReference(str(dll_path))
        from LibreHardwareMonitor.Hardware import Computer

        computer = Computer()
        computer.IsCpuEnabled = True
        computer.IsGpuEnabled = True
        computer.IsMemoryEnabled = True
        computer.IsMotherboardEnabled = True
        computer.IsBatteryEnabled = True
        computer.IsStorageEnabled = True
        computer.Open()
        return computer
    except Exception as e:
        print(f"❌ Erro ao inicializar LHM: {e}")
        return None


def read_temperatures(computer):
    """
    Lê todas as temperaturas do computador.
    Retorna (cpu_temp, gpu_temp, temps_dict).
    """
    if computer is None:
        return None, None, {}

    try:
        from LibreHardwareMonitor.Hardware import HardwareType, SensorType

        temps = {}
        cpu_temp = None
        gpu_temp = None

        for hardware in computer.Hardware:
            hardware.Update()

            for sub in hardware.SubHardware:
                sub.Update()

            hw_name = str(hardware.Name)
            hw_type = str(hardware.HardwareType)

            for sensor in hardware.Sensors:
                if str(sensor.SensorType) == "Temperature":
                    val = sensor.Value
                    if val is None:
                        continue
                    val = float(val)
                    label = str(sensor.Name)

                    if hw_type not in temps:
                        temps[hw_type] = []
                    temps[hw_type].append({"label": label, "current": val, "hardware": hw_name})

                    # CPU — pega o Package ou primeiro core disponível
                    if "Cpu" in hw_type or "CPU" in hw_type:
                        if cpu_temp is None or "Package" in label:
                            cpu_temp = val

                    # GPU
                    if "Gpu" in hw_type or "GPU" in hw_type:
                        if gpu_temp is None:
                            gpu_temp = val

            # Verifica sub-hardware também
            for sub in hardware.SubHardware:
                for sensor in sub.Sensors:
                    if str(sensor.SensorType) == "Temperature":
                        val = sensor.Value
                        if val is None:
                            continue
                        val = float(val)
                        label = str(sensor.Name)
                        key = f"{hw_type}/{str(sub.Name)}"
                        if key not in temps:
                            temps[key] = []
                        temps[key].append({"label": label, "current": val})

                        if ("Cpu" in hw_type or "CPU" in hw_type) and cpu_temp is None:
                            cpu_temp = val

        return cpu_temp, gpu_temp, temps

    except Exception as e:
        print(f"Erro ao ler temperatura: {e}")
        return None, None, {}


# ── Teste standalone ──────────────────────────────────────────
if __name__ == "__main__":
    print("🔍 Inicializando LibreHardwareMonitor...")
    computer = init_lhm()

    if computer is None:
        sys.exit(1)

    print("✅ LHM inicializado com sucesso!\n")
    print("📊 Temperaturas encontradas:")
    print("-" * 40)

    cpu, gpu, temps = read_temperatures(computer)

    if not temps:
        print("Nenhuma temperatura encontrada.")
        print("Certifique-se de rodar como Administrador.")
    else:
        for hw_type, sensors in temps.items():
            print(f"\n[{hw_type}]")
            for s in sensors:
                print(f"  {s['label']}: {s['current']:.1f}°C")

    print("-" * 40)
    print(f"\n🌡️  CPU: {cpu}°C")
    print(f"🎮 GPU: {gpu}°C")

    computer.Close()
