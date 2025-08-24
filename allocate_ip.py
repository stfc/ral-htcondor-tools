#!/usr/bin/python3

from datetime import datetime, timedelta
from ipaddress import ip_address, ip_network
from json import loads
from subprocess import Popen, PIPE
from sys import exit as sys_exit
from os.path import dirname
from os import mkdir

import sqlite3


SAVED_STATE_DB = '/var/cache/ral/docker_ips.db'


def db_connect():
    path = dirname(SAVED_STATE_DB)
    try:
        mkdir(path)
    except FileExistsError:
        pass
    return sqlite3.connect(SAVED_STATE_DB)


def db_load(connection):
    cursor = connection.cursor()

    ips = {}

    try:
        cursor.execute('SELECT * FROM ips')
    except sqlite3.OperationalError:
        cursor.execute('CREATE TABLE ips (ip INTEGER PRIMARY KEY, active REAL)')
        connection.commit()
        print('Initialised new saved state database %s' % SAVED_STATE_DB)

    cursor.execute('SELECT * FROM ips')
    for ip, activity in cursor.fetchall():
        if activity:
            activity = datetime.fromtimestamp(activity)
        ips[ip_address(ip)] = activity

    return ips


def docker_ip_activity(ips):
    p = Popen(['docker', 'network', 'inspect', 'ralworker'], stdout=PIPE, stderr=PIPE)
    stdout, stderr = p.communicate()

    if stdout and not stderr:
        timestamp = datetime.now()

        netdata = loads(stdout)
        if len(netdata) > 1:
            print('Got unexpected extra network data, will only use first network')

        netdata = netdata[0]

        iprange = netdata['IPAM']['Config'][0]['IPRange']

        containers = netdata['Containers']
        for _, c_data in containers.items():
            ip = ip_address(c_data['IPv4Address'].split('/', 1)[0])
            ips[ip] = timestamp

        for ip in ip_network(iprange).hosts():
            if ip not in ips:
                ips[ip] = None

        return ips

    else:
        print("Error fetching docker ip usage")
        print(stderr)
        sys_exit(1)


def update_ips(connection, ips):
    cursor = connection.cursor()

    for ip, activity in ips.items():
        ip = int(ip)
        if activity:
            activity = activity.timestamp()
        try:
            cursor.execute('INSERT INTO ips VALUES (?, ?)', (ip, activity))
        except sqlite3.IntegrityError:
            cursor.execute('UPDATE ips SET active = ? WHERE ip = ?', (activity, ip))

    connection.commit()


def get_lru_ip(connection):
    cursor = connection.cursor()

    timestamp_now = datetime.now().timestamp()
    timestamp_threshold = (datetime.now() - timedelta(minutes=5)).timestamp()

    cursor.execute(
        'SELECT ip FROM ips WHERE active <= ? OR active IS NULL ORDER BY active LIMIT 1;',
        (timestamp_threshold,),
    )
    row = cursor.fetchone()
    if row:
        ip = row[0]
        cursor.execute('UPDATE ips SET active = ? WHERE ip = ?', (timestamp_now, ip))
        connection.commit()
        return ip_address(ip)
    else:
        print("No IPs unused in last 5 minutes")
        sys_exit(1)


def allocate_ip():
    connection = db_connect()
    ips = db_load(connection)

    ips = docker_ip_activity(ips)

    update_ips(connection, ips)

    allocated_ip = get_lru_ip(connection)

    connection.close()

    return allocated_ip


def main():
    allocated_ip = allocate_ip()
    print("Allocated %s" % allocated_ip)


if __name__ == '__main__':
    main()
