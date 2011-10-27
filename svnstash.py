#!/usr/bin/env python2.7

import os, sys
import subprocess
import time
import uuid
from datetime import datetime
from functools import wraps

try:
	import cPickle as pickle
except:
	import pickle

STASH_PATH = '.svn/stash'

commands = {}
help_list = {}

def command(*aliases):
	def call(fn, *a, **k):
		name = fn.__name__
		help = []
		
		commands[name] = fn
		
		#aliases are the same command
		for a in aliases:
			commands[a] = fn
			help.append(a)
		
		help_list[name] = help
		
		return fn
	
	return call

class StashError(Exception):
	pass

class Stashes(object):
	""" Tracks the stashes. """
	
	__built = False
	
	__DATA_FILE = '%s.data' % STASH_PATH
	
	def __init__(self):
		""" Finds the root of the svn repo and sets the svn_env variables """
		
		wd = os.getcwd()
		child = ''
		parent = ''
		grandparent = '.'
	
		while os.path.exists('%s/.svn' % wd):
			parent = grandparent
			grandparent = '%s/..' % parent
			child = '%s/%s' % (os.path.basename(wd), child)
			wd = os.path.dirname(wd)
	
		if not parent:
			raise StashError('could not find SVN root')
		
		self.svn_env = {
			'root': os.path.realpath(parent), #get the abs path to the root
			'child': os.path.relpath('/'.join(child.split('/')[1:]) or './'), #from trunk/test/some, remove trunk
			'abs_child': os.getcwd()
		}
		
		os.chdir(self.svn_env['root'])
		
		try:
			if not os.path.exists(self.__DATA_FILE):
				self.__data = []
			else:
				with open(self.__DATA_FILE) as f:
					self.__data = pickle.load(f)
			
			if not os.path.exists(STASH_PATH):
				os.makedirs(STASH_PATH)
		except:
			if not os.path.exists(STASH_PATH):
				raise StashError('could not create stash directory')
	
	def __len__(self):
		return len(self.__data)
	
	def __getitem__(self, i):
		return self.__data[i]
	
	def __delitem__(self, i):
		del self.__data[i]
	
	def cleanup(self):
		with open(self.__DATA_FILE, 'w') as f:
			pickle.dump(self.__data, f)
	
	def wd_changes_exist(self):
		return len(subprocess.check_output(['svn', 'status', self.svn_env['child']])) > 0
	
	def list(self):
		for i, f in enumerate(self.__data):
			print '%-2d | %s' % (i, f.get_printable())
	
	def push(self, comment=''):
		s = self.save(comment)
		s.revert()
	
	def save(self, comment=''):
		if not self.wd_changes_exist():
			raise StashError('there are no changes in working copy to stash')
	
		s = Stash(self.svn_env['child'], comment=comment)
		
		#store the new stash information
		self.__data.insert(0, s)
		
		s.save()
		
		return s
	
	def pop(self, i):
		s = self.apply(i)
		
		s.delete()
		
		self.__data.remove(s)
	
	def apply(self, i):
		if i < 0 or len(self.__data) <= i:
			raise StashError('no stash with index "%d" exists.' % i)
		
		s = self.__data[i]
		s.apply()
		
		return s

class Stash(object):
	def __init__(self, wd, created=time.time(), comment=''):
		self.id = str(uuid.uuid4())
		self.wd = wd
		self.created = created
		self.comment = comment
	
	def __repr__(self):
		return '<%s>' % self.get_printable()
	
	def __eq__(self, o):
		return self.id == o.id
	
	def __str__(self):
		return self.id
	
	def get_printable(self):
		return '%s  %s  %s %s' % (
			self.size,
			datetime.fromtimestamp(self.created).strftime('%H:%m %d-%m-%y'),
			self.wd if self.wd != '.' else '<root>',
			'- %s' % self.comment if len(self.comment) else ''
		)
	
	def get_file_path(self):
		return '%s/%s.diff' % (STASH_PATH, self.id)
	
	def get_affected_files(self):
		with open(self.get_file_path()) as f:
			return [l.lstrip('Index: ').strip() for l in f if l.find('Index: ') != -1] 
	
	def save(self):
		#save the changes to the diff file
		with open(self.get_file_path(), 'w') as diff:
			subprocess.Popen(['svn', 'diff', '--force', '--diff-cmd', '/usr/bin/diff', '-x', '-au --binary', self.wd], stdout=diff).wait()
		
		self.size = _human_readable_size(os.stat(self.get_file_path()).st_size)
		
	def revert(self):
		#remove any added files
		for f in subprocess.check_output(['svn', 'status', self.wd]).split('\n'):
			if f.startswith('A'):
				subprocess.check_output(['svn', 'remove', '--force', f.lstrip('A').strip()])
		
		#revert the directory
		subprocess.check_output(['svn', 'revert', '--depth=infinity', self.wd])	
	
	def apply(self):
		if stashes.wd_changes_exist():
			raise StashError('local changes exist; please stash or revert them.')
		
		subprocess.Popen(['patch', '-s', '-p0', '--binary', '-i', self.get_file_path()]).wait()
		for f in self.get_affected_files():
			if not os.path.exists(f):
				continue
			
			if os.stat(f).st_size == 0:
				subprocess.check_output(['svn', 'remove', '--force', f])
			else:
				subprocess.check_output(['svn', 'add', '-q', '--parents', f])
		
	def delete(self):
		os.remove(self.get_file_path())
	
