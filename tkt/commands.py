import datetime
import hashlib
import optparse
import os
import random
import subprocess
import sys
import tempfile
import uuid

import tkt.files
import tkt.models
import tkt.config


DEFAULT = "todo"

def main():
    import tkt.plugins
    arg = len(sys.argv) > 1 and sys.argv[1] or DEFAULT
    cmd = Command.cmds.get(arg)
    if cmd is None:
        print "unknown tkt command: %s" % arg
        sys.exit(1)
    cmd().main()

def aliases(*names):
    def decorator(cls):
        for name in names:
            Command.cmds[name.lower()] = cls
        return cls
    return decorator

class CommandTracker(type):
    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, 'cmds'):
            cls.cmds = {}
        else:
            cls.cmds[cls.__name__.lower()] = cls

class Command(object):
    __metaclass__ = CommandTracker

    # override with a list of dictionaries with these keys:
    # - short: -a, -b (the short version)
    # - long: --long-version
    # - type(optional): for option value: int, float, string(default)
    #   - if no type, option won't accept a value, just be a flag
    #   - if type is "counter", no value but can be accepted multiple times
    #     and it will increment a counter, so the value comes in as an int
    # - default(optional): default value for the option
    options = []

    # only for specifying positional arguments in the usage message:
    # usage = "foo [bar]" -> "usage: tkt <commandname> foo [bar] [options]"
    usage = ""

    argv = sys.argv[2:]

    def main(self):
        if sys.stdin.isatty():
            self.ttymain()
        else:
            self.pipemain()

    def ttymain(self):
        raise NotImplementedError()

    def pipemain(self):
        raise NotImplementedError()

    @property
    def parsed_options(self):
        if not hasattr(self, "_options_args"):
            self._options_args = self._build_parser().parse_args(self.argv)
        return self._options_args[0]

    @property
    def parsed_args(self):
        if not hasattr(self, "_options_args"):
            self._options_args = self._build_parser().parse_args(self.argv)
        return self._options_args[1]

    def prompt(self, msg):
        print msg,
        return raw_input()

    def editor_prompt(self, message=None):
        message = message or """Description

Enter your text above. Lines starting with a '#' will be ignored."""
        message = "\n## " + "\n## ".join(message.splitlines())

        temp = tempfile.mktemp()
        fp = open(temp, 'w')
        try:
            fp.write(message)
        finally:
            fp.close()

        proc = subprocess.Popen([os.environ.get("EDITOR", "vi"), temp])
        proc.wait()

        fp = open(temp)
        try:
            text = fp.read()
        finally:
            fp.close()

        return "\n".join(l for l in text.splitlines() if not l.startswith("#"))

    def _build_parser(self):
        parser = optparse.OptionParser()

        for opt in self.options:
            short = opt.get("short")
            long = opt.get("long")
            kwargs = {}

            type = opt.get("type")
            if type is None:
                kwargs["action"] = "store_true"
            elif type == "counter":
                kwargs["action"] = "count"
            else:
                kwargs["type"] = type
                kwargs["action"] = "store"

            kwargs["default"] = opt.get("default")

            help = opt.get("help")
            if help: kwargs["help"] = help

            parser.add_option(short, long, **kwargs)

        parser.usage = "tkt %s %s [options]" % (
                self.__class__.__name__.lower(), self.usage)

        return parser

class Add(Command):
    options = [
        {
            'short': '-n',
            'long': '--title',
            'help': 'the title for the ticket',
        },
        {
            'short': '-p',
            'long': '--type',
            'help': 'the type of ticket: %s'
        },
        {
            'short': '-u',
            'long': '--user',
            'help': 'the creating user'
        }
    ]

    def main(self):
        # delay doing this substitution until now in case
        # plugins wanted to add to the list of Issue types
        self.options[1]['help'] = self.options[1]['help'] % \
                tkt.models.Issue.types_text()

        super(Add, self).main()

    def ttymain(self):
        defaultuser = "%s <%s>" % (tkt.config.config.username,
                                   tkt.config.config.useremail)
        user = self.parsed_options.user or \
                self.prompt("Issue creator [%s]:" % defaultuser)
        if not user:
            user = defaultuser

        title = self.parsed_options.title or self.prompt("Title:")

        typeoptions = set(pair[0] for pair in tkt.models.Issue.types)
        typeprompt = "Type - %s:" % tkt.models.Issue.types_text()
        type = self.parsed_options.type or self.prompt(typeprompt)
        while type not in typeoptions:
            type = self.parsed_options.type or self.prompt(typeprompt)

        description = self.editor_prompt()

        issue = tkt.models.Issue({
            'id': hashlib.sha1(uuid.uuid4().bytes).hexdigest(),
            'title': title,
            'description': description,
            'created': datetime.datetime.now(),
            'type': dict(tkt.models.Issue.types)[type],
            'status': 'open',
            'resolution': None,
            'creator': user,
            'events': []
        })

        issuepath = tkt.files.issue_filename(issue.id)
        issuedir = os.path.abspath(os.path.join(issuepath, os.pardir))

        if not os.path.exists(issuedir):
            os.makedirs(issuedir)

        fp = open(issuepath, 'w')
        try:
            issue.dump(fp)
        finally:
            fp.close()

aliases('new')(Add)
