#!/usr/bin/env python2.7

import getopt
import os
import shutil
import sys
import subprocess
import time
import uuid
from datetime import datetime
from xml.etree import ElementTree

try:
	import cPickle as pickle
except:
	import pickle

__author__ = 'Andrew Stone'
__copyright__ = 'Copyright 2011, Andrew Stone'
__status__ = 'Development'
__version__ = 'pre-alpha'

#useful constants
STASH_PATH = '.svn/stash'
EXTERNAL_DEPENDENCIES = ('svn', 'svnversion', 'lsdiff', ('cdiff', 'colordiff'))
SVN_DIVIDER = '-'*72

class STATUS(object):
	MAP = {'?': '?', '-': 'D', '+': 'A', '!': 'M'}
	UNKNOWN = MAP['?']
	DELETED = MAP['-']
	ADDED = MAP['+']
	MODIFIED = MAP['!']

commands = {}
help_list = {}

interactive = True

class StashError(Exception):
	pass

class Env(object):
	__slots__ = ['props']
	__props = {}
	
	def __getattr__(self, attr):
		if attr.startswith('has_'):
			attr = attr[4:]
			
			if not self.__props.has_key(attr):
				try:
					subprocess.check_output(['which', attr])
					self.__props[attr] = True
				except subprocess.CalledProcessError:
					self.__props[attr] = False
		
			return self.__props[attr]
		
		raise AttributeError('key "%s" not found' % attr)

class SvnLog(object):
	__slots__ = ['__log']
	
	def __init__(self, xml_log):
		self.__log = ElementTree.XML(xml_log)
	
	def __len__(self):
		return len(self.__log)
	
	def __getitem__(self, i):
		return SvnRevision(self.__log[i])

class SvnRevision(object):
	__slots__ = ['__rev']
	
	def __init__(self, rev):
		self.__rev = rev
	
	def was_deleted(self, path):
		""" Tells whether a path was deleted; will be True if the path was moved, too """
		
		for p in self.__rev.find('paths'):
			if p.text.lstrip('/') == path and p.get('action') == STATUS.DELETED:
				return True
		
		return False
	
	def get_new_path(self, path):
		""" Checks if an `svn mv` happened in a commit, and return the new path for the file; None, otherwise. """
		
		for p in self.__rev.find('paths'):
			copy_path = p.get('copyfrom-path')
			if copy_path and copy_path.lstrip('/') == path:
				return p.text.lstrip('/')
			
		return None
	
