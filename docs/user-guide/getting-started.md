# Getting started

```bash
python -m pip install -e .
pulse init            # writes pulse.yml with safe defaults
pulse validate-config
pulse inspect
pulse plan            # preview, changes nothing
pulse run --execute   # run the planned tasks
pulse report --latest
```

`pulse run` without `--execute` is a dry run by default. Commits stay off until you turn
them on in the configuration, and that also needs `runtime.mode: standard`.
