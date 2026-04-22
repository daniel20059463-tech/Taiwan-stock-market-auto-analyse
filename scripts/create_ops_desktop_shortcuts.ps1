$ErrorActionPreference = "Stop"

$desktop = [Environment]::GetFolderPath("Desktop")
$workspace = "E:\claude code test"
$docsDir = Join-Path $workspace "docs"
$logsDir = Join-Path $workspace "logs"

$targets = @(
    @{
        ShortcutName = "TAR Daily Checklist.lnk"
        TargetPath = "notepad.exe"
        Arguments = "`"$docsDir\daily_live_ops_checklist.md`""
        WorkingDirectory = $docsDir
        Description = "Open Taiwan Alpha Radar daily duty checklist."
    },
    @{
        ShortcutName = "TAR Daily SOP.lnk"
        TargetPath = "notepad.exe"
        Arguments = "`"$docsDir\daily_live_ops_sop.md`""
        WorkingDirectory = $docsDir
        Description = "Open Taiwan Alpha Radar daily live operations SOP."
    },
    @{
        ShortcutName = "TAR Logs.lnk"
        TargetPath = "explorer.exe"
        Arguments = "`"$logsDir`""
        WorkingDirectory = $logsDir
        Description = "Open Taiwan Alpha Radar logs folder."
    }
)

$shell = New-Object -ComObject WScript.Shell

foreach ($item in $targets) {
    $shortcutPath = Join-Path $desktop $item.ShortcutName
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $item.TargetPath
    $shortcut.Arguments = $item.Arguments
    $shortcut.WorkingDirectory = $item.WorkingDirectory
    $shortcut.Description = $item.Description
    $shortcut.Save()
}

Get-ChildItem -LiteralPath $desktop |
    Where-Object { $_.Name -like 'TAR *' } |
    Select-Object Name, FullName, LastWriteTime |
    Sort-Object Name
