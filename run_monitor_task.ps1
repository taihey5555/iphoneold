$ErrorActionPreference = "Continue"

$projectRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($projectRoot)) {
  if (-not [string]::IsNullOrWhiteSpace($MyInvocation.MyCommand.Path)) {
    $projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
  } else {
    $projectRoot = (Get-Location).Path
  }
}
$pythonExe = "C:\Users\koko3\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\python.exe"
$logDir = Join-Path $projectRoot "logs"
$logFile = Join-Path $logDir "monitor.log"
$maxLogBytes = 5MB

if (-not (Test-Path $logDir)) {
  New-Item -ItemType Directory -Path $logDir | Out-Null
}

function Write-Log {
  param([string]$Message)
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  "$ts $Message" | Out-File -FilePath $logFile -Append -Encoding UTF8
}

function Rotate-LogIfNeeded {
  if (-not (Test-Path $logFile)) {
    return
  }

  # 1) UTF-16ログを検出したら退避して、以降UTF-8に切り替える
  $bytes = [System.IO.File]::ReadAllBytes($logFile)
  if (
    ($bytes.Length -ge 2) -and
    (
      (($bytes[0] -eq 0xFF) -and ($bytes[1] -eq 0xFE)) -or
      (($bytes[0] -eq 0xFE) -and ($bytes[1] -eq 0xFF))
    )
  ) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $utf16Backup = Join-Path $logDir "monitor-utf16-$stamp.log"
    Move-Item -Path $logFile -Destination $utf16Backup -Force
    return
  }

  # 1.5) UTF-8ヘッダ付きでもNUL混在（過去の混在ログ）の場合は退避
  if ([Array]::IndexOf($bytes, [byte]0x00) -ge 0) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $mixedBackup = Join-Path $logDir "monitor-mixed-$stamp.log"
    Move-Item -Path $logFile -Destination $mixedBackup -Force
    return
  }

  # 2) 簡易ローテーション: 5MB超で退避
  $info = Get-Item $logFile
  if ($info.Length -ge $maxLogBytes) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $rotated = Join-Path $logDir "monitor-$stamp.log"
    Move-Item -Path $logFile -Destination $rotated -Force
  }
}

Rotate-LogIfNeeded
Write-Log "[INFO] scheduled run started"
Write-Log "[INFO] project_root=$projectRoot"
Write-Log "[INFO] python_exe=$pythonExe"

try {
  Set-Location $projectRoot
  if (-not (Test-Path $pythonExe)) {
    throw "python executable not found: $pythonExe"
  }

  # NOTE:
  # $LASTEXITCODE が空になるケースに備えて、$? でフォールバックして必ず数値化する。
  $global:LASTEXITCODE = $null
  $outputLines = & $pythonExe -m app.main --config config.yaml --env .env --verbose run-once 2>&1

  foreach ($line in $outputLines) {
    if ($null -ne $line) {
      $clean = ("$line" -replace "`0", "")
      Write-Log $clean
    }
  }

  if ($null -ne $LASTEXITCODE) {
    $exitCode = [int]$LASTEXITCODE
  } elseif ($?) {
    $exitCode = 0
  } else {
    $exitCode = 1
  }
  Write-Log "[INFO] run exit_code=$exitCode"
} catch {
  Write-Log "[ERROR] $($_.Exception.Message)"
}

Write-Log "[INFO] scheduled run finished"
