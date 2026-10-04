param(
    [Parameter(Mandatory=$true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$configPath = Join-Path $PSScriptRoot 'local-settings.json'
if (-not (Test-Path -LiteralPath $configPath)) { throw 'See README.md: local-settings.json is required.' }
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
foreach ($name in @('Python', 'ISCC', 'ComfyRoot', 'PythonRoot', 'PayloadRoot')) {
    if (-not (Test-Path -LiteralPath $config.$name)) { throw "Missing configured path: $name" }
}
if ($config.BuildDependencies) { $env:PYTHONPATH = $config.BuildDependencies }
$installer = Get-Content -LiteralPath 'installer.iss' -Raw
$previous = [regex]::Match($installer, '(?m)^AppVersion=(\d+\.\d+\.\d+)').Groups[1].Value
if ([version]$Version -le [version]$previous) { throw 'Use a version newer than the current AppVersion. To retry a publish, run python publish.py.' }
& $config.Python app.py --self-test
if ($LASTEXITCODE -ne 0) { throw 'App self-test failed' }
& $config.Python test_publish.py
if ($LASTEXITCODE -ne 0) { throw 'Publish self-test failed' }
$installer = $installer.Replace("AppVersion=$previous", "AppVersion=$Version").Replace("OutputBaseFilename=StarCanvas-Offline-Setup-$previous", "OutputBaseFilename=StarCanvas-Offline-Setup-$Version")
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'installer.iss'), $installer, [Text.UTF8Encoding]::new($false))
$guide = (Get-Content -LiteralPath '安装说明.txt' -Raw).Replace("StarCanvas-Offline-Setup-$previous", "StarCanvas-Offline-Setup-$Version")
[IO.File]::WriteAllText((Join-Path $PSScriptRoot '安装说明.txt'), $guide, [Text.UTF8Encoding]::new($false))
$readme = (Get-Content -LiteralPath 'README.md' -Raw).Replace("**$previous**", "**$Version**")
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'README.md'), $readme, [Text.UTF8Encoding]::new($false))
& $config.Python -m PyInstaller --noconfirm --clean '生图app.spec'
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed' }
& $config.ISCC "/DComfyRoot=$($config.ComfyRoot)" "/DPythonRoot=$($config.PythonRoot)" "/DPayloadRoot=$($config.PayloadRoot)" 'installer.iss'
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
Copy-Item -LiteralPath '安装说明.txt' -Destination 'D:\生图app\离线安装包\安装说明.txt' -Force
& $config.Python publish.py
if ($LASTEXITCODE -ne 0) { throw 'GitHub sync failed. After fixing the connection, retry: python publish.py' }
