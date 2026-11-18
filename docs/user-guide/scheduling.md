# Scheduling

Pulse has no background process. Your scheduler calls `pulse run --scheduled --execute`.
Run `pulse schedule --for cron --at 18:00` to print a ready made snippet for cron, systemd,
GitHub Actions or Windows Task Scheduler.

With `--scheduled`, Pulse skips days that are not in `schedule.weekdays` and skips a second
run on the same day. It never makes up for missed runs. A scheduled invocation is not a
completed maintenance action by itself; read the report to see what really happened.
