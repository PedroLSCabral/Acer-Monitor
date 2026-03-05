#!/usr/bin/env python3
"""
Acer Aspire 5 — Classificar Reinicialização
Abre uma janela para classificar o último reboot pendente no banco.

Uso:
    python classify_reboot.py
    python classify_reboot.py --db C:\outro\caminho\monitor.db
"""

import sqlite3
import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent


def parse_args():
    parser = argparse.ArgumentParser(description="Classificar último reboot pendente")
    parser.add_argument("--db", type=Path, default=BASE_DIR / "monitor.db",
                        help="Caminho para o banco de dados (padrão: monitor.db)")
    return parser.parse_args()


def toast(title, message):
    """Envia notificação toast nativa do Windows."""
    ps = f"""
Add-Type -AssemblyName System.Windows.Forms
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.BalloonTipIcon = 'Info'
$n.BalloonTipTitle = '{title}'
$n.BalloonTipText = '{message}'
$n.Visible = $true
$n.ShowBalloonTip(5000)
Start-Sleep -Milliseconds 5500
$n.Dispose()
"""
    subprocess.Popen(
        ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
        creationflags=subprocess.CREATE_NO_WINDOW
    )


def classify_dialog():
    """
    Exibe diálogo de classificação via PowerShell (nativo, sem tkinter).
    Retorna 'crash', 'intencional' ou None (pular).
    """
    ps = """
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Acer Crash Monitor'
$form.Size = New-Object System.Drawing.Size(420, 230)
$form.StartPosition = 'CenterScreen'
$form.TopMost = $true
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false

$label = New-Object System.Windows.Forms.Label
$label.Text = "Uma reinicializacao foi detectada.`n`nComo voce classifica esse evento?"
$label.Location = New-Object System.Drawing.Point(20, 20)
$label.Size = New-Object System.Drawing.Size(380, 60)
$form.Controls.Add($label)

$btnCrash = New-Object System.Windows.Forms.Button
$btnCrash.Text = "Crash (inesperado)"
$btnCrash.Location = New-Object System.Drawing.Point(20, 100)
$btnCrash.Size = New-Object System.Drawing.Size(160, 40)
$btnCrash.BackColor = [System.Drawing.Color]::FromArgb(220, 80, 80)
$btnCrash.ForeColor = [System.Drawing.Color]::White
$btnCrash.FlatStyle = 'Flat'
$btnCrash.Add_Click({ $form.Tag = 'crash'; $form.Close() })
$form.Controls.Add($btnCrash)

$btnIntent = New-Object System.Windows.Forms.Button
$btnIntent.Text = "Intencional (manual)"
$btnIntent.Location = New-Object System.Drawing.Point(200, 100)
$btnIntent.Size = New-Object System.Drawing.Size(160, 40)
$btnIntent.BackColor = [System.Drawing.Color]::FromArgb(50, 160, 100)
$btnIntent.ForeColor = [System.Drawing.Color]::White
$btnIntent.FlatStyle = 'Flat'
$btnIntent.Add_Click({ $form.Tag = 'intencional'; $form.Close() })
$form.Controls.Add($btnIntent)

$btnSkip = New-Object System.Windows.Forms.Button
$btnSkip.Text = "Pular"
$btnSkip.Location = New-Object System.Drawing.Point(160, 155)
$btnSkip.Size = New-Object System.Drawing.Size(100, 30)
$btnSkip.Add_Click({ $form.Tag = 'pular'; $form.Close() })
$form.Controls.Add($btnSkip)

$form.ShowDialog() | Out-Null
Write-Output $form.Tag
"""
    result = subprocess.run(
        ["powershell", "-WindowStyle", "Normal", "-Command", ps],
        capture_output=True, text=True
    )
    answer = result.stdout.strip()
    if answer == "crash":
        return "crash"
    elif answer == "intencional":
        return "intencional"
    return None


def main():
    args = parse_args()

    if not args.db.exists():
        print(f"Banco não encontrado: {args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # Busca o último reboot pendente (desconhecido)
    pending = conn.execute("""
        SELECT * FROM boot_events
        WHERE kind = 'desconhecido' AND notes != 'Primeira execução'
        ORDER BY ts DESC LIMIT 1
    """).fetchone()

    if not pending:
        print("Nenhuma reinicialização pendente de classificação.")
        toast("Acer Crash Monitor", "Nenhuma reinicializacao pendente.")
        conn.close()
        return

    print(f"Reinicialização pendente: {pending['ts'][:19]}")
    kind = classify_dialog()

    if kind is None:
        print("Classificação pulada.")
        conn.close()
        return

    notes = {
        "crash":      "Crash / reinicialização inesperada (confirmado pelo usuário)",
        "intencional": "Reinicialização manual pelo usuário",
    }[kind]

    conn.execute(
        "UPDATE boot_events SET kind = ?, notes = ? WHERE id = ?",
        (kind, notes, pending["id"])
    )
    conn.commit()
    conn.close()

    print(f"Classificado como: {kind}")
    toast("Acer Crash Monitor", f"Reboot classificado como: {kind}.")


if __name__ == "__main__":
    main()