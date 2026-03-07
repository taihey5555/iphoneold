$ErrorActionPreference = "Stop"

$taskNames = @(
  "iPhoneOldMonitor-0900",
  "iPhoneOldMonitor-1400",
  "iPhoneOldMonitor-2100"
)

$taskPath = "\"
$projectRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $projectRoot "run_monitor_task.ps1"
$taskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$runAsUser = "MSI\koko3"

if (-not (Test-Path $scriptPath)) {
  throw "script not found: $scriptPath"
}

# Ask password once and reuse for all tasks.
$secure = Read-Host "Enter Windows password for $runAsUser" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
  $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

if ([string]::IsNullOrWhiteSpace($password)) {
  throw "password is required"
}

foreach ($name in $taskNames) {
  try {
    & schtasks /Delete /TN "$taskPath$name" /F | Out-Null
  } catch {
    # Ignore when task does not exist.
  }
}

& schtasks /Create /TN "$taskPath$($taskNames[0])" /SC DAILY /ST 09:00 /TR $taskCommand /RU $runAsUser /RP $password /RL HIGHEST /F | Out-Null
& schtasks /Create /TN "$taskPath$($taskNames[1])" /SC DAILY /ST 14:00 /TR $taskCommand /RU $runAsUser /RP $password /RL HIGHEST /F | Out-Null
& schtasks /Create /TN "$taskPath$($taskNames[2])" /SC DAILY /ST 21:00 /TR $taskCommand /RU $runAsUser /RP $password /RL HIGHEST /F | Out-Null

# Ensure battery mode does not block/stop tasks and wake if sleeping.
foreach ($name in $taskNames) {
  $task = Get-ScheduledTask -TaskPath $taskPath -TaskName $name
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun -StartWhenAvailable
  $setOk = $false
  foreach ($userCandidate in @($runAsUser, $env:USERNAME)) {
    try {
      Set-ScheduledTask -TaskPath $taskPath -TaskName $name -Action $task.Actions -Trigger $task.Triggers -Settings $settings -User $userCandidate -Password $password | Out-Null
      $setOk = $true
      break
    } catch {
      # Try next user format.
    }
  }
  if (-not $setOk) {
    Write-Warning "Could not update power settings via Set-ScheduledTask for $name. Task was created, but battery settings may need GUI update."
  }
}

Write-Host "Recreated tasks:"
foreach ($name in $taskNames) {
  schtasks /Query /TN "$taskPath$name" /V /FO LIST | findstr /I "TaskName Next Run Time Logon Mode Power Management Last Run Time Last Result"
  Write-Host ""
}
