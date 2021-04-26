#!/usr/bin/python
# coding=utf8

import unittest

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

    def test_gateway(self):
        self.assertFalse(docker.gateway([]))
        self.assertFalse(docker.gateway(['']))
        self.assertFalse(docker.gateway(['version']))

        self.assertTrue(docker.gateway(self.atlas_job_args_before))
        self.assertTrue(docker.gateway(self.cms_job_args_before))



if __name__ == '__main__':
    unittest.main()