class CmdTools(object):
	""" Wraps some of the common svn functions that are needed """
	
	diff_file_indicator = 'Index: '
	diff_fi_len = len(diff_file_indicator)
	
	def get_root(self):
		""" From a directory inside an svn repo, it walks to the svn root directory. """
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
		
		return {
			'root': os.path.realpath(parent), #get the abs path to the root
			'child': os.path.relpath('/'.join(child.split('/')[1:]) or './'), #from trunk/test/some, remove trunk
			'abs_child': os.getcwd()
		}
	
	def svn_update(self, path):
		""" Runs `svn update` on a path """
		
		subprocess.check_output(['svn', 'update', path])
	
	def svn_changes(self, child_dir):
		""" An interable svn status in the form [('A', 'path/to/file'), ('M', 'path/to/another/file')] ('A', 'M', etc from STATUS) """
		
		return [(f[0], f[1:].strip()) for f in subprocess.check_output(['svn', 'status', child_dir]).split('\n')[:-1]]
	
	def svn_changes_exist(self, child_dir):
		""" Checks `svn status` to see if changes exist. """
		
		return len(self.svn_changes(child_dir)) > 0
	
	def svn_write_diff(self, wd, f):
		""" Write an svn diff to a file """
		
		subprocess.Popen(['svn', 'diff', '--force', '--diff-cmd', 'diff', '-x', '-au --binary', wd], stdout=f).wait()
	
	def svn_remove(self, path):
		""" Remove a path from svn """
		
		subprocess.check_output(['svn', 'remove', '--force', path])
	
	def svn_add(self, path):
		""" Add a path to svn """
		subprocess.check_output(['svn', 'add', '-q', '--parents', path])
	
	def svn_revert(self, path):
		""" Revert a path """
		
		subprocess.check_output(['svn', 'revert', '--depth=infinity', path])
	
	def svn_revision(self, path, from_server=False):
		""" Get the svn revision of a path, optionally asking the svn server for the most recent revision """
		
		return int(subprocess.check_output(['svnversion', path]).strip('MSP\n').split(':')[int(from_server)])
	
	def svn_log(self, path, start=0, end='HEAD'):
		""" Get an xml svn log of a path """
		
		return SvnLog(subprocess.check_output(['svn', 'log', '--xml', '-v', '-r', '%s:%s' % (str(start), str(end))]))
	
	def patch(self, diff_path):
		""" Run `patch` on the given diff. """
		
		subprocess.Popen(['patch', '--forward', '-p0', '--binary', '--batch', '-s', '-i', diff_path], stderr=subprocess.PIPE, stdout=subprocess.PIPE).wait()
	
	def color_diff(self, diff_path):
		""" Takes a diff file and gives it some color. """
		
		if not env.has_cdiff and not env.has_colordiff:
			#term-ansicolor uses cdiff which will use colordiff if available, or fallback to its own stuff
			raise StashError('you need to install the gem `term-ansicolor` or `colordiff` in order to get colored output.')
		
		if env.has_cdiff:
			return subprocess.check_output(['cdiff', diff_path])
		elif env.has_colordiff:
			with open(diff_path) as f:
				return subprocess.check_output(['colordiff'], stdin=f)
	
	def files_in_diff(self, diff, include_status=False):
		""" Gets a list of all the files described in a diff. """
		
		if env.has_lsdiff:
			args = ['lsdiff', diff]
			include_status and args.append('--status')
			files = subprocess.check_output(args).split('\n')[:-1] #don't include the last newline
		else:
			
			status = '? ' if include_status else ''
			
			with open(diff) as f:
				files = [status + l[self.diff_fi_len:].strip() for l in f if l.find(self.diff_file_indicator) != -1]
		
		if include_status:
			files = [(STATUS.MAP[f[0]], f[2:]) for f in files]
		
		return files
	
	def diff_move_files(self, diff, files):
		""" A _very dirty_ file reader/writer that rewrites paths in a diff file. """
		
		orig_diff = diff + '.old'
		shutil.move(diff, orig_diff)
		
		#have to keep state...arg, there has to be a better way to do this
		track_file = False
		
		#zomg that's a lot of indentation
		try:
			with open(orig_diff) as od, open(diff, 'w') as nd:
				for l in od:
					if l.startswith(self.diff_file_indicator):
						name = l[self.diff_fi_len:].strip()
						if name in files:
							track_file = True
							name = files[name]
						
						nd.write('%s%s\n' % (self.diff_file_indicator, name))
					elif l.startswith('---'):
						nd.write('--- %s\n' % name)
					elif l.startswith('+++'):
						nd.write('+++ %s\n' % name)
						track_file = False
					else:
						nd.write(l)
			
			os.remove(orig_diff)
		except:
			#revert the diffs if something goes wrong
			shutil.move(orig_diff, diff)
			raise
	
	def user_confirm(self, msg):
		""" A wrapper to help with unit testing """
		if interactive:
			return raw_input('%s (y,n)' % msg).lower() in ('y', 'ye', 'yes', 'true')
		else:
			return interactive_response
	
class Stashes(object):
	""" Tracks the stashes. """
	
	__built = False
	
	__DATA_FILE = '%s.data' % STASH_PATH
	
	def __init__(self):
		""" Finds the root of the svn repo and sets the svn_env variables """
		
		self.svn_env = cmds.get_root()
		
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
		""" The number of stashes being tracked """
		
		return len(self.__data)
	
	def __getitem__(self, i):
		""" Get a stash object at i """
		
		if i < 0 or i >= len(self.__data):
			raise StashError('no stash with index "%d" exists.' % i) 
		
		return self.__data[i]
	
	def __delitem__(self, i):
		""" Delete a stash """
		
		if i < 0 or i >= len(self.__data):
			raise StashError('no stash with index "%d" exists.' % i)
		
		del self.__data[i]
	
	def cleanup(self):
		""" Save any data that was modified during this run to the data file. """
		
		with open(self.__DATA_FILE, 'w') as f:
			pickle.dump(self.__data, f)
	
	def list(self, show_files=False):
		""" Print out a list of stashes to stdout, in human-readable form. """
		
		for i, s in enumerate(self.__data):
			print '%-2d | %s' % (i, s.get_printable())
			
			if show_files:
				print 'Changed paths:'
				
				for f in s.get_affected_files(include_status=True):
					print '\t%s' % f[0] + ' ' + f[1]
				
				print SVN_DIVIDER
	
	def push(self, comment=''):
		""" Save patch with [comment] and revert the working directory. """
		
		s = self.save(comment)
		s.revert()
	
	def save(self, comment=''):
		""" Save patch with [comment] without reverting the working directory. """
		
		if not cmds.svn_changes_exist(self.svn_env['child']):
			raise StashError('there are no changes in working copy to stash')
	
		s = Stash(self.svn_env['child'], comment=comment)
		
		#store the new stash information
		self.__data.insert(0, s)
		
		s.save()
		
		return s
	
	def pop(self, i):
		""" Apply patch i and remove it afterwards. """
		
		s = self.apply(i)
		
		s.delete()
		
		del self[i]
	
	def apply(self, i):
		""" Apply patch i without removing the patch afterwards """
		
		s = self[i]
		s.apply()
		
		return s

