#!/bin/bash

_svnstash () {
	local cur
	cur="${COMP_WORDS[*]:1}"
	comps=$(svnstash bash "$cur")
	
	if [ -z "$comps" ]; then
		return
	fi
	
	while read i
	do
		COMPREPLY=("${COMPREPLY[@]}" "${i}")
	done <<EOF
	$comps
EOF
}

complete -F _svnstash svnstash
