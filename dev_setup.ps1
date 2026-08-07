# Phoenix Installer - Windows wrapper
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ScriptDir
python install.py @args
