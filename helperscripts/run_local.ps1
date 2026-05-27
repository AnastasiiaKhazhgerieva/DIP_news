# run_local.ps1 -- prepare a local PowerShell session for dip_news.py
#
# What it does:
#   * loads every secret from keys\*.txt into the current shell's env vars
#   * activates .\.venv (if present) so `python` points at the venv interpreter
# It does NOT run dip_news.py -- launch the pipeline yourself afterwards, e.g.:
#     python .\dip_news.py
#     python .\dip_news.py --stage scrape
#     python .\dip_news.py --stage lists prioritise design
#
# Usage (from PowerShell, in the news/ folder):
#     . .\run_local.ps1                 # dot-source so env vars persist
#     .\run_local.ps1                   # also works; env vars survive because
#                                       # we use $env:VAR which is process-scoped
#
# If the script is blocked, run once for the current user:
#     Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Read-Key([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required key file is missing: $path"
    }
    return (Get-Content -Raw -Encoding UTF8 -LiteralPath $path).Trim()
}

# Match USE_SANDBOX in dip_news.py: $true -> sandbox folders + sandbox tg keys
$useSandbox = $True

if ($useSandbox) {
    $env:FOLDERS_SANDBOX    = Read-Key ".\keys\folders_sandbox.txt"
    $env:TELEGRAM_BOT_TOKEN = Read-Key ".\keys\TELEGRAM_BOT_TOKEN.txt"
    $env:TELEGRAM_CHAT_ID   = Read-Key ".\keys\TELEGRAM_CHAT_ID.txt"
}
else {
    $env:FOLDERS_MAIN       = Read-Key ".\keys\folders_main.txt"
    $env:TELEGRAM_BOT_TOKEN = Read-Key ".\keys\A\TELEGRAM_BOT_TOKEN.txt"
    $env:TELEGRAM_CHAT_ID   = Read-Key ".\keys\A\TELEGRAM_CHAT_ID.txt"
}

$env:PROXY            = Read-Key ".\keys\proxy.txt"
$env:GOOGLE_TOKEN_B64 = Read-Key ".\keys\GOOGLE_TOKEN_B64.txt"
#$env:DEEPSEEK_API_KEY = Read-Key ".\keys\deepseek_api_key.txt"
$env:OPENROUTER_API_KEY = Read-Key ".\keys\openrouter.txt"

$activate = ".\.venv\Scripts\Activate.ps1"
if (Test-Path -LiteralPath $activate) {
    & $activate
    Write-Host "Activated venv: $activate"
} else {
    Write-Warning ".venv not found at $activate - using system 'python'."
}

Write-Host ("Environment ready (sandbox = {0})." -f $useSandbox)
Write-Host "Now run the pipeline yourself, e.g.:"
Write-Host "    python .\dip_news.py"
Write-Host "    python .\dip_news.py --stage scrape"
Write-Host "    python .\dip_news.py --stage lists prioritise design"
