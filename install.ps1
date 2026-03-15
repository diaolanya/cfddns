# DDNS Daemon Windows 安装脚本
# 需要以管理员权限运行

param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$TaskName = "DDNS-Daemon"

# 检查管理员权限
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "错误: 需要管理员权限运行此脚本" -ForegroundColor Red
    Write-Host "请右键点击 PowerShell，选择'以管理员身份运行'" -ForegroundColor Yellow
    pause
    exit 1
}

# 检查 Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "错误: 未找到 Python" -ForegroundColor Red
    Write-Host "请先安装 Python: https://www.python.org/downloads/" -ForegroundColor Yellow
    pause
    exit 1
}

# 检查配置文件
if (-not (Test-Path "$ScriptDir\config.json")) {
    Write-Host "错误: 未找到配置文件 config.json" -ForegroundColor Red
    Write-Host "请先复制 config.json.example 并填写配置" -ForegroundColor Yellow
    pause
    exit 1
}

if ($Uninstall) {
    # 卸载
    Write-Host "正在卸载 DDNS Daemon..." -ForegroundColor Yellow

    # 停止并删除任务计划
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "已删除任务计划" -ForegroundColor Green
    }

    # 删除 VBS 启动器
    if (Test-Path "$ScriptDir\run_hidden.vbs") {
        Remove-Item "$ScriptDir\run_hidden.vbs" -Force
        Write-Host "已删除 VBS 启动器" -ForegroundColor Green
    }

    Write-Host "卸载完成!" -ForegroundColor Green
    pause
    exit 0
}

# 安装
Write-Host "正在安装 DDNS Daemon..." -ForegroundColor Yellow

# 创建 VBS 启动器（隐藏窗口运行）
$vbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "$ScriptDir"
WshShell.Run "pythonw.exe ddns_daemon.py", 0, False
"@

Set-Content -Path "$ScriptDir\run_hidden.vbs" -Value $vbsContent -Encoding ASCII
Write-Host "已创建 VBS 启动器" -ForegroundColor Green

# 创建任务计划
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$ScriptDir\run_hidden.vbs`"" -WorkingDirectory $ScriptDir

# 用户登录时启动
$trigger = New-ScheduledTaskTrigger -AtLogOn

# 设置
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit 0

# 注册任务
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "已创建任务计划: $TaskName" -ForegroundColor Green

# 立即启动
Start-ScheduledTask -TaskName $TaskName
Write-Host "已启动 DDNS Daemon" -ForegroundColor Green

Write-Host ""
Write-Host "安装完成!" -ForegroundColor Green
Write-Host ""
Write-Host "常用命令:"
Write-Host "  查看状态:   Get-ScheduledTask -TaskName $TaskName"
Write-Host "  停止服务:   Stop-ScheduledTask -TaskName $TaskName"
Write-Host "  启动服务:   Start-ScheduledTask -TaskName $TaskName"
Write-Host "  卸载:       .\install.ps1 -Uninstall"
Write-Host "  查看日志:   Get-Content $ScriptDir\ddns.log -Tail 50 -Wait"
Write-Host ""
Write-Host "请确保已正确配置 config.json 文件" -ForegroundColor Yellow
pause