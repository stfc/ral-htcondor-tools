#!/usr/bin/python2

"""This module introduces the functions necassary to
have preemptable jobs on the batch farm.
When run from a CLI the script will:
Identify demand for draining machines
Kill preemptable jobs if a 8 core job can fit in their place
Add / Remove jobs from the PREEMPTABLE_ONLY state."""

import htcondor
import datetime
import subprocess
import socket
from operator import attrgetter
import sys
import time
import os
import logging
import fcntl

JOB_THRESHOLDS = {
    'idle' : 20,
    'running' : 300,
}

CONCURRECY = {
    'low' : 20,
    'high' : 60,
    'default' : 2,
}

#full paths to these commands needed.
CONDOR_RECONFIG='/usr/sbin/condor_reconfig'
CONDOR_CONFIG_VAL='/usr/bin/condor_config_val'

FILENAME_INHIBIT_DRAINING = '/etc/nodrain'
FILENAME_MULTI_RUN_LOCK = '/var/run/efficientDrainingRunning'

class Machine(object):
    """ Represents a single compute node """
    name = None
    rank = -10.0
    preemptable_jobs = []
    num_free = 0
    num_preemptable = 0
    total_cpus = 0
    total_killable_cpus = 0

    def __init__(self, name):
        self.name = name


class Job(object):
    """ Represents a single job """
    job_id = None
    global_id = None
    schedd = None
    start_time = None

    def __init__(self, job_id, global_id, start_time, schedd):
        self.job_id = job_id
        self.global_id = global_id
        self.start_time = start_time
        self.schedd = schedd

def persistent_set(hostname, daemon, atr, val):
    """ Calls /usr/bin/condor_config_val to set a configuration variable persistently """
    logger = logging.getLogger('condor_efficient_defrag')
    set_string = '%s -name %s %s -set "%s = %s" && %s -name %s' % (CONDOR_CONFIG_VAL, hostname, daemon, atr, val, CONDOR_RECONFIG, hostname)
    subprocess.Popen(set_string, shell=True, stdout=subprocess.PIPE).communicate()
    logger.debug('Set %s, %s, %s = %s persistently', hostname, daemon, atr, val)