class Stash(object):
	def __init__(self, wd, comment=''):
		self.id = str(uuid.uuid4())
		self.wd = wd
		self.comment = comment
		
		self.created = time.time()
		self.revision = cmds.svn_revision(self.wd)
	
	def __repr__(self):
		return '<%s>' % self.get_printable()
	
	def __eq__(self, o):
		return self.id == o.id
	
	def __str__(self):
		return self.id
	
	def get_printable(self):
		""" A printable (human-readble) summary of the patch. """
		
		return '%s | %s | %s %s' % (
			self.size,
			datetime.fromtimestamp(self.created).ctime(),
			self.wd if self.wd != '.' else '<root>',
			'- %s' % self.comment if len(self.comment) else ''
		)
	
	def get_file_path(self):
		""" The absolute path to this stash's diff file """
		
		return '%s/%s.diff' % (STASH_PATH, self.id)
	
	def get_affected_files(self, include_status=False):
		""" Get the files affected by this stash """
		
		return cmds.files_in_diff(self.get_file_path(), include_status=include_status)
			
	def save(self):
		""" Save the diff of the current working directory into a stash """
		
		#save the changes to the diff file
		with open(self.get_file_path(), 'w') as diff:
			cmds.svn_write_diff(self.wd, diff)
		
		self.size = _human_readable_size(os.stat(self.get_file_path()).st_size)
		
	def revert(self):
		""" Remove any added files """
		
		for f in cmds.svn_changes(self.wd):
			#check path exists in case we delete a directory that contained added files
			if f[0] == STATUS.ADDED and os.path.exists(f[1]):
				cmds.svn_remove(f[1])
		
		cmds.svn_revert(self.wd)
	
	def apply(self):
		"""
			Apply the patch to the working directory without deleting the patch.
			Follow any file path changes made since the patch so that we're up-to-date.
		"""
		
		if cmds.svn_changes_exist(self.wd):
			raise StashError('changes exist in "%s"; please stash or revert them.' % self.wd)
		
		#our working directory MUST be in sync with the server, otherwise file movement tracing would be a terrible
		#mess. this is simpler and easier for everyone all around
		cmds.svn_update(self.wd)
		
		#since the wd is now up-to-date, finding the revision and doing our calculations is simple
		revision = cmds.svn_revision(self.wd)
		
		#check to make sure that all the files in the patch are up-to-date
		if revision != self.revision:
			if revision - self.revision >= 25:
				sys.stderr.write('Warning: this operation might take a while.\n')
			
			files = self.get_affected_files()
			log = cmds.svn_log(self.wd, start=self.revision, end=revision)
			moved_files = {}
			
			#trace each file in the diff and find its final resting place
			for f in files:
				final_path = f
				for rev in log:
					new_path = rev.get_new_path(f)
					if new_path:
						final_path = new_path
					elif rev.was_deleted(f):
						#warn the user if a file was removed, and give him the chance to abort
						if not cmds.user_confirm('Warning: the file "%s" in the stash has been deleted. Continue?' % f):
							raise StashError('dying by user request.')
						
						#make sure the deleted file in the diff doesn't touch any file that might be in its place now
						final_path = '/does/not/exist/'
				
				if final_path != f:
					moved_files[f] = final_path
			
			cmds.diff_move_files(self.get_file_path(), moved_files)
			
			#we rewrote the diff file, let's not cause any errors on return
			self.revision = revision
		
		#run the actual patch
		cmds.patch(self.get_file_path())
		
		#do some svn cleanup
		for f in self.get_affected_files():
			if not os.path.exists(f):
				continue
			
			if os.stat(f).st_size == 0:
				cmds.svn_remove(f)
			else:
				cmds.svn_add(f)
		
	def delete(self):
		os.remove(self.get_file_path())
	
	def dump(self, with_color=False):
		if with_color and (env.has_cdiff or env.has_colordiff):
			print cmds.color_diff(self.get_file_path())
		else:
			with open(self.get_file_path()) as f:
				print f.read()

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
	print commands[cmd].__doc__

