$ErrorActionPreference = "Stop"
Write-Output "WSL status:"
wsl.exe --status
Write-Output ""
Write-Output "Distributions:"
wsl.exe -l -v
Write-Output ""
Write-Output "Docker daemon:"
docker version --format "{{.Server.Version}}"
if ($LASTEXITCODE -ne 0) {
    Write-Output "Docker daemon is not running."
}
Write-Output ""
Write-Output "kubectl client:"
kubectl version --client
Write-Output ""
kubectl cluster-info
if ($LASTEXITCODE -ne 0) {
    Write-Output "No Kubernetes API is reachable."
}
exit 0
