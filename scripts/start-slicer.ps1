param([string]$SlicerPath = '')
$ErrorActionPreference = 'Stop'
$atlasRoot = Split-Path $PSScriptRoot -Parent
if (-not $SlicerPath) { $SlicerPath = Join-Path $atlasRoot 'tools\Slicer\Slicer.exe' }
if (-not (Test-Path -LiteralPath $SlicerPath)) { throw 'Slicer.exe not found; pass -SlicerPath or install Slicer first.' }
$atlasModulePaths = @((Join-Path $atlasRoot 'HeadNeckAtlas'))
$env:TOTALSEG_HOME_DIR = Join-Path $atlasRoot 'tools\model-cache'
$atlasExtensionsRoot = Join-Path $atlasRoot 'tools\extensions'
if (Test-Path -LiteralPath $atlasExtensionsRoot) {
    $atlasUpstreamModule = Get-ChildItem -LiteralPath $atlasExtensionsRoot -Filter 'TotalSegmentator.py' -Recurse | Select-Object -First 1
    if ($atlasUpstreamModule) { $atlasModulePaths += $atlasUpstreamModule.DirectoryName }
}
$atlasQuotedPaths = $atlasModulePaths | ForEach-Object { '"' + $_ + '"' }
$atlasLaunchArguments = @('--additional-module-paths') + $atlasQuotedPaths + @('--python-code', '"import slicer; slicer.util.selectModule(''HeadNeckAtlas''); slicer.util.mainWindow().showNormal(); slicer.util.mainWindow().raise_(); slicer.util.mainWindow().activateWindow()"')
Start-Process -FilePath $SlicerPath -ArgumentList $atlasLaunchArguments -WindowStyle Normal
