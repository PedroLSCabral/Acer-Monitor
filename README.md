# Acer Aspire 5 — Crash Monitor

Monitor de sistema em background para investigar reinicializações aleatórias no Acer Aspire 5. Coleta dados de CPU, temperatura, RAM, bateria e processos a cada 5 segundos, detecta reboots automaticamente e armazena tudo num banco SQLite para análise de padrões.

> Desenvolvido para Windows 11, mas adaptável a outros modelos com o mesmo problema.

---

## Funcionalidades

- Coleta contínua de métricas do sistema (CPU, RAM, disco, rede, bateria)
- Leitura de temperatura via `LibreHardwareMonitorLib.dll` (sem WMI, sem programa externo)
- Detecção automática de reinicializações ao iniciar
- **Classificação de reinicializações** — distingue crashes de desligamentos intencionais
- **Detecção de shutdown limpo** — identifica automaticamente se o monitor foi encerrado normalmente ou abruptamente
- Alertas registrados quando CPU/temperatura/RAM passam de limites críticos
- Dashboard HTML com gráficos interativos
- Script de análise que examina o que acontecia nos minutos antes de cada crash

---

## Pré-requisitos

- Python 3.10 ou superior → [python.org](https://python.org) (marque **"Add Python to PATH"**)
- `LibreHardwareMonitorLib.dll` na pasta do projeto (veja abaixo)

---

## Instalação

### 1. Clone o repositório

```powershell
git clone https://github.com/SEU_USUARIO/acer-crash-monitor.git
cd acer-crash-monitor
```

### 2. Instale as dependências

```powershell
pip install psutil pythonnet
```

### 3. Obtenha a DLL de temperatura

O Windows não expõe temperatura de CPU nativamente. É necessária a DLL do LibreHardwareMonitor:

1. Baixe o `.zip` em: [LibreHardwareMonitor Releases](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases)
2. Extraia o arquivo
3. Crie a pasta `libs/` na raiz do projeto
4. Copie `LibreHardwareMonitorLib.dll` e todas as outras `.dll` para dentro de `libs/`

> A pasta `libs/` não está incluída no repositório pois contém binários de terceiros. O monitor funciona sem ela, mas sem leitura de temperatura.

### 4. Teste a leitura de temperatura

Abra o **PowerShell como Administrador** e rode:

```powershell
python lhm_reader.py
```

Se as temperaturas aparecerem, está tudo pronto.

---

## Uso

### Rodar manualmente

```powershell
# Com janela (você vê os logs em tempo real)
python monitor.py

# Em background, sem janela
pythonw monitor.py

# Ver status atual (se está rodando, última coleta, crashes)
python monitor.py --status
```

### Iniciar automaticamente com o Windows (recomendado)

O `watchdog.py` é o processo que deve ser registrado no Task Scheduler. Ele inicia o `monitor.py` e o reinicia automaticamente se ele travar ou encerrar inesperadamente.

Via PowerShell como Administrador:

```powershell
$dir = "C:\Users\$env:USERNAME\acer-crash-monitor"
$action = New-ScheduledTaskAction -Execute "pythonw.exe" -Argument "watchdog.py" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtLogon
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "AcerMonitor" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest
```

Ou importe o arquivo `AcerMonitor_Task.xml` diretamente no **Agendador de Tarefas** (Task Scheduler), ajustando o caminho da pasta.

> O watchdog e o monitor precisam rodar como Administrador para ler temperaturas via DLL.

---

## Classificação de reinicializações

Ao iniciar após um reboot, o monitor combina duas estratégias para classificar o evento:

**Detecção de shutdown limpo (automática):** ao ser encerrado normalmente — via Ctrl+C ou pelo Task Scheduler — o monitor cria um arquivo `.clean_shutdown` na pasta. Se esse arquivo não existir na próxima inicialização, significa que o processo foi interrompido abruptamente, o que indica um possível crash.

**Notificação toast (Windows nativa):** ao detectar um reboot, o monitor envia uma notificação toast nativa do Windows avisando o evento e orientando o usuário a classificá-lo. Não requer nenhuma dependência extra — usa PowerShell nativo.

**Classificação manual via `classify_reboot.py`:** abre uma janela para classificar o último reboot pendente no banco.

```powershell
python classify_reboot.py

# Banco em outro caminho
python classify_reboot.py --db D:\backups\monitor.db
```

As opções são **Crash (inesperado)**, **Intencional (manual)** ou **Pular**. O dashboard reflete essa classificação com badges coloridos: 💥 Crash, ✋ Intencional e ❓ Desconhecido. O contador de reinicializações no topo conta apenas os crashes confirmados.

---

## Dashboard

```powershell
# Uso padrão
python dashboard.py

# Banco em outro caminho
python dashboard.py --db D:\backups\monitor.db

# Gerar sem abrir o navegador
python dashboard.py --no-open

# Caminho de saída personalizado
python dashboard.py --output relatorio.html
```

Gera um `dashboard.html` com gráficos de temperatura, CPU e RAM ao longo do tempo, histórico de reinicializações e alertas registrados.

---

## Análise de padrões

```powershell
# Uso padrão (5 min de janela, todos os reboots)
python analyze.py

# Janela de 10 minutos antes de cada reboot
python analyze.py --window 10

# Apenas crashes confirmados
python analyze.py --only-crashes

# Banco em outro caminho
python analyze.py --db D:\backups\monitor.db
```

Examina os minutos antes de cada crash e calcula médias e máximos de cada métrica, sinalizando prováveis causas como superaquecimento, CPU saturada ou bateria crítica.

---

## Arquivos do projeto

```
acer-crash-monitor/
├── libs/                   # DLLs do LibreHardwareMonitor (não versionado)
├── monitor.py              # Daemon principal de coleta
├── watchdog.py             # Mantém o monitor.py sempre em execução
├── classify_reboot.py      # Classificação manual de reboots pendentes
├── lhm_reader.py           # Teste isolado de leitura de temperatura
├── dashboard.py            # Gerador do relatório HTML
├── analyze.py              # Análise de padrões pré-crash
├── config.json             # Configurações de thresholds e caminhos
├── AcerMonitor_Task.xml    # Configuração do Task Scheduler
└── README.md
```

Arquivos gerados em tempo de execução (ignorados pelo git):

```
├── monitor.db              # Banco SQLite com todos os dados
├── monitor.log             # Log de execução
├── dashboard.html          # Relatório gerado
├── .clean_shutdown         # Flag de encerramento limpo (criado/removido automaticamente)
└── *.dll                   # DLLs do LibreHardwareMonitor
```

---

## O que é coletado

A cada 5 segundos:

| Métrica | Detalhes |
|---------|----------|
| CPU | Uso % e frequência MHz |
| Temperatura | CPU e GPU via LibreHardwareMonitor |
| Memória | RAM usada/total/% e swap % |
| Disco | Uso % e bytes de leitura/escrita |
| Rede | Bytes enviados/recebidos |
| Bateria | % e estado (plugado / bateria) |
| Processos | Contagem total e top 5 por CPU |
| Boot | Detecção automática de reinicialização |

---

## Consultas SQL úteis

Abra `monitor.db` com o [DB Browser for SQLite](https://sqlitebrowser.org):

```sql
-- Momentos com temperatura mais alta
SELECT ts, cpu_temp, cpu_pct, ram_pct
FROM snapshots
ORDER BY cpu_temp DESC
LIMIT 50;

-- O que acontecia nos 10 min antes do último reboot
SELECT ts, cpu_pct, cpu_temp, ram_pct, battery_pct
FROM snapshots
WHERE ts < (SELECT last_snap_ts FROM boot_events ORDER BY id DESC LIMIT 1)
ORDER BY ts DESC
LIMIT 120;

-- Todos os alertas de temperatura
SELECT * FROM alerts WHERE kind = 'temp' ORDER BY ts DESC;

-- Estava plugado na tomada quando reiniciou?
SELECT b.ts, b.notes,
       (SELECT battery_plugged FROM snapshots
        WHERE ts <= b.last_snap_ts ORDER BY ts DESC LIMIT 1) as plugged
FROM boot_events b;

-- Apenas crashes confirmados
SELECT ts, boot_time, last_snap_ts, notes
FROM boot_events
WHERE kind = 'crash'
ORDER BY ts DESC;
```

---

## Contexto

O Acer Aspire 5 tem um defeito conhecido de reinicialização aleatória em algumas unidades. Este projeto nasceu da necessidade de coletar dados suficientes para identificar se o problema é térmico, elétrico (bateria/fonte) ou relacionado a carga de software — informação útil tanto para diagnóstico próprio quanto para suporte técnico.

---

## Licença

MIT