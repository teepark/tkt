import os
import subprocess

import yaml


RCFILENAME = '.tktrc.yaml'
CONFIGVARS = ['username', 'useremail', 'datafolder']

# first, seach the current directory up to the root
_foundrcfile = False
_path = os.path.abspath(os.curdir)
_parentpath = os.path.abspath(os.path.join(_path, os.pardir))
while _path != _parentpath:
    _path = _parentpath
    _parentpath = os.path.abspath(os.path.join(_path, os.pardir))
    _rcpath = os.path.join(_path, RCFILENAME)
    if os.path.exists(_rcpath):
        globals().update(yaml.load(open(_rcpath)))
        _foundrcfile = True
        break

# failing that, try the user's home directory
if not _foundrcfile:
    _path = os.path.join(os.environ['HOME'], RCFILENAME)
    _rcpath = os.path.join(_path, RCFILENAME)
    if os.path.exists(_rcpath):
        globals().update(yaml.load(open(_rcpath)))
        _foundrcfile = True

# finally, do a best guess at values
if not _foundrcfile:
    username = os.environ['USER'].title()
    try:
        _proc = subprocess.Popen("hostname", stdout=subprocess.PIPE)
        _hostname = _proc.communicate()[0].rstrip()
    except:
        _hostname = "localhost.localdomain"
    useremail = "%s@%s" % (username.lower(), _hostname)
    datafolder = '.tkt'
    _rcpath = os.path.abspath(os.path.join(os.curdir, RCFILENAME))

# make sure we got all the values we needed
assert set(globals().keys()) >= set(CONFIGVARS), "missing config values: %s" % \
        ",".join(set(CONFIGVARS).difference(globals().keys()))

datapath = os.path.abspath(os.path.join(_rcpath, os.pardir, datafolder))
