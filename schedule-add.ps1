$taskName   = "kk-GuelphBikeLayer"
$projectDir = $PSScriptRoot
$logFile    = "$projectDir\logs\scheduler.log"

if (-not (Test-Path "$projectDir\logs")) {
    New-Item -ItemType Directory -Path "$projectDir\logs" | Out-Null
}

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"`"$projectDir\run-scheduled.cmd`" >> `"$logFile`" 2>&1`""

# Weekly, because this is the fastest-changing layer the City publishes (52
# rows added between the audit and 2026-10-09, 61 dated 2026) but its service
# carries no edit date to poll; the gap page diffs against live OSM each run.
# The 16:30 band is full (one sibling a day, Monday to Sunday), and the 19:30
# band has guelph-water on Monday, guelph-gardens on Tuesday and
# toronto-poster-columns on Wednesday (registered 2026-10-24, the day this
# layer was built for that slot), so this takes Thursday 19:30 -- three hours
# clear of Thursday's 16:30 bus-stops run, so no two of them drive tippecanoe
# in the same WSL instance at once.
$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Thursday -At "19:30"
# Retries live in run-scheduled.cmd, not here: 'update' exits 75 when it sees no
# usable link, and 70 when no Overpass mirror answered and the gap page fell back
# to cached OSM (published first). The wrapper tries either again up to twice, half
# an hour apart, and the 3-hour limit leaves room for that. RestartCount covers only
# a launch that fails; Task Scheduler never re-runs on an exit code.
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 3) -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force

Write-Host "Scheduled '$taskName' to run weekly on Thursday at 19:30."
Write-Host "Log: $logFile"
