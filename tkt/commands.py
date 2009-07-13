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
    cmd = Command._get_cmd(arg)
    if cmd is None:
        sys.stderr.write("unknown tkt command: %s\n" % arg)
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

    def store_new_issue(self, title, description, type, user):
        issue = tkt.models.Issue({
            'id': uuid.uuid4().hex,
            'title': title,
            'description': description,
            'created': datetime.datetime.now(),
            'type': dict(tkt.models.Issue.types)[type],
            'status': 'open',
            'resolution': None,
            'creator': user,
            'events': []})

        issuepath = tkt.files.issue_filename(issue.id)
        issuedir = os.path.abspath(os.path.join(issuepath, os.pardir))

        if not os.path.exists(issuedir):
            os.makedirs(issuedir)

        fp = open(issuepath, 'w')
        try:
            issue.dump(fp)
        finally:
            fp.close()

    def store_new_configuration(self, username, useremail, datafolder):
        config = tkt.models.Configuration({
            'username': username,
            'useremail': useremail,
            'datafolder': datafolder})

        rcpath = self.configobj.rcfile()
        fp = open(rcpath, 'w')
        try:
            config.dump(fp)
        finally:
            fp.close()

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

        if hasattr(self, "usageinfo"):
            parser.usage += "\n%s" % self.usageinfo

        return parser

    @classmethod
    def _get_cmd(cls, name):
        return cls.cmds.get(name.replace('-', '_'))

class Add(Command):
    options = [
        {
            'short': '-t',
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

    usageinfo = "create a new ticket"

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

        self.store_new_issue(title, description, type, user)

    def pipemain(self):
        if not all(map(functools.partial(getattr, self.parsed_options),
                ["user", "title", "type"])):
            sys.stderr.write("required option(s) missing\n")
            sys.exit(1)

        user = self.parsed_options.user

        title = self.parsed_options.title

        typeoptions = set(pair[0] for pair in tkt.models.Issue.types)
        type = self.parsed_options.type
        if type not in typeoptions:
            sys.stderr.write("bad issue type: %s\n" % type)
            sys.exit(1)

        description = self.stdin.read()

        self.store_new_issue(title, description, type, user)

aliases('new')(Add)

class Help(Command):
    usage = "command"

    def main(self):
        if not self.parsed_args:
            sys.stderr.write("command argument required\n")
            sys.exit(1)
        arg = self.parsed_args[0]
        cmd = self._get_cmd(arg)
        if cmd is None:
            sys.stderr.write("unknown tkt command: %s\n" % arg)
            sys.exit(1)
        cmd()._build_parser().print_help()

aliases('man', 'info')(Help)

class Init(Command):
    options = [
        {
            'short': '-u',
            'long': '--username',
            'help': 'your name',
        },
        {
            'short': '-e',
            'long': '--useremail',
            'help': 'your email address'
        },
        {
            'short': '-f',
            'long': '--foldername',
            'help': 'name for the tkt data folder'
        }
    ]

    def main(self):
        self.configobj = tkt.models.Configuration(None)
        super(Init, self).main()

    def ttymain(self):
        default_username = self.configobj.default_username()
        username = self.parsed_options.username or \
                self.prompt("Your Name [%s]:" % default_username) or \
                default_username

        default_email = self.configobj.default_useremail()
        useremail = self.parsed_options.useremail or \
                self.prompt("Your E-Mail [%s]:" % default_email) or \
                default_useremail

        default_folder = self.configobj.default_datafolder()
        datafolder = self.parsed_options.foldername or \
                self.prompt("tkt Data Folder [%s]:" % default_folder) or \
                default_folder

        self.store_new_configuration(username, useremail, datafolder)

    def pipemain(self):
        if not all(map(functools.partial(getattr, self.parsed_options),
                ["username", "useremail", "foldername"])):
            sys.stderr.write("mising required option(s)\n")
            sys.exit(1)

        self.store_new_configuration(
            self.parsed_options.username,
            self.parsed_options.useremail,
            self.parsed_options.foldername)

aliases('setup')(Init)
