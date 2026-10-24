$taskName   = "kk-GuelphBikeLayer"
$projectDir = $PSScriptRoot
$logFile    = "$projectDir\logs\scheduler.log"

if (-not (Test-Path "$projectDir\logs")) {
    New-Item -ItemType Directory -Path "$projectDir\logs" | Out-Null
}

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c cd /d `"$projectDir`" && python run.py update >> `"$logFile`" 2>&1"

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
# Restart on failure. 'update' exits 75 as soon as it sees no usable link
# instead of blocking on one (the ExecutionTimeLimit would kill a long wait
# anyway), so three tries half an hour apart turn a dead link at 19:30 into a
# run by 21:00 rather than a seven-day gap -- which is what a dead resolver
# cost the Toronto sibling on 2026-07-27. Still clear of the 23:00 quiet window.
#
# It also exits 70 when no Overpass mirror answered and the gap page had to fall
# back to cached OSM. That publishes first, so the retry costs a rebuild and not
# the tiles; without it, two 504s in Aug 2026 left the page a fortnight stale
# with the task reporting success both times.
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force

Write-Host "Scheduled '$taskName' to run weekly on Thursday at 19:30."
Write-Host "Log: $logFile"
