# svnstash

An svn extension that adds stashing to the repository.

## Features

* Stashes working directory to repository level so you'll never lose it.
* Tracks moved files (only using `svn mv`) from when you create a stash to when you apply it.

### Commands

Run `svnstash help` for details on the commands.

* apply - apply a stash
* dependencies - show all `svnstash` dependencies and if they are met
* list - list all stashes
* pop - apply and delete a stash
* push - stash (save) all changes and revert working directory
* remove - delete a stash
* save - save a stash without reverting
* show - show the details of a stash (in other words, dump the diff)

Bash Autocompletion
-------------------

Source the svnstash.bash file to get some autocompletion.  It's pretty rough for now, but will be better later.
