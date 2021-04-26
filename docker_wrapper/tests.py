#!/usr/bin/python
# coding=utf8

import unittest

import docker


class TestDockerWrapper(unittest.TestCase):
    def setUp(self):
        self.cms_job_args = open('test_resources/cms_job.txt').read().split()
        self.atlas_job_args = open('test_resources/atlas_job.txt').read().split()

    def test_gateway(self):
        self.assertFalse(docker.gateway([]))
        self.assertFalse(docker.gateway(['']))
        self.assertFalse(docker.gateway(['version']))

        self.assertTrue(docker.gateway(self.cms_job_args))
        self.assertTrue(docker.gateway(self.atlas_job_args))


if __name__ == '__main__':
    unittest.main()
