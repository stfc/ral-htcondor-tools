#!/usr/bin/python
# coding=utf8

import unittest

from mock import patch

import docker


class TestDockerWrapper(unittest.TestCase):
    def setUp(self):
        self.maxDiff = None
        self.atlas_job_args_before, self.atlas_job_args_after = [
            l.split() for l in open('test_resources/atlas_job.txt').readlines()
        ]
        self.cms_job_args_before, self.cms_job_args_after = [
            l.split() for l in open('test_resources/cms_job.txt').readlines()
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



if __name__ == '__main__':
    unittest.main()
