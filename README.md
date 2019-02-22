# ral-htcondor-tools
Scripts and stuff used with HTCondor at RAL

## healhcheck_wn_condor
This script is used by HTCondor to provided a stop/go flag to determine if a worker node should start jobs.

It is set by the HTCondor configuration value `STARTD_CRON_JOBLIST`

The initial version simply returned:
```
NODE_IS_HEALTHY = True
NODE_STATUS = "All_OK"
```
This assumes that the worker node is 'OK'

Later versions return other values which can be used by HTCondor.
Note that the script should be written in modular way. The easy checks should be done first.
