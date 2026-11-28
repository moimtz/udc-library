# Prepares the Flutter project (platform folders + this app's code).
# Run from the biblioteca_udc folder:
#     powershell -ExecutionPolicy Bypass -File .\setup_app.ps1
$ErrorActionPreference = "Stop"
$root  = $PSScriptRoot
$build = Join-Path $root "app_build"

if (-not (Test-Path $build)) {
    flutter create --project-name biblioteca_udc --org local.bibliotecaudc --platforms=windows,android $build
}

# Copy this project's code over the generated template
Copy-Item (Join-Path $root "app\pubspec.yaml") $build -Force
$lib = Join-Path $build "lib"
if (Test-Path $lib) { Remove-Item $lib -Recurse -Force }
Copy-Item (Join-Path $root "app\lib") $lib -Recurse -Force
$tests = Join-Path $build "test"
if (Test-Path $tests) { Remove-Item $tests -Recurse -Force }
# widget tests (flutter test): screens drawn at laptop and phone sizes, English and Spanish
if (Test-Path (Join-Path $root "app\test")) { Copy-Item (Join-Path $root "app\test") $tests -Recurse -Force }

# Android: internet permission, plain-HTTP over Tailscale, app name
$manifest = Join-Path $build "android\app\src\main\AndroidManifest.xml"
if (Test-Path $manifest) {
    $xml = Get-Content $manifest -Raw
    if ($xml -notmatch "android.permission.INTERNET") {
        $xml = $xml -replace "<application", ("<uses-permission android:name=`"android.permission.INTERNET`"/>`n    <application")
    }
    if ($xml -notmatch "usesCleartextTraffic") {
        $xml = $xml -replace "<application", "<application android:usesCleartextTraffic=`"true`""
    }
    $xml = $xml -replace 'android:label="[^"]*"', 'android:label="Biblioteca UDC"'
    Set-Content $manifest $xml -Encoding UTF8
}

# Windows: window title
$main = Join-Path $build "windows\runner\main.cpp"
if (Test-Path $main) {
    $cpp = Get-Content $main -Raw
    $cpp = $cpp -replace 'L"biblioteca_udc"', 'L"Biblioteca UDC"'
    Set-Content $main $cpp -Encoding UTF8
}

Push-Location $build
flutter pub get
Pop-Location

Write-Host ""
Write-Host "Ready. Next steps (inside the app_build folder):"
Write-Host "  flutter run -d windows                      test on this PC"
Write-Host "  flutter build windows --release             portable Windows app"
Write-Host "  flutter build apk --release --split-per-abi Android APK"
