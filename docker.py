#!/usr/bin/python
import os
import re
import sys
from subprocess import Popen, PIPE
from socket import getfqdn

singularity = True
if any('grid-workernode-c7' in arg for arg in sys.argv):
    singularity = True

gateway = False
if any('atl' in arg for arg in sys.argv) or any('cms' in arg for arg in sys.argv) or any('lhcb' in arg for arg in sys.argv):
    gateway = True

count = 0
dargs = ['/usr/bin/sudo', '/usr/bin/docker']

if os.environ.get('DOCKER_WRAPPER_DEBUG'):
    dargs = ['/bin/echo'] + dargs

for arg in sys.argv:
    if count > 0:
        m = re.search(r'--memory=([\d]+)m', arg)
        if m:
            memory = int(m.group(1))
            dargs.append('--memory=%dm' % (memory*2))
            dargs.append('--memory-reservation=%dm' % memory)

        elif arg in ('create', 'run'):
            if not os.path.isfile('/etc/nogateway') and gateway:
                dargs.append('--network=ralworker')
                dargs.append('--add-host=xrootd.echo.stfc.ac.uk ceph-gw10.gridpp.rl.ac.uk ceph-gw11.gridpp.rl.ac.uk:172.28.1.1')
                dargs.append('--label=xrootd-local-gateway=true')
                dargs.append('--env=XrdSecGSISRVNAMES=%s' % getfqdn())
                dargs.append('--env=SINGULARITYENV_XrdSecGSISRVNAMES=%s' % getfqdn())
                dargs.append('--env=PANDA_HOSTNAME=%s' % getfqdn())
            else:
                dargs.append('--label=xrootd-local-gateway=false')

            # Allow singularity to work inside of Docker containers
            if singularity:
                dargs.append('-eSINGULARITY_BINDPATH=/etc/hosts')
                dargs.append('--cap-add=SYS_ADMIN')
                dargs.append('--cap-add=DAC_OVERRIDE')
                dargs.append('--cap-add=SETUID')
                dargs.append('--cap-add=SETGID')
                dargs.append('--cap-add=SYS_CHROOT')
                dargs.append('--env=SINGULARITYENV_PANDA_HOSTNAME=%s' % getfqdn())

                # ATLAS fix for 21.0.XX release errors with frontier
                dargs.append('--env=SINGULARITYENV_FRONTIER_LOG_FILE=frontier.log')

                # Set security options to allow unprivileged singularity to run
                # The options are secure as long as the system administrator controls the images and does not allow user
                # code to run as root, and are generally more secure than adding capabilities.
                #
                # Enable unshare to be called (which is needed to create namespaces)
                #dargs.append('--security-opt seccomp=unconfined')
                # Allow /proc to be mounted in an unprivileged process namespace (as done by singularity exec -p)
                #dargs.append('--security-opt systempaths=unconfined')
                # Prevent any privilege escalation (prevents setuid programs from running)
                #dargs.append('--security-opt no-new-privileges')
        else:
            dargs.append(arg)
    count += 1


if '/' in dargs[-1] and not dargs[-1].startswith('-'):
    command = dargs.pop()
    dargs = dargs + ['nice', '-n 10', command]

p = Popen(dargs, stdout=PIPE, stderr=PIPE)
output, err = p.communicate()
for l in output:
    sys.stdout.write(l)
for l in err:
    sys.stderr.write(l)
exit(p.returncode)
