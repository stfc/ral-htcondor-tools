#!/usr/bin/python
# coding=utf8

import unittest

try:
    from unittest.mock import patch
except ImportError:
    from mock import patch

from random import choice, randint
from string import ascii_letters
from os.path import dirname, join

import docker


class TestDockerWrapper(unittest.TestCase):
    def setUp(self):
        self.maxDiff = None
        self.resource_dir = join(dirname(__file__), 'test_resources')
        self.atlas_job_args_before, self.atlas_job_args_after = [
            l.split() for l in open(join(self.resource_dir, 'atlas_job.txt')).readlines()
        ]
        self.cms_job_args_before, self.cms_job_args_after = [
            l.split() for l in open(join(self.resource_dir, 'cms_job.txt')).readlines()
        ]

    def mocked_getfqdn(self):
        return 'host.example.org'

    def test_gateway(self):
        self.assertFalse(docker.gateway([]))
        self.assertFalse(docker.gateway(['']))
        self.assertFalse(docker.gateway(['version']))

        self.assertTrue(docker.gateway(self.atlas_job_args_before))
        self.assertTrue(docker.gateway(self.cms_job_args_before))

    def test_args_create(self):
        basic_args = [
            '-eSINGULARITY_BINDPATH=/etc/hosts',
            '--cap-add=SYS_ADMIN',
            '--cap-add=DAC_OVERRIDE',
            '--cap-add=SETUID',
            '--cap-add=SETGID',
            '--cap-add=SYS_CHROOT',
            '--env=SINGULARITYENV_FRONTIER_LOG_FILE=frontier.log',
            '--env=PANDA_HOSTNAME=host.example.org',
            '--env=SINGULARITYENV_PANDA_HOSTNAME=host.example.org',
            '--env=PILOT_NOKILL=1',
        ]
        with patch('docker.getfqdn') as mock_socket:
            mock_socket.return_value = 'host.example.org'

            self.assertEqual(docker.args_create([]), basic_args + ['--label=xrootd-local-gateway=false'])
            self.assertEqual(docker.args_create(['']), basic_args + ['--label=xrootd-local-gateway=false', ''])

            self.assertEqual(docker.args_create(self.atlas_job_args_before), self.atlas_job_args_after)
            self.assertEqual(docker.args_create(self.cms_job_args_before), self.cms_job_args_after)

    def test_args_run(self):
        with patch('docker.args_create') as mock_args_create:
            test_args = ['foo', 'bar']
            docker.args_run(test_args)
            mock_args_create.assert_called_with(test_args)

    def test_args_other_commands(self):
        random_args = [
            ''.join([ choice(ascii_letters) for _ in range(0, randint(3, 9)) ])
            for __ in range(0, randint(2, 12))
        ]
        # args_other_commands should return the input without modification
        self.assertEqual(random_args, docker.args_other_commands(random_args))


if __name__ == '__main__':
    unittest.main()
