[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')]
    [string]$VolumeName = "memory-palace-secrets",
    [Security.SecureString]$Password
)

$helperImage = "nginx@sha256:516475cc129da42866742567714ddc681e5eed7b9ee0b9e9c015e464b4221a00"
$securePassword = if ($Password) { $Password } else { Read-Host "Scenic seeded-account shared password" -AsSecureString }
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    if ($plainPassword.Length -lt 12 -or $plainPassword.Length -gt 128) {
        throw "Scenic account password must be 12-128 characters"
    }
    docker volume inspect $VolumeName *> $null
    if ($LASTEXITCODE -ne 0) { docker volume create $VolumeName | Out-Null }
    if ($LASTEXITCODE -ne 0) { throw "Unable to create Docker secret volume: $VolumeName" }
    $arguments = @(
        "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--volume", "${VolumeName}:/secrets", $helperImage,
        "sh", "-eu", "-c",
        'temporary_file=`mktemp /secrets/.scenic_account_password.XXXXXX`; trap ''rm -f "$temporary_file"'' 0 1 2 15; cat > "$temporary_file"; chmod 0444 "$temporary_file"; mv -f "$temporary_file" /secrets/scenic_account_password; temporary_file='
    )
    $plainPassword | & docker @arguments
    if ($LASTEXITCODE -ne 0) { throw "Unable to write scenic password to Docker secret volume" }
    Write-Output "Scenic account credential saved in Docker volume '$VolumeName'."
}
finally {
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    $plainPassword = $null
    $securePassword = $null
}
