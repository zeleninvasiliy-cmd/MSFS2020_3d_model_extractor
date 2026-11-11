param(
    [string]$Python = "",
    [string]$ISCC = "C:\Program Files\Inno Setup 7\ISCC.exe",
    [switch]$SkipFreeze
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$packageRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $Python = Join-Path $packageRoot '.venv-release\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Build Python missing: $Python. Create a venv, install release/build_requirements.txt, and pass -Python <path>."
}
if (-not (Test-Path -LiteralPath $ISCC)) { throw "Inno Setup compiler missing: $ISCC" }

$buildRoot = Join-Path $PSScriptRoot 'build'
$distRoot = Join-Path $PSScriptRoot 'dist'
$installerRoot = Join-Path $PSScriptRoot 'output'
New-Item -ItemType Directory -Path $buildRoot,$distRoot,$installerRoot -Force | Out-Null
$version = (Get-Content -LiteralPath (Join-Path $packageRoot 'VERSION') -Raw).Trim()
$versionMatch = [regex]::Match($version, '^(?<major>\d+)\.(?<minor>\d+)\.(?<patch>\d+)$')
if (-not $versionMatch.Success) {
    throw "VERSION must use three numeric components (major.minor.patch): $version"
}
$versionTemplate = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'version_info.template.txt') -Raw
$versionTemplate = $versionTemplate.Replace('@VERSION_MAJOR@', $versionMatch.Groups['major'].Value)
$versionTemplate = $versionTemplate.Replace('@VERSION_MINOR@', $versionMatch.Groups['minor'].Value)
$versionTemplate = $versionTemplate.Replace('@VERSION_PATCH@', $versionMatch.Groups['patch'].Value)
$versionTemplate = $versionTemplate.Replace('@VERSION@', $version)
$generatedVersionInfo = Join-Path $buildRoot 'version_info.txt'
[System.IO.File]::WriteAllText($generatedVersionInfo, $versionTemplate, [System.Text.UTF8Encoding]::new($false))
$common = @('--noconfirm', '--clean', '--onedir', '--distpath', $distRoot,
            '--workpath', $buildRoot, '--specpath', $buildRoot,
            '--paths', $packageRoot, '--paths', (Join-Path $packageRoot 'scripts'),
            '--version-file', $generatedVersionInfo,
            '--hidden-import', 'msfs_universal', '--add-data', ((Join-Path $packageRoot 'scripts') + ';scripts'),
            '--add-data', ((Join-Path $packageRoot 'VERSION') + ';.'))

$appRoot = Join-Path $distRoot 'MSFSBuilder'
$cliRoot = Join-Path $distRoot 'MSFSBuilderCLI'
if (-not $SkipFreeze) {
    & $Python -m PyInstaller @common --windowed --name MSFSBuilder (Join-Path $packageRoot 'msfs_builder_gui.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller GUI build failed.' }
    & $Python -m PyInstaller @common --console --name MSFSBuilderCLI (Join-Path $PSScriptRoot 'cli_entry.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller CLI build failed.' }
    # Both executables use the common _internal runtime. Only generated build
    # artifacts are updated, never source files or user projects.
    Copy-Item -Path (Join-Path $cliRoot '*') -Destination $appRoot -Recurse -Force
}
Copy-Item -LiteralPath (Join-Path $packageRoot 'VERSION') -Destination $appRoot -Force
$docRoot = Join-Path $appRoot 'docs'
New-Item -ItemType Directory -Path $docRoot -Force | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot 'docs\*') -Destination $docRoot -Recurse -Force
# The repository keeps one canonical user guide per language.  Remove stale
# Markdown files from a reused dist directory before copying the current pair.
Get-ChildItem -LiteralPath $docRoot -Filter '*.md' -File -ErrorAction SilentlyContinue |
    Remove-Item -Force
Copy-Item -LiteralPath (Join-Path $packageRoot 'USER_GUIDE.md'),(Join-Path $packageRoot 'USER_GUIDE_EN.md') -Destination $docRoot -Force
$licenseRoot = Join-Path $appRoot 'licenses'
New-Item -ItemType Directory -Path $licenseRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $packageRoot 'LICENSE') -Destination (Join-Path $licenseRoot 'Project-LICENSE') -Force
Copy-Item -LiteralPath (Join-Path $packageRoot 'LICENSE_NOTICE.md') -Destination (Join-Path $licenseRoot 'Project-LICENSE-NOTICE.md') -Force
$basePython = (& $Python -X utf8 -c 'import sys; print(sys.base_prefix)').Trim()
Copy-Item -LiteralPath (Join-Path $basePython 'LICENSE.txt') -Destination (Join-Path $licenseRoot 'Python-LICENSE.txt') -Force
$tkLicense = Join-Path $basePython 'tcl\tk8.6\license.terms'
if (Test-Path -LiteralPath $tkLicense) {
    Copy-Item -LiteralPath $tkLicense -Destination (Join-Path $licenseRoot 'Tk-license.terms') -Force
}
$pyInstallerLicense = (& $Python -X utf8 -c "import importlib.metadata as m; print(m.distribution('pyinstaller').locate_file('pyinstaller-6.16.0.dist-info/licenses/COPYING.txt'))").Trim()
Copy-Item -LiteralPath $pyInstallerLicense -Destination (Join-Path $licenseRoot 'PyInstaller-COPYING.txt') -Force

& $ISCC /Q "/DAppVersion=$version" "/DAppSource=$appRoot" "/DOutputDir=$installerRoot" (Join-Path $PSScriptRoot 'MSFSModelBuilder.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup build failed.' }
$installer = Join-Path $installerRoot "MSFSModelBuilder-$version-Setup.exe"
$portable = Join-Path $installerRoot "MSFSModelBuilder-$version-Portable.zip"
Compress-Archive -Path $appRoot -DestinationPath $portable -Force
$hashes = @($installer, $portable) | ForEach-Object {
    $hash = Get-FileHash -LiteralPath $_ -Algorithm SHA256
    "$($hash.Hash.ToLowerInvariant())  $([System.IO.Path]::GetFileName($_))"
}
[System.IO.File]::WriteAllLines((Join-Path $installerRoot 'SHA256SUMS.txt'), $hashes, [System.Text.UTF8Encoding]::new($false))
$hashes | Write-Output
Write-Output "Installer ready: $installer"
Write-Output "Portable ready: $portable"
