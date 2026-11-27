<#
Start-up tasks: the library server and the classifier start when Windows starts, before anyone logs on
(after a power cut, a Windows Update restart, or simply switching the PC on). No windows: their output
goes to biblioteca_udc\server\logs\server.log and udc_poc\logs\classifier.log.

Run as administrator, from install_autostart.bat (or: powershell -ExecutionPolicy Bypass -File
install_autostart.ps1). -Remove deletes the tasks (also the old "BibliotecaUDC" one that ran as SYSTEM).

The tasks run as the Windows user who installs them (not SYSTEM): the classifier model is in that user's
profile (.cache\huggingface) and the data files stay owned by that user. Windows stores the password to
start them without a logon; if the password changes, run this again.
#>
param([switch]$Remove)
$ErrorActionPreference = 'Stop'

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run it as administrator (right click on install_autostart.bat > Run as administrator).'
}

$server = $PSScriptRoot
$poc = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\udc_poc'))
$tasks = @(
    @{ Name = 'BibliotecaUDC'; Dir = $server; Bat = 'run_server.bat'; Delay = 'PT30S'
       What = 'Biblioteca UDC: library server (run_server.bat --log)' },
    @{ Name = 'BibliotecaUDC-Clasificador'; Dir = $poc; Bat = 'run_classifier.bat'; Delay = 'PT1M'
       What = 'Biblioteca UDC: classifier for the Analyze button (run_classifier.bat --log)' }
)

foreach ($t in $tasks) {
    if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
        Write-Host "Removed task $($t.Name)."
    }
}
if ($Remove) { return }

$user = "$env:USERDOMAIN\$env:USERNAME"
Write-Host ''
Write-Host "The tasks will run as $user, also when nobody is logged on."
Write-Host 'Windows needs that user''s password (with a Microsoft account: the account password, not the PIN).'
$secure = Read-Host "Password of $user" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew -Priority 4     # 4 = normal (the default, 7, slows the process down)

foreach ($t in $tasks) {
    $bat = Join-Path $t.Dir $t.Bat
    if (-not (Test-Path (Join-Path $t.Dir '.venv\Scripts\python.exe'))) {
        Write-Host "Skipped $($t.Name): $($t.Dir) has no .venv (not installed on this PC)."
        continue
    }
    $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"`"$bat`" --log`"" -WorkingDirectory $t.Dir
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay = $t.Delay                       # Tailscale and the network start first
    Register-ScheduledTask -TaskName $t.Name -Description $t.What -Action $action -Trigger $trigger `
        -Settings $settings -User $user -Password $password -RunLevel Limited -Force | Out-Null
    Write-Host "Registered $($t.Name): starts with Windows. Log: $(Join-Path $t.Dir 'logs')"
}
$password = $null

Write-Host ''
Write-Host 'Done. Close the run_server.bat / run_classifier.bat windows if they are open, then restart the PC'
Write-Host 'or start the tasks now:  schtasks /Run /TN BibliotecaUDC  (and BibliotecaUDC-Clasificador)'