def _help_general():
	print """usage: svnstash <command> [args ...]

Provides stashing functionality for svn

For more help on a command:
	svnstash help <command>

Available subcommands:"""

	keys = help_list.keys()
	keys.sort()

	for k in keys:
		aliases = help_list[k]
		aliases.sort()
		print '\t%s %s' % (k, '(%s)' % ', '.join(aliases) if len(aliases) else '')

def _help_command(cmd):
	print '\n'.join([l.strip() for l in commands[cmd].__doc__.split('\n') if len(l) > 1])

def _human_readable_size(num):
	#from: http://stackoverflow.com/questions/1094841/reusable-library-to-get-human-readable-version-of-file-size
    for x in ['B','K','M','G','T']:
        if num < 1024.0:
            return "%3.0f%s" % (num, x)
        num /= 1024.0

def _bash():
	global stashes
	
	try:
		args = len(sys.argv)
		
		#TODO - better bash searching for stashes
		
		if args > 3:
			pass
		elif args > 2 and sys.argv[2].strip() in commands.keys() and sys.argv[2][-1] != ' ':
			print '%s ' % sys.argv[2]
		elif args == 3:
			arg = sys.argv[2]
			for k in commands.keys():
				if k.startswith(arg):
					print '%s ' % k
		else:
			for k in commands.keys():
				print k
	except StashError:
		print '<error>'
		sys.exit()

@command()
def apply():
	"""
		usage: svnstash apply [index]
		
		Applies the most recent stash or the one given by [index] without deleting the stash
	"""
	if len(sys.argv) == 3:
		i = int(sys.argv[2])
	else:
		i = 0
	
	stashes.apply(id)	

@command()
def help():
	"""
		usage: svnstash help <command>
		
		Prints general information about a command
	"""
	
	if len(sys.argv) == 3 and commands[sys.argv[2]]:
		_help_command(sys.argv[2])
	else:
		_help_general()

@command('ls')
def list():
	"""
		usage: svnstash list
		
		Shows the list of all stashes, sorted by date.  All paths displayed are relative to the root of the repository.
	"""
	stashes.list()
	
@command()
def pop():
	"""
		usage: svnstash pop [index]
		
		Unstashes the most recent stash or the one given by [index]
	"""
	if len(sys.argv) == 3:
		i = int(sys.argv[2])
	else:
		i = 0
	
	stashes.pop(i)

@command()
def push():
	"""
		usage: svnstash push [comment]

		Stashes everything in the working directory, with an optional [comment]
	"""
	comment = ''
	if len(sys.argv) > 2:
		comment = ' '.join(sys.argv[2:])
	
	stashes.push(comment)

@command('rm')
def remove():
	"""
		usage: svnstash remove index

		Removes a stash without applying it
	"""
	if len(sys.argv) < 3:
		raise StashError('you must provide an index to delete')
	
	del stashes[int(sys.argv[2])]

@command()
def save():
	"""
		usage: svnstash save [comment]

		Saves everything in the working directory, with an optional [comment], without reverting
	"""
	comment = ''
	if len(sys.argv) > 2:
		comment = ' '.join(sys.argv[2:])
	
	stashes.save(comment)

def main():
	global stashes
	
	try:
		command = sys.argv[1] if len(sys.argv) > 1 else 'push'
		
		#bash is all kinds of special
		if command == 'bash':
			_bash()
		elif command in commands:
			stashes = Stashes()
			commands[command]()
			stashes.cleanup()
		else:
			help()
	except StashError as e:
		print 'Error: %s' % e.message

if __name__ == "__main__":
	main()
