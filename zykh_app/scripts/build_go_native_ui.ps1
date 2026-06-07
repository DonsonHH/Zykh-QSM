$ErrorActionPreference = 'Stop'

$AppDir = Resolve-Path (Join-Path $PSScriptRoot '..')
$RepoDir = Resolve-Path (Join-Path $AppDir '..')
$SourceDir = Join-Path $AppDir 'native\go-ui'
$VoiceDir = Join-Path $AppDir 'tools\ai-voice'
$BinDir = Join-Path $AppDir 'bin'
$Out = Join-Path $BinDir 'zykh-go-ui'
$VoiceOut = Join-Path $BinDir 'zykh-ai-voice'
$LocalGoBin = Join-Path $RepoDir '.tools\go-win\go\bin'

if (Test-Path (Join-Path $LocalGoBin 'go.exe')) {
  $env:PATH = $LocalGoBin + ';' + $env:PATH
}

if (-not (Get-Command go -ErrorAction SilentlyContinue)) {
  throw 'Go was not found. Install Go or extract it to .tools\go-win\go first.'
}

New-Item -ItemType Directory -Force $BinDir | Out-Null
$env:GOCACHE = Join-Path $RepoDir '.tools\gocache'
$env:GOPATH = Join-Path $RepoDir '.tools\gopath'
New-Item -ItemType Directory -Force $env:GOCACHE, $env:GOPATH | Out-Null

Push-Location $SourceDir
try {
  go mod tidy
  gofmt -w main.go
  $env:GOOS = 'linux'
  $env:GOARCH = 'arm64'
  $env:CGO_ENABLED = '0'
  go build -trimpath -ldflags='-s -w' -o $Out .
}
finally {
  Pop-Location
}

Write-Host ('Go native UI built: ' + $Out)

Push-Location $VoiceDir
try {
  go mod tidy
  gofmt -w main.go
  $env:GOOS = 'linux'
  $env:GOARCH = 'arm64'
  $env:CGO_ENABLED = '0'
  go build -trimpath -ldflags='-s -w' -o $VoiceOut .
}
finally {
  Pop-Location
}

Write-Host ('Go AI voice helper built: ' + $VoiceOut)
