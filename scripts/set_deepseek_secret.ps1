[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')]
    [string]$VolumeName = "memory-palace-secrets",

    [Security.SecureString]$ApiKey
)

$helperImage = "nginx@sha256:516475cc129da42866742567714ddc681e5eed7b9ee0b9e9c015e464b4221a00"
$secureKey = if ($ApiKey) { $ApiKey } else { Read-Host "DeepSeek API key" -AsSecureString }
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)

try {
    $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    if ($key -notmatch '^sk-[A-Za-z0-9_-]{20,}$') {
        throw "Invalid DeepSeek API key format"
    }

    docker volume inspect $VolumeName *> $null
    if ($LASTEXITCODE -ne 0) {
        docker volume create $VolumeName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to create Docker secret volume: $VolumeName"
        }
    }

    $dockerArguments = @(
        "run", "--rm", "-i",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--volume", "${VolumeName}:/secrets",
        $helperImage,
        "sh", "-eu", "-c",
        'input_file=`mktemp /secrets/.deepseek_api_key.input.XXXXXX`; temporary_file=`mktemp /secrets/.deepseek_api_key.XXXXXX`; cleanup() { rm -f "$input_file" "$temporary_file"; }; trap cleanup 0 1 2 15; cat > "$input_file"; prefix=`od -An -tx1 -N3 "$input_file" | tr -d "[:space:]"`; if [ "$prefix" = "efbbbf" ]; then tail -c +4 "$input_file" > "$temporary_file"; else cp "$input_file" "$temporary_file"; fi; chmod 0444 "$temporary_file"; mv -f "$temporary_file" /secrets/deepseek_api_key; temporary_file='
    )
    $key | & docker @dockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to write Docker secret volume: $VolumeName"
    }

    $containerIds = @(
        docker ps --filter "volume=$VolumeName" --filter "label=com.docker.compose.service=app" --format "{{.ID}}"
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to find application containers using Docker volume: $VolumeName"
    }
    if ($containerIds.Count -gt 0) {
        docker restart $containerIds | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Secret saved, but application containers could not be restarted"
        }
    }

    Write-Output "DeepSeek secret saved in Docker volume '$VolumeName'; restarted $($containerIds.Count) application container(s)."
}
finally {
    if ($pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    $key = $null
    $secureKey = $null
}
