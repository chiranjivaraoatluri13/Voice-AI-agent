# ==========================================================
# extract_app_labels.ps1
# Extracts real app labels from ALL pulled APKs using aapt2
# Outputs app_labels_map.txt to the project folder
# ==========================================================

# Paths — update $ProjDir to your project root
$ProjDir = "C:\Users\chira\OneDrive\Desktop\tablet_voice_agent_v1"
$List    = Join-Path $ProjDir "packages_all.txt"
$Out     = Join-Path $ProjDir "app_labels_map.txt"
$ApkDir  = Join-Path $ProjDir "apks_all"
$Aapt2   = "C:\Users\chira\AppData\Local\Android\Sdk\build-tools\36.1.0\aapt2.exe"

# Verify aapt2 exists
if (-not (Test-Path $Aapt2)) {
    Write-Host "ERROR: aapt2 not found at: $Aapt2" -ForegroundColor Red
    Write-Host "Update the path in this script to your Android SDK build-tools location."
    exit 1
}

# Verify package list exists
if (-not (Test-Path $List)) {
    Write-Host "ERROR: Package list not found: $List" -ForegroundColor Red
    Write-Host "Run pull_all_apks.bat first."
    exit 1
}

Write-Host "============================================"
Write-Host " Extracting app labels using aapt2"
Write-Host "============================================"
Write-Host ""

# Initialize output with header
"Label=Package" | Set-Content -Encoding UTF8 $Out

$total = 0
$extracted = 0
$failed = 0
$noLabel = 0

Get-Content $List | ForEach-Object {
    $line = $_.Trim()
    if ($line.Length -eq 0) { return }

    # Remove "package:" prefix
    $line = $line -replace '^(?i)package:', ''
    $i = $line.LastIndexOf('=')
    if ($i -lt 1) { return }

    $apk = $line.Substring(0, $i).Trim()
    $pkg = $line.Substring($i + 1).Trim()
    $total++

    $localApk = Join-Path $ApkDir ($pkg + ".apk")

    # Pull APK if not already local
    if (-not (Test-Path $localApk)) {
        Write-Host "  Pulling: $pkg"
        & adb pull "$apk" "$localApk" 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  FAILED to pull: $pkg" -ForegroundColor Yellow
            "pull_failed=$pkg" | Add-Content -Encoding UTF8 $Out
            $failed++
            return
        }
    }

    # Extract label using aapt2
    $badging = & $Aapt2 dump badging "$localApk" 2>$null
    $labelLine = $badging | Where-Object { $_ -match '^application-label:' } | Select-Object -First 1

    if ($labelLine) {
        $label = $labelLine -replace '^application-label:', ''
        $label = $label.Trim("'").Trim('"').Trim()
        
        if ($label.Length -gt 0) {
            "$label=$pkg" | Add-Content -Encoding UTF8 $Out
            $extracted++
        } else {
            "no_label=$pkg" | Add-Content -Encoding UTF8 $Out
            $noLabel++
        }
    } else {
        "no_label=$pkg" | Add-Content -Encoding UTF8 $Out
        $noLabel++
    }
}

Write-Host ""
Write-Host "============================================"
Write-Host " Done!"
Write-Host " Total packages: $total"
Write-Host " Labels extracted: $extracted"
Write-Host " No label found: $noLabel"
Write-Host " Pull failed: $failed"
Write-Host " Output: $Out"
Write-Host "============================================"
Write-Host ""
Write-Host "Now restart the agent or run 'reindex apps' to pick up new labels."
