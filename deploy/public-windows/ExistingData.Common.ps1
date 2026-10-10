# Metadata-only guard for restarting an existing installation.
function Assert-PublicWebGISExistingData {
    param([Parameter(Mandatory)][string]$DataRoot)
    foreach ($relative in @('state/runtime.json', 'auth/auth.db')) {
        $path = Join-Path $DataRoot $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Existing installation data missing: $relative. Restore and verify the data root before starting; no services were launched."
        }
        if ((Get-Item -LiteralPath $path -Force -ErrorAction Stop).Length -eq 0) {
            throw "Existing installation data empty: $relative. Restore and verify the data root before starting; no services were launched."
        }
    }
}
