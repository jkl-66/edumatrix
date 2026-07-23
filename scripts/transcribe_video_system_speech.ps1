param(
    [Parameter(Mandatory = $true)]
    [string]$AudioPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputJson,

    [Parameter(Mandatory = $true)]
    [string]$OutputMarkdown,

    [string]$Culture = "zh-CN"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech

$audio = (Resolve-Path -LiteralPath $AudioPath).Path
$recognizerInfo = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() |
    Where-Object { $_.Culture.Name -eq $Culture } |
    Select-Object -First 1

if (-not $recognizerInfo) {
    throw "No installed System.Speech recognizer for culture $Culture"
}

$cultureInfo = [System.Globalization.CultureInfo]::GetCultureInfo($Culture)
$recognizer = [System.Speech.Recognition.SpeechRecognitionEngine]::new($cultureInfo)
$recognizer.LoadGrammar([System.Speech.Recognition.DictationGrammar]::new())
$recognizer.SetInputToWaveFile($audio)

$segments = [System.Collections.Generic.List[object]]::new()
while ($true) {
    $result = $recognizer.Recognize()
    if ($null -eq $result) {
        break
    }

    $segments.Add([PSCustomObject]@{
        start_seconds = [Math]::Round($result.Audio.AudioPosition.TotalSeconds, 3)
        duration_seconds = [Math]::Round($result.Audio.Duration.TotalSeconds, 3)
        confidence = [Math]::Round($result.Confidence, 4)
        text = $result.Text
    })
}
$recognizer.Dispose()

$jsonDir = Split-Path -Parent $OutputJson
$markdownDir = Split-Path -Parent $OutputMarkdown
New-Item -ItemType Directory -Force -Path $jsonDir | Out-Null
New-Item -ItemType Directory -Force -Path $markdownDir | Out-Null

$payload = [PSCustomObject]@{
    source_audio = $audio
    recognizer = $recognizerInfo.Name
    culture = $Culture
    generated_at = (Get-Date).ToString("s")
    segment_count = $segments.Count
    segments = $segments
}
$payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutputJson -Encoding UTF8

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("# Offline Video Transcript")
$lines.Add("")
$lines.Add("- Audio: ``$audio``")
$lines.Add("- Recognizer: ``$($recognizerInfo.Name)``")
$lines.Add("- Culture: ``$Culture``")
$lines.Add("- Segments: ``$($segments.Count)``")
$lines.Add("- Warning: System.Speech is an offline recognizer. Verify names and continuous speech against video frames.")
$lines.Add("")

foreach ($segment in $segments) {
    $start = [TimeSpan]::FromSeconds($segment.start_seconds).ToString("hh\:mm\:ss\.fff")
    $end = [TimeSpan]::FromSeconds($segment.start_seconds + $segment.duration_seconds).ToString("hh\:mm\:ss\.fff")
    $lines.Add("- **$start - $end** ``confidence=$($segment.confidence)``: $($segment.text)")
}

$lines | Set-Content -LiteralPath $OutputMarkdown -Encoding UTF8
Write-Output ([PSCustomObject]@{
    output_json = (Resolve-Path -LiteralPath $OutputJson).Path
    output_markdown = (Resolve-Path -LiteralPath $OutputMarkdown).Path
    segment_count = $segments.Count
})
