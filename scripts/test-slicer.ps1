param([string]$SlicerPath = '')
$ErrorActionPreference = 'Stop'
$atlasRoot = Split-Path $PSScriptRoot -Parent
if (-not $SlicerPath) { $SlicerPath = Join-Path $atlasRoot 'tools\Slicer\Slicer.exe' }
if (-not (Test-Path -LiteralPath $SlicerPath)) { throw 'Slicer.exe not found; pass -SlicerPath.' }
$atlasResults = Join-Path $atlasRoot 'test-results'
New-Item -ItemType Directory -Path $atlasResults -Force | Out-Null
$atlasModulePaths = @(('"' + $atlasRoot + '\HeadNeckAtlas"'))
$atlasExtensionDirectory = Join-Path $atlasRoot 'tools\extensions'
if (Test-Path -LiteralPath $atlasExtensionDirectory) {
    $atlasUpstreamFile = Get-ChildItem -LiteralPath $atlasExtensionDirectory -Filter 'TotalSegmentator.py' -Recurse | Select-Object -First 1
    if ($atlasUpstreamFile) { $atlasModulePaths += ('"' + $atlasUpstreamFile.DirectoryName + '"') }
}
$atlasArguments = @('--no-splash', '--ignore-slicerrc', '--additional-module-paths') + $atlasModulePaths + @('--python-script', ('"' + $atlasRoot + '\tests\slicer_smoke.py"'))
$atlasProcess = Start-Process -FilePath $SlicerPath -ArgumentList $atlasArguments -WindowStyle Hidden -RedirectStandardOutput (Join-Path $atlasResults 'slicer-stdout.log') -RedirectStandardError (Join-Path $atlasResults 'slicer-stderr.log') -PassThru
$atlasProcess.WaitForExit()
Get-Content -LiteralPath (Join-Path $atlasResults 'slicer-smoke-result.json')
exit $atlasProcess.ExitCode
