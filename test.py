#!/usr/bin/env python2.7

import os
import shutil
from cStringIO import StringIO
import subprocess
import sys

from nose.tools import *

import svnstash
from svnstash import cmds

svnstash.interactive = False

STDOUT = sys.stdout
STDERR = sys.stderr

TEST_DIR = os.path.abspath('test')
TEST_FILES = '%s/files' % TEST_DIR
TEST_ZONE = '%s/test_zone' % TEST_DIR
CLIENT_DIR = '%s/client' % TEST_ZONE
SERVER_DIR = '%s/server' % TEST_ZONE

def _mv(file, new):
	subprocess.check_output(['svn', 'mv', file, new])

def _rm(path):
	subprocess.check_output(['svn', 'rm', path])
	
def _add():
	subprocess.check_output('svn add --force %s/*' % CLIENT_DIR, shell=True)

def _commit():
	subprocess.check_output(['svn', 'commit', CLIENT_DIR, '-m', 'commit'])

def _command(cmd, args=[], interactive_response=False):
	""" Run an svnstash command with the given argument(s) """
	
	sys.argv = ['svnstash', cmd]
	
	svnstash.interactive_response = interactive_response
	
	if isinstance(args, list):
		sys.argv += args
	else:
		sys.argv.append(args)
	
	#capture the output from the commands
	stdout = StringIO()
	stderr = StringIO()
	sys.stdout = stdout
	sys.stderr = stderr
	
	svnstash.main()
	
	sys.stdout = STDOUT
	sys.stderr = STDERR
	ret = (stdout.getvalue(), stderr.getvalue())
	stdout.close()
	stderr.close()
	
	return ret

def _test_file(file_path):
	return '%s/%s' % (TEST_FILES, file_path)

def _client_file(client_path):
	return '%s/%s' % (CLIENT_DIR, client_path)

def _copy(file_path, client_path=''):
	shutil.copy(_test_file(file_path), _client_file(client_path))
	_add()

class Base(object):
	""" Basic setup for every test case """
	
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
		'''shutil.rmtree(TEST_ZONE)'''

class TestBash(Base):
	""" Make sure that bash autocompletes work properly """
	
	def test_autocomplete(self):
		#a minor cross-section of the possible autocompletions, just make sure it works
		assert _command('bash', 'a')[0].strip() == 'apply'
		assert _command('bash', 'ls')[0].strip() == 'ls'
		assert _command('bash', 'rem')[0].strip() == 'remove'
		assert _command('bash', 'sa')[0].strip() == 'save'

class TestClean(Base):
	""" Test a clean repo with nothing in it. """
	
	def test_ls(self):
		""" Make sure nothing is stashed """
		
		assert len(_command('list')[0]) == 0
	
	def test_pop(self):
		""" Make sure nothing can be popped """
		
		assert_raises(SystemExit, _command, 'pop')
		assert not cmds.svn_changes_exist(CLIENT_DIR)
	
	def test_push(self):
		""" Make sure nothing can be pushed """
		
		assert_raises(SystemExit, _command, 'push')
		self.test_ls()

class TestSingleTextChanges(Base):
	file = 'a_few_lines'
	file_moved = file + '_moved'
	
	file_changed = 'SingleTextChanges/a_few_lines'
	
	@classmethod
	def setUpClass(cls):
		pass
	
	def test_0_single_file(self):
		_copy(self.file)
		cmds.svn_add(_client_file(self.file))
		
		_command('push')
		assert not cmds.svn_changes_exist(CLIENT_DIR)
		
		stashes = svnstash.Stashes()
		
		assert len(stashes) == 1
		
		s = stashes[0]
		
		assert s.comment == ''
		assert len(s.get_affected_files()) == 1
		
		_command('pop')
		
		assert cmds.svn_changes_exist(CLIENT_DIR)
		assert len(cmds.svn_changes(CLIENT_DIR)) == 1
	
	def test_1_file_mod(self):
		_copy(self.file)
		_command('push')
		_copy(self.file_changed, self.file)
		_commit()
		
		assert not cmds.svn_changes_exist(CLIENT_DIR)
		
		_command('pop')
		
		assert cmds.svn_changes_exist(CLIENT_DIR)
	
	def test_2_moved_file(self):
		#Test response to committing a file, making changes to it, stashing it, moving that file,
		#then unstashing (the unstash will have the old file location, and it should update + conflict
		#with the new file, and patch should reject it)
		_copy(self.file)
		_commit()
		_copy(self.file_changed, self.file)
		_command('push')
		_copy(self.file_changed, self.file)
		_mv(self.file, self.file_moved)
		_commit()
		
		_command('pop')
		
		assert os.path.exists('%s/%s' % (CLIENT_DIR, self.file_moved))
		assert not os.path.exists('%s/%s.orig' % (CLIENT_DIR, self.file_moved))
		assert os.path.exists('%s/%s.rej' % (CLIENT_DIR, self.file_moved))
		assert not os.path.exists('%s/%s' % (CLIENT_DIR, self.file))
	
	def test_3_simple_moved_filed(self):
		#like test2, but without the conflict
		_copy(self.file)
		_commit()
		_copy(self.file_changed, self.file)
		_command('push')
		_mv(self.file, self.file_moved)
		_commit()
		
		_command('pop')
		
		assert os.path.exists('%s/%s' % (CLIENT_DIR, self.file_moved))
		assert not os.path.exists('%s/%s.orig' % (CLIENT_DIR, self.file_moved))
		assert not os.path.exists('%s/%s.rej' % (CLIENT_DIR, self.file_moved))
		assert not os.path.exists('%s/%s' % (CLIENT_DIR, self.file))
	
	def test_4_file_deleted(self):
		_copy(self.file)
		_commit()
		_copy(self.file_changed, self.file)
		_command('push')
		_rm(self.file)
		_commit()
		
		_command('pop', interactive_response=True)
		
		assert not os.path.exists('%s/%s' % (CLIENT_DIR, self.file))
		assert not os.path.exists('%s/%s.orig' % (CLIENT_DIR, self.file))
		assert not os.path.exists('%s/%s.rej' % (CLIENT_DIR, self.file))
		assert not os.path.exists('%s/%s' % (CLIENT_DIR, self.file))

if __name__== "__main__":
	import nose
	
	sys.argv += ['--exe', '--with-coverage', '--cover-package=svnstash', '--nocapture']
	
	nose.main(sys.argv)
