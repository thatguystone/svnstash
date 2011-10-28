#!/usr/bin/env python2.7

import os
import shutil
from cStringIO import StringIO
import subprocess
import svnstash
import sys

STDOUT = sys.stdout

TEST_DIR = os.path.abspath('test')
TEST_FILES = '%s/files' % TEST_DIR
TEST_ZONE = '%s/test_zone' % TEST_DIR
CLIENT_DIR = '%s/client' % TEST_ZONE
SERVER_DIR = '%s/server' % TEST_ZONE

def command(cmd, args=[]):
	sys.argv = ['svnstash', cmd]
	
	if isinstance(args, list):
		sys.argv += args
	else:
		sys.argv.append(args)
	
	#capture the output from the commands
	out = StringIO()
	sys.stdout = out
	
	svnstash.main()
	
	sys.stdout = STDOUT
	ret = out.getvalue()
	out.close()
	
	return ret

class Base(object):
	def setUp(self):
		if os.path.exists(TEST_ZONE):
			shutil.rmtree(TEST_ZONE)
		
		#create a test space to work in
		os.mkdir(TEST_ZONE)
		subprocess.check_output(['svnadmin', 'create', SERVER_DIR])
		subprocess.check_output(['svn', 'checkout', 'file://%s' % SERVER_DIR, CLIENT_DIR])
		
		#we always operate inside the svn reo
		os.chdir(CLIENT_DIR)
		
	def tearDown(self):
		#clear all the test data
		shutil.rmtree(TEST_ZONE)

class TestBasics(Base):
	def test_ls(self):
		#clean repo, there should be nothing there
		assert len(command('list')) == 0

class TestBash(Base):
	def test_autocomplete(self):
		#a minor cross-section of the possible autocompletions, just make sure it works
		assert command('bash', 'a').strip() == 'apply'
		assert command('bash', 'ls').strip() == 'ls'
		assert command('bash', 'rem').strip() == 'remove'
		assert command('bash', 'sa').strip() == 'save'
		

if __name__== "__main__":
	import nose
	
	sys.argv += ['--exe', '--with-coverage', '--cover-package=svnstash', '--nocapture']
	
	nose.main(sys.argv)
