param(
    [Parameter(Mandatory = $true)][string]$Text,
    [Parameter(Mandatory = $true)][string]$OutputWav,
    [string]$Culture = "zh-CN"
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$destination = [System.IO.Path]::GetFullPath($OutputWav)
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($destination)) | Out-Null
$synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $voice = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq $Culture } | Select-Object -First 1
    if (-not $voice) { throw "No installed System.Speech voice for culture $Culture" }
    $synth.SelectVoice($voice.VoiceInfo.Name)
    $synth.Rate = 0
    $synth.Volume = 100
    $synth.SetOutputToWaveFile($destination)
    $synth.Speak($Text)
    $synth.SetOutputToNull()
    Write-Output ($voice.VoiceInfo.Name)
}
finally {
    $synth.Dispose()
}
