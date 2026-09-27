# Called by upload-latest-msi.bat with the selected file, repository, and tag.
$ErrorActionPreference = 'Stop'
$responsePath = $null
$notesPath = $null

try {
    $file = Get-Item -LiteralPath $env:LATEST_MSI
    $version = (Get-Content -LiteralPath (Join-Path $PSScriptRoot '.version') -Raw).Trim()
    if ($version -notmatch '^\d+\.\d+\.\d+$' -or
        $env:RELEASE_TAG -cne "ankigpt-v$version" -or
        $file.Name -cne "anki-$version-win-x64.msi") {
        throw 'Installer filename, release tag, and .version must match.'
    }
    & gh release view $env:RELEASE_TAG --repo $env:GITHUB_REPOSITORY --json tagName 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $commit = & git -C $PSScriptRoot rev-parse HEAD
        if ($LASTEXITCODE -ne 0) { throw 'Could not determine the source commit.' }
        & gh api "repos/$env:GITHUB_REPOSITORY/commits/$commit" --silent
        if ($LASTEXITCODE -ne 0) { throw 'Push the source commit before creating its release.' }
        $changelog = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'CHANGELOG.md') -Raw
        $section = [regex]::Match($changelog, '(?ms)^## ' + [regex]::Escape($version) + '\r?\n(.*?)(?=^## |\z)')
        if (-not $section.Success) { throw 'No changelog section matches the installer version.' }
        $notesPath = [IO.Path]::GetTempFileName()
        $notes = "## $version`n`n" + $section.Groups[1].Value.Trim() + "`n`nWindows installer: $($file.Name)`n`nSource commit: $commit`n"
        [IO.File]::WriteAllText($notesPath, $notes)
        & gh release create $env:RELEASE_TAG --repo $env:GITHUB_REPOSITORY --target $commit --title "AnkiGPT $version" --notes-file $notesPath
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the version-specific release.' }
    }
    $tag = [Uri]::EscapeDataString($env:RELEASE_TAG)
    $releaseJson = & gh api --hostname github.com "repos/$env:GITHUB_REPOSITORY/releases/tags/$tag"
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the GitHub release.' }
    $release = ($releaseJson -join "`n") | ConvertFrom-Json
    $uploadBase = ($release.upload_url -split '\{')[0]
    $uploadUri = [Uri]$uploadBase
    if ($uploadUri.Scheme -ne 'https' -or $uploadUri.Host -ne 'uploads.github.com') {
        throw 'GitHub returned an unexpected upload URL.'
    }
    $uploadUrl = $uploadBase + '?name=' + [Uri]::EscapeDataString($file.Name)

    $token = $env:GH_TOKEN
    if (-not $token) { $token = $env:GITHUB_TOKEN }
    if (-not $token) {
        $token = & gh auth token --hostname github.com
        if ($LASTEXITCODE -ne 0) { throw 'Could not obtain the GitHub authentication token.' }
    }
    if (-not $token) { throw 'The GitHub authentication token is empty.' }

    # Match the previous --clobber behavior, deleting only the same-named asset.
    foreach ($asset in $release.assets) {
        if ($asset.name -ceq $file.Name) {
            Write-Host "Replacing existing asset: $($file.Name)"
            & gh api --hostname github.com --method DELETE "repos/$env:GITHUB_REPOSITORY/releases/assets/$($asset.id)"
            if ($LASTEXITCODE -ne 0) { throw 'Could not remove the existing release asset.' }
        }
    }

    $responsePath = [IO.Path]::GetTempFileName()
    Write-Host 'Uploading with curl (% Xferd = upload percentage; speed is bytes/second)...'
    Write-Host 'At 35 Mbps, the ideal upload rate is about 4,375,000 bytes/second.'
    $timer = [Diagnostics.Stopwatch]::StartNew()
    # Pass authentication over stdin, keeping the token out of command arguments
    # and temporary files. Stream the MSI with a known length for upload progress.
    $transferStats = '\nTransfer diagnostics: HTTP %{http_code}; remote %{remote_ip}\nUploaded: %{size_upload} bytes; average upload: %{speed_upload} bytes/sec\nTimings from start: DNS %{time_namelookup}s; TCP connected %{time_connect}s; TLS ready %{time_appconnect}s; total %{time_total}s\n'
    "Authorization: Bearer $token" | & curl.exe --disable --show-error --fail-with-body `
        --request POST --upload-file $file.FullName --url $uploadUrl `
        --header '@-' --header 'Accept: application/vnd.github+json' `
        --header 'Content-Type: application/octet-stream' --output $responsePath --write-out $transferStats
    $curlExit = $LASTEXITCODE
    if ($curlExit -ne 0) {
        $details = Get-Content -LiteralPath $responsePath -Raw
        throw "Upload failed (curl exit code $curlExit). $details"
    }
    $uploaded = Get-Content -LiteralPath $responsePath -Raw | ConvertFrom-Json
    if ($uploaded.state -ne 'uploaded' -or $uploaded.size -ne $file.Length) {
        throw 'GitHub did not confirm a complete upload of the expected size.'
    }
    Write-Host ('GitHub confirmed {0:n0} bytes uploaded in {1:n1} seconds.' -f $file.Length, $timer.Elapsed.TotalSeconds)
} catch {
    [Console]::Error.WriteLine("Error: $($_.Exception.Message)")
    exit 1
} finally {
    $token = $null
    if ($responsePath) { Remove-Item -LiteralPath $responsePath -Force -ErrorAction SilentlyContinue }
    if ($notesPath) { Remove-Item -LiteralPath $notesPath -Force -ErrorAction SilentlyContinue }
}