def _human_readable_size(num):
	#from: http://stackoverflow.com/questions/1094841/reusable-library-to-get-human-readable-version-of-file-size
	for x in ['B','K','M','G','T']:
		if num < 1024.0:
			return "%3.0f%s" % (num, x)
		num /= 1024.0

def _bash():
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

@command()
def apply():
	"""usage: svnstash apply [index]

Applies the most recent stash or the one given by [index] without deleting the stash"""

	if len(sys.argv) == 3:
		i = int(sys.argv[2])
	else:
		i = 0
	
	stashes.apply(i)

@command()
def help():
	"""usage: svnstash help <command>

Prints general information about a command"""
	
	if len(sys.argv) == 3 and commands[sys.argv[2]]:
		_help_command(sys.argv[2])
	else:
		_help_general()

@command('ls')
def list():
	"""usage: svnstash list [options]

Shows the list of all stashes, sorted by date.  All paths displayed are relative to the root of the repository.

Options:
	-v, --verbose	print extra information about the stash"""
	
	opts = {
		'show_files': False
	}
	
	optlist, args = getopt.getopt(sys.argv[2:], 'v', ['verbose'])
	
	for o, a in optlist:
		if o in ('-v', '--verbose'):
			opts['show_files'] = True
	
	stashes.list(**opts)
	
@command()
def pop():
	"""usage: svnstash pop [index]

Unstashes the most recent stash or the one given by [index]"""

	if len(sys.argv) == 3:
		i = int(sys.argv[2])
	else:
		i = 0
	
	stashes.pop(i)

@command()
def push():
	"""usage: svnstash push [comment]

Stashes everything in the working directory, with an optional [comment]"""

	comment = ''
	if len(sys.argv) > 2:
		comment = ' '.join(sys.argv[2:])
	
	stashes.push(comment)

@command('rm')
def remove():
	"""usage: svnstash remove index

Removes a stash without applying it"""

	if len(sys.argv) < 3:
		raise StashError('you must provide an index to delete')
	
	del stashes[int(sys.argv[2])]

@command()
def dependencies():
	"""usage: svnstash dependencies

Prints the status of external dependencies for svnstash"""
	
	print 'External commands that svnstash relies on.  Only `svn` (which includes `svnversion`) is required.'
	
	for r in EXTERNAL_DEPENDENCIES:
		if isinstance(r, tuple):
			name = ' or '.join(r)
			present = any(getattr(env, 'has_%s' % i) for i in r)
		else:
			name = r
			present = getattr(env, 'has_%s' % r)
		
		print '%20s: %s' % (name, 'Yes' if present else 'No')

@command()
def save():
	"""usage: svnstash save [comment]

Saves everything in the working directory, with an optional [comment], without reverting"""
	
	comment = ''
	if len(sys.argv) > 2:
		comment = ' '.join(sys.argv[2:])
	
	stashes.save(comment)

@command()
def show():
	""" usage: svnstash show [options] index

Show the changes made in the given stash.  Be careful with binary diffs.

Options:
	-b, --no-color	Shows the diff without colored output"""
	
	opts = {
		'with_color': True
	}
	
	optlist, args = getopt.getopt(sys.argv[2:], 'b', ['no-color'])
	
	for o, a in optlist:
		if o in ('-b', '--no-color'):
			opts['with_color'] = False
	
	if not len(args):
		raise StashError('you must provide an index to show')
	
	stashes[int(args[0])].dump(**opts)

def main():
	global stashes
	
	try:
		command = sys.argv[1] if len(sys.argv) > 1 else 'list'
		
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
		sys.stderr.write('Error: %s\n' % e.message)
		sys.exit(1)
	except getopt.GetoptError as e:
		sys.stderr.write('Options error: %s\n' % e.msg)
		sys.exit(2)

env = Env()
cmds = CmdTools()

if __name__ == "__main__":
	main()
