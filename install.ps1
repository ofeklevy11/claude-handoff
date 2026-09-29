# claude-handoff one-line install (Windows PowerShell):
#   irm https://raw.githubusercontent.com/ofeklevy11/claude-handoff/v1.0.5/install.ps1 | iex
# Same as typing in Claude Code:  /plugin marketplace add ofeklevy11/claude-handoff
#                                 /plugin install handoff@claude-handoff
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host "claude-handoff: Claude Code CLI not found. Install it first: https://claude.com/claude-code" -ForegroundColor Red
    return
}
$py = @('python3', 'python', 'py') | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Select-Object -First 1
if (-not $py) {
    Write-Host "claude-handoff: warning: Python 3.8+ not found. The plugin installs, but needs Python to run." -ForegroundColor Yellow
}
claude plugin marketplace add ofeklevy11/claude-handoff
if ($LASTEXITCODE -ne 0) { claude plugin marketplace update claude-handoff }
claude plugin install handoff@claude-handoff
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "claude-handoff installed. Open a NEW Claude Code session and it is active." -ForegroundColor Green
}
