param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('backend', 'mock', 'frontend')]
    [string]$Service
)

$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'logs'
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

# Force UTF-8 on console and for python output, so Chinese logs stay readable
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Log($logPath) {
    process {
        Write-Host $_
        Add-Content -Path $logPath -Value ([string]$_) -Encoding utf8
    }
}

switch ($Service) {
    'backend' {
        Set-Location (Join-Path $root 'backend')
        $log = Join-Path $logDir 'backend.log'
        cmd /c ".\.venv\Scripts\python.exe -u app.py 2>&1" | Write-Log $log
    }
    'mock' {
        Set-Location (Join-Path $root 'backend')
        $log = Join-Path $logDir 'mock.log'
        cmd /c ".\.venv\Scripts\python.exe -u mock_server.py 2>&1" | Write-Log $log
    }
    'frontend' {
        Set-Location (Join-Path $root 'frontend')
        $log = Join-Path $logDir 'frontend.log'
        cmd /c "npm start 2>&1" | Write-Log $log
    }
}
