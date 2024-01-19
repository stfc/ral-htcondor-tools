#!/usr/bin/env python3

import os
import re
import sys
from subprocess import Popen, PIPE
from socket import getfqdn

def gateway():
    gateway_needed = False
    for prefix in ['atl', 'cms', 'lhcb']:
        gateway_needed = gateway_needed or any(prefix in arg for arg in sys.argv)
    return gateway_needed and not os.path.isfile('/etc/nogateway')

def args_create(argv):
    """
    Build the new list of command line arguments for command
        docker create
    """
    dargs = []

    # Allow apptainer to bind local hosts file
    dargs.append('--env=APPTAINER_BINDPATH=/etc/hosts')
    # Singularity equivalent for backwards compatibility
    dargs.append('--env=SINGULARITY_BINDPATH=/etc/hosts')

    # ATLAS fix for 21.0.XX release errors with frontier
    dargs.append('--env=APPTAINERENV_FRONTIER_LOG_FILE=frontier.log')
    # Singularity equivalent for backwards compatibility
    dargs.append('--env=SINGULARITYENV_FRONTIER_LOG_FILE=frontier.log')

    # Define a parent hostname variable
    dargs.append('--env=PARENT_HOSTNAME=%s' % getfqdn())

    # PANDA enviroment variables for ATLAS
    dargs.append('--env=PANDA_HOSTNAME=%s' % getfqdn())
    dargs.append('--env=APPTAINERENV_PANDA_HOSTNAME=%s' % getfqdn())
    # Singularity equivalent for backwards compatibility
    dargs.append('--env=SINGULARITYENV_PANDA_HOSTNAME=%s' % getfqdn())

    # Prevent ATLAS pilot from attempting to kill orphaned processes
    # at the end of each job.
    # It may trigger a SIGKILL signal to the pilot.
    dargs.append('--env=PILOT_NOKILL=1')

    # Set security options to allow unprivileged apptainer to run
    # The options are secure as long as the system administrator controls the images and does not allow user
    # code to run as root, and are generally more secure than adding capabilities.
    #
    # Enable unshare to be called (which is needed to create namespaces)
    dargs.append('--security-opt=seccomp=unconfined')
    # Allow /proc to be mounted in an unprivileged process namespace (as done by apptainer exec -p)
    dargs.append('--security-opt=systempaths=unconfined')
    # Prevent any privilege escalation (prevents setuid programs from running)
    dargs.append('--security-opt=no-new-privileges')
    # In addition, the following option is recommended for allowing unprivileged fuse mounts on kernels that support that.
    dargs.append('--device=/dev/fuse')

    if gateway():
        dargs.append('--label=xrootd-local-gateway=true')
        dargs.append('--network=ralworker')
        dargs.append('--add-host=xrootd.echo.stfc.ac.uk ceph-gw10.gridpp.rl.ac.uk ceph-gw11.gridpp.rl.ac.uk:172.28.1.1')
        dargs.append('--env=XrdSecGSISRVNAMES=%s' % getfqdn())
        dargs.append('--env=APPTAINERENV_XrdSecGSISRVNAMES=%s' % getfqdn())
        # Singularity equivalent for backwards compatibility
        dargs.append('--env=SINGULARITYENV_XrdSecGSISRVNAMES=%s' % getfqdn())
        # ATLAS fix for 21.0.XX release errors with frontier
        dargs.append('--env=FRONTIER_LOG_FILE=frontier.log')
        #Increase timeout to prevent vector read errors
        dargs.append('--env=XRD_STREAMTIMEOUT=300')
        dargs.append('--env=APPTAINERENV_XRD_STREAMTIMEOUT=300')
        dargs.append('--env=SINGULARITYENV_XRD_STREAMTIMEOUT=300')
    else:
        dargs.append('--label=xrootd-local-gateway=false')

    # memory setup
    for arg in argv:
        m = re.search(r'--memory=([\d]+)m', arg)
        if m:
            memory = int(m.group(1))
            dargs.append('--memory=%dm' % (memory*3))
            dargs.append('--memory-reservation=%dm' % memory)
        else:
            dargs.append(arg)

    if '/' in dargs[-1] and not dargs[-1].startswith('-'):
        command = dargs.pop()
        dargs = dargs + ['nice', '-n 10', command]

    return dargs

def args_run(argv):
    """
    To ensure backwards compatibility.
    We handle 'docker run' just the same way we do for 'docker create'
    """
    return args_create(argv)

def args_other_commands(argv):
    """
    Just in case we need to do something custom for other commands.
    """
    # for the time being, this is just a pass thru
    return argv

def execute(args):
    p = Popen(args, stdout=PIPE, stderr=PIPE)
    output, err = p.communicate()
    sys.stdout.buffer.write(output)
    sys.stderr.buffer.write(err)
    exit(p.returncode)


# ==============================================================================
#   main
# ==============================================================================

docker_command = sys.argv[1]
dargs = ['/usr/bin/sudo', '/usr/bin/docker', docker_command]

if docker_command == 'create':
    dargs += args_create(sys.argv[2:])
elif docker_command == 'run':
    dargs += args_run(sys.argv[2:])
else:
    dargs += args_other_commands(sys.argv[2:])

if os.environ.get('DOCKER_WRAPPER_DEBUG'):
    dargs = ['/bin/echo'] + dargs

execute(dargs)
