# デスクトップショートカット作成スクリプト
# PowerShellで実行: 右クリック → PowerShellで実行

$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$batFile    = Join-Path $scriptDir "AI積算システム起動.bat"
$icoFile    = Join-Path $scriptDir "painting_ai.ico"
$shortcut   = "$env:USERPROFILE\Desktop\AI積算システム.lnk"

$wsh    = New-Object -ComObject WScript.Shell
$lnk    = $wsh.CreateShortcut($shortcut)

$lnk.TargetPath       = $batFile
$lnk.WorkingDirectory = $scriptDir
$lnk.IconLocation     = $icoFile
$lnk.Description      = "塗装会社専用 AI積算・見積りシステム"
$lnk.WindowStyle      = 1

$lnk.Save()

Write-Host ""
Write-Host "  ショートカットをデスクトップに作成しました！" -ForegroundColor Green
Write-Host "  場所: $shortcut" -ForegroundColor Cyan
Write-Host ""
Write-Host "  デスクトップの「AI積算システム」をダブルクリックして起動できます。"
Write-Host ""

Read-Host "Enterキーで閉じる"
