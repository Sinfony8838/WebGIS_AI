param(
    [string]$ApiBase = "http://127.0.0.1:18999",
    [string]$DataRoot,
    [string]$ProjectId = "",
    [string]$Topic = "classroom_dataset",
    [string]$Region = "",
    [string]$GradeLevel = "general",
    [switch]$Recurse
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http

function Write-Step {
    param([string]$Message)
    Write-Host "[KB-Ingest] $Message" -ForegroundColor Cyan
}

function Ensure-DataRoot {
    param([string]$Path)
    if (-not $Path) {
        throw "Please provide -DataRoot"
    }
    if (-not (Test-Path $Path)) {
        throw "Data root does not exist: $Path"
    }
}

function Ensure-Project {
    param(
        [string]$ApiBase,
        [string]$ProjectId
    )
    if ($ProjectId) {
        return $ProjectId
    }

    Write-Step "No project id provided. Creating a new project."
    $payload = @{
        name = "Knowledge Ingest Project"
        metadata = @{
            mode = "kb_ingest"
        }
    } | ConvertTo-Json -Depth 6
    $created = Invoke-RestMethod -Method Post -Uri "$ApiBase/projects" -ContentType "application/json" -Body $payload
    return [string]$created.project_id
}

function Upload-Dataset {
    param(
        [System.Net.Http.HttpClient]$Client,
        [string]$ApiBase,
        [string]$ProjectId,
        [System.IO.FileInfo]$File
    )

    $multipart = [System.Net.Http.MultipartFormDataContent]::new()
    $multipart.Add([System.Net.Http.StringContent]::new($ProjectId), "project_id")
    $multipart.Add([System.Net.Http.StringContent]::new($File.BaseName), "dataset_name")

    $stream = [System.IO.File]::OpenRead($File.FullName)
    try {
        $fileContent = [System.Net.Http.StreamContent]::new($stream)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::new("application/octet-stream")
        $multipart.Add($fileContent, "file", $File.Name)

        $response = $Client.PostAsync("$ApiBase/datasets/upload", $multipart).GetAwaiter().GetResult()
        $responseBody = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "Upload failed ($($response.StatusCode)): $responseBody"
        }
        return $responseBody | ConvertFrom-Json
    }
    finally {
        $stream.Dispose()
        $multipart.Dispose()
    }
}

function Register-KbItem {
    param(
        [string]$ApiBase,
        [string]$ProjectId,
        [string]$LayerId,
        [System.IO.FileInfo]$File,
        [string]$Topic,
        [string]$Region,
        [string]$GradeLevel
    )

    $metadata = @{
        topic = $Topic
        region = $Region
        grade_level = $GradeLevel
        source = $File.FullName
        keywords = @($Topic, $Region, $File.BaseName) | Where-Object { $_ -and $_.Trim() }
        summary = "Dataset layer '$($File.BaseName)' imported in batch for classroom explanation and thematic analysis."
    }
    $payload = @{
        project_id = $ProjectId
        layer_id = $LayerId
        metadata = $metadata
    } | ConvertTo-Json -Depth 8

    return Invoke-RestMethod -Method Post -Uri "$ApiBase/kb/layers/register" -ContentType "application/json" -Body $payload
}

Ensure-DataRoot -Path $DataRoot

$resolvedRoot = (Resolve-Path $DataRoot).Path
$supported = @(".geojson", ".json", ".csv", ".zip", ".png", ".jpg", ".jpeg")
$searchOption = if ($Recurse) { [System.IO.SearchOption]::AllDirectories } else { [System.IO.SearchOption]::TopDirectoryOnly }
$files = [System.IO.Directory]::GetFiles($resolvedRoot, "*", $searchOption) |
    ForEach-Object { Get-Item $_ } |
    Where-Object { $supported -contains $_.Extension.ToLowerInvariant() } |
    Sort-Object FullName

if (-not $files.Count) {
    throw "No supported files found in $resolvedRoot"
}

$ProjectId = Ensure-Project -ApiBase $ApiBase -ProjectId $ProjectId
Write-Step "Using project: $ProjectId"
Write-Step "Found files: $($files.Count)"

$client = [System.Net.Http.HttpClient]::new()
$client.Timeout = [TimeSpan]::FromMinutes(5)

$success = 0
$failed = 0
$registered = 0
$errors = @()

foreach ($file in $files) {
    try {
        Write-Step "Uploading: $($file.FullName)"
        $uploadResult = Upload-Dataset -Client $client -ApiBase $ApiBase -ProjectId $ProjectId -File $file
        $layerId = [string]$uploadResult.layer.layer_id
        if (-not $layerId) {
            throw "Upload succeeded but layer_id is missing"
        }
        $success += 1

        Write-Step "Registering KB item for layer: $layerId"
        $null = Register-KbItem -ApiBase $ApiBase -ProjectId $ProjectId -LayerId $layerId -File $file -Topic $Topic -Region $Region -GradeLevel $GradeLevel
        $registered += 1
    }
    catch {
        $failed += 1
        $message = "$($file.FullName) :: $($_.Exception.Message)"
        $errors += $message
        Write-Host "[KB-Ingest][ERROR] $message" -ForegroundColor Red
    }
}

$client.Dispose()

Write-Host ""
Write-Host "Ingest completed." -ForegroundColor Green
Write-Host "Project ID : $ProjectId"
Write-Host "Uploaded   : $success"
Write-Host "Registered : $registered"
Write-Host "Failed     : $failed"

if ($errors.Count -gt 0) {
    Write-Host ""
    Write-Host "Errors:" -ForegroundColor Yellow
    $errors | ForEach-Object { Write-Host " - $_" -ForegroundColor Yellow }
}