def ping(hostname):
    """ Returns true if (and only if) hostname is ping-able, else returns False"""
    exit_code = subprocess.call(["/bin/ping", "-c", "1", hostname], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if exit_code == 0:
        return True
    return False


def get_collector(hostname=socket.gethostname()):
    """ Gets the condor_colecttor of the machine passed (by default local host)"""
    logger = logging.getLogger('condor_efficient_defrag')
    condor_collector = htcondor.Collector(hostname)
    try:
        # Test the connection with a simple query
        condor_collector.locateAll(htcondor.DaemonTypes.Collector)
    except IOError:
        logger.error("Failed to connect to collector %s, exiting.", socket.gethostname())
        sys.exit()
    return condor_collector


def get_schedd_hosts(condor_collector):
    """ Returns a list of the hosts with a condor_schedd on them"""
    logger = logging.getLogger('condor_efficient_defrag')
    hosts = condor_collector.query(htcondor.AdTypes.Schedd, "true", ["Name"])
    if not hosts: #ie no schedds
        logger.error("No schedds found, exiting!")
        sys.exit()
    return [h['Name'] for h in hosts]

def update_jobs_list(condor_collector, hostname):
    """ Queries the schedds to generate a list of preemptable jobs"""
    logger = logging.getLogger('condor_efficient_defrag')

    condor_schedd = htcondor.Schedd(condor_collector.locate(htcondor.DaemonTypes.Schedd, hostname))

    jobs = []
    pjobs = []

    try:
       jobs = condor_schedd.query('isPreemptable =?= True', ["GlobalJobId"])
    except ValueError:
        logger.error("Caught ValueError - could not connect to schedd on %s, skipping reading jobs in queue.", hostname)
    except IOError:
        logger.error("Caught IOError - could not connect to schedd on %s, skipping reading jobs in queue.", hostname)

    for job in jobs:
       pjobs.append(job["GlobalJobId"])

    return pjobs

def get_schedd_jobs(condor_collector, hostname):
    """ Queries the schedds to determine how many multicore jobs are running and idle"""
    logger = logging.getLogger('condor_efficient_defrag')
    jobs = []

    condor_schedd = htcondor.Schedd(condor_collector.locate(htcondor.DaemonTypes.Schedd, hostname))

    try:
        jobs = condor_schedd.query('RequestCpus>1', ["JobStatus", "RequestCpus"])
    except ValueError:
        logger.error("Caught ValueError - could not connect to schedd on %s, skipping reading jobs in queue.", hostname)
    except IOError:
        logger.error("Caught IOError - could not connect to schedd on %s, skipping reading jobs in queue.", hostname)

    running = idle = 0
    for job in jobs:
        if int(job["JobStatus"]) == 2:
            running += 1
        if int(job["JobStatus"]) == 1:
            idle += 1

    return running, idle


def get_startds(condor_collector, constraint=""):
    """ Gets the startd from all worker nodes in pool"""
    logger = logging.getLogger('condor_efficient_defrag')
    try:
        results = condor_collector.query(htcondor.AdTypes.Startd, constraint)
    except IOError:
        logger.error("Error: Failed to read startds, exiting.")
        sys.exit()

    if not results:
        logger.error("No startds found, exiting.")
        sys.exit()

    return results


def calculate_concurrency(job_counts):
    """ Determines how aggresive to be with the draining"""
    if job_counts['idle'] > JOB_THRESHOLDS['idle']:
        if job_counts['running'] > JOB_THRESHOLDS['running']:
            return CONCURRECY['low']
        else:
            return CONCURRECY['high']
    else:
        return CONCURRECY['default']

def kill_jobs(condor_collector, machine, number_to_kill):
    """ Kills number_to_kill many jobs from the preemptable jobs on machine, newest first"""
    logger = logging.getLogger('condor_efficient_defrag')
    for job in machine.preemptable_jobs[0:number_to_kill]:
        #need to send action to right collector
        schedd_ad = condor_collector.locate(htcondor.DaemonTypes.Schedd, job.schedd)
        schedd = htcondor.Schedd(schedd_ad)
        schedd.act(htcondor.JobAction.Remove, 'GlobalJobId=="%s"' % job.global_id)
        logger.debug('Killed %s, started at: %s', job.global_id, job.start_time)

def startd_will_hibernate(condor_startd, machine):
    """ Returns true if machine is about to hibernate"""
    #because we are querying partionable slots, even if the node is full the partionable slot
    #will show as ShouldHibernate, so need to check if the total cpus in the
    #partionable slot == total on machine, if so, no cpus is doing anything and node truly idle.
    if "ShouldHibernate" in condor_startd and condor_startd["ShouldHibernate"] and machine.num_free == machine.total_cpus:
        return True
    return False

def startd_is_fast_draining(condor_startd):
    """ Returns true if condor_startd has KILL_SIGNAL set to true"""
    if "KILL_SIGNAL" in condor_startd and str(condor_startd["KILL_SIGNAL"]) == "True":
        return True
    return False

def startd_is_being_emptied(condor_startd):
    """ Returns true if condor_startd is filling with preemptable jobs before a restart"""
    if "EFFICIENT_DRAIN" in condor_startd and str(condor_startd["EFFICIENT_DRAIN"]) == "True":
        return True
    return False

def get_running_jobs(machine, condor_collector):
    """ Gets the running jobs from machine"""
    logger = logging.getLogger('condor_efficient_defrag')
    jobs = []
    try:
        jobs = condor_collector.query(htcondor.AdTypes.Startd, 'Machine=="%s"' % machine, ["JobId", "ClientMachine", "GlobalJobId", "EnteredCurrentActivity"])
    except IOError:
        logger.error("Collector Error: Failed to get jobs from machine %s.\n", machine.name)
    return jobs

def get_schedd(client, condor_collector):
    """ Gets the schedd deamon runnning on Client"""
    schedd_ad = condor_collector.locate(htcondor.DaemonTypes.Schedd, client)
    return htcondor.Schedd(schedd_ad)

def main():
    """ Main function, called when module is run as a CLI application """
    logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s')
    logger = logging.getLogger('condor_efficient_defrag')
    logger.setLevel(logging.INFO)
    #---------------------------------------------------------------------------------
    #
    # Calculate demand for multicore slots
    #
    #---------------------------------------------------------------------------------

    logger.info("Starting run at: %s", datetime.datetime.now())

    #if not create_lock():
    #    sys.exit(1)

    job_counts = dict()
    job_counts['idle'] = 0
    job_counts['running'] = 0

    condor_collector = get_collector()
    condor_schedd_hosts = get_schedd_hosts(condor_collector)
    condor_stards = get_startds(condor_collector, 'RalCluster =!= "wn-cloud" && ClusterName =!= "wn-test" && RalCluster =!= "vm-nubes" && RalCluster =!= "vm-hyperv"')

    jobs_list = []

    # Get job counts from as many schedds as possible
    for condor_schedd_host in condor_schedd_hosts:
        running, idle = get_schedd_jobs(condor_collector, condor_schedd_host)
        job_counts['running'] += running
        job_counts['idle'] += idle
        jobs_list.extend(update_jobs_list(condor_collector, condor_schedd_host))

    logger.debug('Idle multicore jobs = %(idle)i', job_counts)
    logger.debug('Running multicore jobs = %(running)i', job_counts)

    # Set max concurrent draining machines based on demand
    max_concurrent_draining = calculate_concurrency(job_counts)

    drain = True
    if os.path.isfile(FILENAME_INHIBIT_DRAINING):
        drain = False
        max_concurrent_draining = 0

    logger.debug('Max concurrent draining machines = %i', max_concurrent_draining)

    #---------------------------------------------------------------------------------
    #
    # Calculate rank for each machine, machines which can be drained & machines which
    # should have draining cancelled
    #
    #---------------------------------------------------------------------------------

    # Machines which can be drained
    machines_can_drain = []

    # Machines which are draining but can be cancelled
    machines_draining_to_stop = []

    # Machines which are draining
    machines_are_draining = []

    machines_draining = 0

    #use a float here to force non integer ranks
    free_up_n_cpus = 8.0


    for condor_startd in condor_stards:
        #only care about partitonable slots, that supports efficent draining, is healthy and could run jobs
        #also, dont fuss with nodes in the KILL_SIGNAL state
        if (
                "PartitionableSlot" in condor_startd and
                "PREEMPTABLE_ONLY" in condor_startd and
                "NODE_IS_HEALTHY" in condor_startd and
                condor_startd["NODE_IS_HEALTHY"] == True and
                condor_startd["StartJobs"] == True
            ):

            machine = Machine(str(condor_startd["Machine"]))

            #can we ping the machine
            if not ping(machine.name):
                logger.warning("%s not contact-able, so skipping\n", machine.name)
                continue

            #totalCpus is the number of cpus on the machine
            machine.total_cpus = int(condor_startd["TotalCpus"])

            #int(result["Cpus"]) is the number of cpus on the slot, because we are only querying partionable slots,
            #this is effectively free cpus
            machine.num_free = int(condor_startd["Cpus"])

            if startd_will_hibernate(condor_startd, machine):
                logger.info("Skipping %s because it is about to hibernate.\n\n", machine.name)
                continue

            if startd_is_fast_draining(condor_startd):
                logger.info("Skipping %s because it is being fast hibernated.\n\n", machine.name)
                continue

            if startd_is_being_emptied(condor_startd):
                logger.info("Skipping %s because it is being efficently emptied.\n\n", machine.name)
                continue

            #get the jos running on this machine
            jobs = get_running_jobs(machine.name, condor_collector)

            if not jobs:
                logger.info("No jobs found for %s, skipping.\n", machine.name)
                continue

            #work out how many are preemptable
            machine.num_preemptable = 0
            machine.preemptable_jobs = []

            for job in jobs:
                if "JobId" in job:
                    if job["GlobalJobId"] in jobs_list:
                        machine.num_preemptable += 1
                        logger.debug("identified %s as preemptable", job["GlobalJobId"])

                        temp_job = Job(job["JobId"], job["GlobalJobId"], job["EnteredCurrentActivity"], job["ClientMachine"])
                        machine.preemptable_jobs.append(temp_job)
                    else:
                        logger.debug("identified %s as unpreemptable", job["GlobalJobId"])

            logger.debug('Machine                %-4s', machine.name)
            logger.debug('total CPUs             %-4s', machine.total_cpus)
            logger.debug('free CPUs              %-4s', machine.num_free)
            logger.debug('preemptable CPUs       %-4s', machine.num_preemptable)

            machine.total_killable_cpus = machine.num_free + machine.num_preemptable

            logger.debug('total killable CPUs    %-4s', machine.total_killable_cpus)

            if machine.total_killable_cpus >= free_up_n_cpus:
                machines_draining_to_stop.append(machine)
            else:
                if str(condor_startd["PREEMPTABLE_ONLY"]) == "True":
                    machines_are_draining.append(machine)
                    machines_draining += 1
                else:
                    machine.rank = (machine.total_cpus - machine.total_killable_cpus) / (free_up_n_cpus - machine.total_killable_cpus)
                    machines_can_drain.append(machine)

    #summary of results
    logger.info('Machines that can be drained')
    for machine in machines_can_drain:
        logger.info('%s %s', machine.name, machine.rank)

    logger.info('Machines with enough total Killable CPUs')
    for machine in machines_draining_to_stop:
        logger.info(machine.name)

    logger.info('Machines draining')
    for machine in machines_are_draining:
        logger.info(machine.name)

    #---------------------------------------------------------------------------------
    #
    # Kill jobs (and Cancel draining) of machines if they can take a multicore job
    #
    #---------------------------------------------------------------------------------

    logger.info('Actions taken...')
    # Cancel draining (and kill jobs) of machines which have N or more killable CPUs
    # if a machine stops drainiing because of this, PREEMPT THE PREEMPTABLE JOBS!
    for machine in machines_draining_to_stop:
        logger.info("Draining finished on %s", machine.name)
        try:
            #htcondor.set_subsystem("STARTD")
            #htcondor.reload_config()
            #condor_startd = condor_collector.locate(htcondor.DaemonTypes.Startd, "slot1@%(name)s" % machine)
            #htcondor.RemoteParam(condor_startd)

            kill_this_many = int(max((free_up_n_cpus * int(machine.total_killable_cpus / free_up_n_cpus)) - machine.num_free, 0))

            #kill the newest first, as they will have done the least
            machine.preemptable_jobs = sorted(machine.preemptable_jobs, key=attrgetter('start_time'), reverse=True)
            if kill_this_many > 0 and drain:
                #put node on hold so no new jobs can start while we kill jobs
                persistent_set(machine.name, "-startd", "StartJobs", "False")
                logger.info("Killing %i jobs %s", kill_this_many, machine.name)
                kill_jobs(condor_collector, machine, kill_this_many)
                time.sleep(10) #give jobs a chance to vacate before unholdin the job

        except IOError:
            logger.warning("IO Error killing jobs on %s, skipping.", machine.name)
        except RuntimeError:
            logger.warning("Runtime Error killing jobs on %s, skipping.", machine.name)

        try:
            #ensure the machine is in the correct state to run jobs
            #allow non preemptable jobs to run (if jobs could run)
            persistent_set(machine.name, "-startd", "PREEMPTABLE_ONLY", "False")
            #allow jobs to run
            persistent_set(machine.name, "-startd", "StartJobs", "True")
        except IOError:
            logger.critical("Could not get %(name)s back to a suitable state to run jobs!", machine)
            continue

    #---------------------------------------------------------------------------------
    #
    # Cancel Draining or Drain machines if necessary
    #
    #---------------------------------------------------------------------------------

    # if a machine stops draining because of this, we want to keep jobs running
    for machine in sorted(machines_are_draining, key=attrgetter('total_killable_cpus')):
        if machines_draining > max_concurrent_draining and machines_draining > 0:
            try:
                persistent_set(machine.name, "-startd", "PREEMPTABLE_ONLY", "False")
                logger.info('CANCEL DRAINING %s %s', machine.name, machine.total_killable_cpus)
                machines_draining -= 1
            except IOError:
                logger.error("Error setting %s to cancel draining, skipping.", machine.name)
                continue
        else:
            break


    for machine in sorted(machines_can_drain, key=attrgetter('rank'), reverse=True):
        if machines_draining < max_concurrent_draining:
            try:
                persistent_set(machine.name, "-startd", "PREEMPTABLE_ONLY", "True")
                logger.info('START DRAINING %s %s', machine.name, machine.rank)
                machines_draining += 1
            except IOError:
                logger.error("Error setting %s to drain, skipping.", machine.name)
        else:
            break

    if machines_draining != max_concurrent_draining:
        logger.warning("%i machines draining, should be %i", machines_draining, max_concurrent_draining)

    logger.info("Ending run at: %s", datetime.datetime.now())


if __name__ == "__main__":

    fp = open(FILENAME_MULTI_RUN_LOCK, 'w')

    try:
        fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        print "Defrag script is already running but has been called again (%s locked)." % FILENAME_MULTI_RUN_LOCK
        sys.exit(1)

    main()
