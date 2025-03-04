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

def get_primary_ipv6():
    # Get the default route interface
    route_info = Popen(['ip', '-6', 'route', 'show', 'default'], stdout=PIPE, stderr=PIPE)
    stdout, _ = route_info.communicate()
    route_output = stdout.decode().split()

    # Ensure there is enough data to extract the interface
    if len(route_output) < 5:
        return None

    default_interface = route_output[4]

    # Get IPv6 addresses for the default interface
    addr_info = Popen(['ip', '-6', 'addr', 'show', 'dev', default_interface], stdout=PIPE, stderr=PIPE)
    stdout, _ = addr_info.communicate()
    addr_lines = stdout.decode().split('\n')

    # Filter out the primary IPv6 address
    for line in addr_lines:
        if 'inet6' in line and 'global' in line:
            return line.split()[1].split('/')[0]
    return None

def args_create(argv):
    """
    Build the new list of command line arguments for command
        docker create
    """
    dargs = []

    if any('lhcb' in arg for arg in sys.argv):
        dargs.append('--ulimit=nofile=1048575:1048575')
    else:
        dargs.append('--ulimit=nofile=2097152:2097152')

    if gateway():
        dargs.append('--label=xrootd-local-gateway=true')
        dargs.append('--network=ralworker')
        dargs.append('--add-host=xrootd.echo.stfc.ac.uk ceph-gw10.gridpp.rl.ac.uk ceph-gw11.gridpp.rl.ac.uk:172.28.1.1')
        dargs.append('--add-host=xrootd-gateway.echo.stfc.ac.uk:172.28.1.2')
        # Call function to capture primary IPv6 address and assign xrootd alias to local containers IPv6 address.
        primary_ipv6 = get_primary_ipv6()
        if primary_ipv6:
            primary_ipv6 = primary_ipv6.rstrip(':')
            dargs.append('--add-host=xrootd.echo.stfc.ac.uk ceph-gw10.gridpp.rl.ac.uk ceph-gw11.gridpp.rl.ac.uk:{}{}'.format(primary_ipv6, ':1000:2'))
            dargs.append('--add-host=xrootd-gateway.echo.stfc.ac.uk:{}{}'.format(primary_ipv6, ':1000:3'))
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
