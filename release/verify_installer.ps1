param([string]$Installer = "", [string]$Blender = "")
$ErrorActionPreference = 'Stop'
$releaseRoot = $PSScriptRoot
if (-not $Installer) {
    $version = (Get-Content -LiteralPath (Join-Path (Split-Path -Parent $releaseRoot) 'VERSION') -Raw).Trim()
    $Installer = Join-Path $releaseRoot "output\MSFSModelBuilder-$version-Setup.exe"
}
$Installer = (Resolve-Path -LiteralPath $Installer).Path
$registration = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{DC7C8B8E-E8C6-4890-B788-193723B427D9}_is1'
if (Test-Path -LiteralPath $registration) { throw 'An installed release already exists. Smoke install must not overwrite its registration.' }
$testId = [guid]::NewGuid().ToString('N')
$installRoot = Join-Path $releaseRoot "install-smoke-$testId"
$testData = Join-Path $releaseRoot "smoke-data-$testId"
New-Item -ItemType Directory -Path $testData -Force | Out-Null
$previousLocal = $env:LOCALAPPDATA
try {
    $args = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/TASKS=',
              "/DIR=`"$installRoot`"", '/GROUP="MSFS Model Builder Smoke Test"',
              "/LOG=`"$(Join-Path $testData 'install.log')`"")
    $setup = Start-Process -FilePath $Installer -ArgumentList $args -WindowStyle Hidden -PassThru -Wait
    if ($setup.ExitCode -ne 0) { throw "Installer returned $($setup.ExitCode)" }
    $app = Join-Path $installRoot 'MSFSBuilder.exe'
    $cli = Join-Path $installRoot 'MSFSBuilderCLI.exe'
    if (-not (Test-Path -LiteralPath $app) -or -not (Test-Path -LiteralPath $cli)) { throw 'Installed executables missing.' }
    & $cli --help
    if ($LASTEXITCODE -ne 0) { throw 'Installed CLI failed.' }
    $smoke = Start-Process -FilePath $app -ArgumentList '--self-test' -WindowStyle Hidden -PassThru -Wait
    if ($smoke.ExitCode -ne 0) { throw 'Installed GUI self-test failed.' }
    $env:LOCALAPPDATA = $testData
    # This test only persists a path; it does not start Blender. An existing
    # executable is sufficient when Blender is absent on the build machine.
    $blender = if ($Blender) { $Blender } else { $cli }
    $config = Start-Process -FilePath $app -ArgumentList @('--configure-only', '--configure-msfs', "`"$testData`"", '--configure-blender', "`"$blender`"") -WindowStyle Hidden -PassThru -Wait
    if ($config.ExitCode -ne 0) { throw 'Installed configuration failed.' }
    $settings = Join-Path $testData 'MSFSModelBuilder\settings.json'
    $saved = Get-Content -LiteralPath $settings -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($saved.msfs_root -ne $testData -or $saved.blender -ne $blender) { throw 'Installer configuration arguments were not persisted.' }
    $uninstaller = Join-Path $installRoot 'unins000.exe'
    $uninstall = Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=`"$(Join-Path $testData 'uninstall.log')`"") -WindowStyle Hidden -PassThru -Wait
    if ($uninstall.ExitCode -ne 0) { throw "Uninstaller returned $($uninstall.ExitCode)" }
    if (Test-Path -LiteralPath $app) { throw 'App was not uninstalled.' }
    if (-not (Test-Path -LiteralPath $settings)) { throw 'Uninstaller removed user settings.' }
    Write-Output "Installer smoke passed; logs: $testData"
} finally {
    # Also remove the isolated test install after a failing assertion.
    $cleanup = Join-Path $installRoot 'unins000.exe'
    if (Test-Path -LiteralPath $cleanup) {
        $cleanupProcess = Start-Process -FilePath $cleanup -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -WindowStyle Hidden -PassThru -Wait
    }
    $env:LOCALAPPDATA = $previousLocal
}
