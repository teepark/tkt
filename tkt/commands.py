import bisect
import collections
import datetime
import operator
import optparse
import os
import random
import stat
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
    if len(sys.argv) > 1 and sys.argv[1] and not sys.argv[1].startswith('-'):
        arg = sys.argv[1]
    else:
        arg = DEFAULT
    cmd = Command.cmds.get(arg)
    if cmd is None:
        sys.stderr.write("unknown tkt command: %s\n" % arg)
        sys.exit(1)
    cmd().main()

def aliases(*names):
    def decorator(cls):
        for name in names:
            Command.cmds[name.replace("_", "-").lower()] = cls
        return cls
    return decorator

class CommandTracker(type):
    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, 'cmds'):
            cls.cmds = {}
        else:
            cls.cmds[cls.__name__.replace("_", "-").lower()] = cls

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

    if len(sys.argv) > 1 and sys.argv[1] and not sys.argv[1].startswith('-'):
        argv = sys.argv[2:]
    else:
        argv = sys.argv[1:]

    def main(self):
        if hasattr(getattr(self, 'prepare_options', None), '__call__'):
            self.prepare_options()

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

    def username(self):
        return "%s <%s>" % (tkt.config.config.username,
                            tkt.config.config.useremail)

    def prompt(self, msg):
        print msg,
        return raw_input()

    def editor_prompt(self, message=None):
        message = message or "Description"

        message += "\n\nEnter your text above. Lines starting with a '#' " + \
                "will be ignored."
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

    def fail(self, message):
        sys.stderr.write(message + "\n")
        sys.exit(1)

    def require_all_options(self, exceptions=None):
        required = set(o['long'][2:] for o in self.options).difference(
                exceptions or ())
        if not all(getattr(self.parsed_options, opt['long'][2:]) for opt in
                self.options):
            self.fail("missing required option(s)")

    def load_project(self):
        # also loads everything else:
        #   all issues (from Project.__init__),
        #   and all Events (from Issue.__init__)
        filename = tkt.files.project_filename()

        try:
            fp = open(filename)
        except IOError:
            dirname = os.path.dirname(filename)
            if not os.path.exists(dirname):
                os.path.makedirs(dirname)
            os.mknod(filename, 0644, stat.S_IFREG)
            return tkt.models.Project({'issues': []})

        try:
            return tkt.models.Project.load(fp)
        finally:
            fp.close()

    def store_new_issue(self, project, title, description, type, user):
        project = project or self.load_project()

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

        bisect.insort(project.issues, issue)

        issuepath = tkt.files.issue_filename(issue.id)
        issuedir = os.path.abspath(os.path.join(issuepath, os.pardir))

        if not os.path.exists(issuedir):
            os.makedirs(issuedir)

        fp = open(tkt.files.project_filename(), 'w')
        try:
            project.dump(fp)
        finally:
            fp.close()

        # this dumps the issue too
        self.store_new_event(issue, "issue created", issue.created, user, "")

        return issue

    def store_new_event(self, issue, title, created, creator, comment):
        event = tkt.models.Event({
            'id': uuid.uuid4().hex,
            'title': title,
            'created': created,
            'creator': creator,
            'comment': comment,
        })

        bisect.insort(issue.events, event)

        fp = open(tkt.files.issue_filename(issue.id), 'w')
        try:
            issue.dump(fp)
        finally:
            fp.close()

        fp = open(tkt.files.event_filename(issue.id, event.id), 'w')
        try:
            event.dump(fp)
        finally:
            fp.close()

        return event

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

        return config

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

class Add(Command):
    options = [
        {
            'short': '-t',
            'long': '--title',
            'help': 'the title for the ticket',
            'type': 'string',
        },
        {
            'short': '-p',
            'long': '--type',
            'help': 'the type of ticket: %s',
            'type': 'string',
        },
    ]

    usageinfo = "create a new ticket"

    def prepare_options(self):
        # delay doing this substitution until now in case
        # plugins wanted to add to the list of Issue types
        self.options[1]['help'] = self.options[1]['help'] % \
                tkt.models.Issue.types_text()

    def ttymain(self):
        title = self.parsed_options.title or self.prompt("Title:")

        typeoptions = set(pair[0] for pair in tkt.models.Issue.types)
        typeprompt = "Type - %s:" % tkt.models.Issue.types_text()
        type = self.parsed_options.type or self.prompt(typeprompt)
        while type not in typeoptions:
            type = self.parsed_options.type or self.prompt(typeprompt)

        description = self.editor_prompt()

        self.store_new_issue(None, title, description, type, self.username())

    def pipemain(self):
        self.require_all_options()

        title = self.parsed_options.title

        typeoptions = set(pair[0] for pair in tkt.models.Issue.types)
        type = self.parsed_options.type
        if type not in typeoptions:
            sys.stderr.write("bad issue type: %s\n" % type)
            sys.exit(1)

        description = sys.stdin.read()

        self.store_new_issue(None, title, description, type, self.username())

aliases('new')(Add)

class Help(Command):
    usage = "command"

    def main(self):
        if not self.parsed_args:
            print "Commands (use 'tkt help <cmd>' to see more detail)"
            print self.list_args()
            sys.exit()
        arg = self.parsed_args[0]
        cmd = self.cmds.get(arg)
        if cmd is None:
            sys.stderr.write("unknown tkt command: %s\n" % arg)
            sys.exit(1)
        cmd = cmd()
        if hasattr(getattr(cmd, "prepare_options"), "__call__"):
            cmd.prepare_options()
        cmd._build_parser().print_help()

    def list_args(self):
        cmds = {}
        for key, cmd in self.cmds.iteritems():
            cmds.setdefault(cmd, []).append(key)

        for cmd, names in cmds.items():
            cmds[cmd] = "/".join(sorted(names))

        output = []
        groups = sorted(cmds.iteritems(), key=operator.itemgetter(1))
        longest = max(len(pair[1]) for pair in groups)
        for cmd, names in groups:
            if hasattr(cmd, "usageinfo"):
                output.append("%s : %s" % (names.ljust(longest), cmd.usageinfo))
            else:
                output.append(names)

        return "\n".join(output)

aliases('man', 'info')(Help)

class Init(Command):
    options = [
        {
            'short': '-u',
            'long': '--username',
            'help': 'your name',
            'type': 'string',
        },
        {
            'short': '-e',
            'long': '--useremail',
            'help': 'your email address',
            'type': 'string',
        },
        {
            'short': '-f',
            'long': '--foldername',
            'help': 'name for the tkt data folder',
            'type': 'string',
        },
        {
            'short': '-p',
            'long': '--projectname',
            'help': 'name of the tracked project',
            'type': 'string',
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

        default_project = os.path.basename(os.path.abspath('.'))
        projectname = self.parsed_options.projectname or\
                self.prompt("Project Name [%s]:" % default_project) or\
                default_project

        self.store_new_configuration(username, useremail, datafolder)

        project = self.load_project()
        project.name = projectname

        fp = open(tkt.files.project_filename(), 'w')
        try:
            project.dump(fp)
        finally:
            fp.close()

    def pipemain(self):
        self.require_all_options()

        self.store_new_configuration(
            self.parsed_options.username,
            self.parsed_options.useremail,
            self.parsed_options.foldername)

aliases('setup')(Init)

class Todo(Command):

    options = [{
        'short': '-c',
        'long': '--show-closed',
        'help': 'also show closed tickets',
    }]

    def ttymain(self):
        project = self.load_project()
        for issue in project.issues:
            if self.parsed_options.show_closed or issue.status != "closed":
                print issue.view_one_line()

    pipemain = ttymain

class Show(Command):
    usage = "ticket"
    def ttymain(self):
        if not self.parsed_args and self.parsed_args[0]:
            self.fail("a ticket to show is required")

        tktname = self.parsed_args[0]
        for issue in self.load_project().issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        print issue.view_detail()

    pipemain = ttymain

aliases('view')(Show)

class Close(Command):
    usage = 'ticket'

    options = [{
        'short': '-r',
        'long': '--resolution',
        'help': 'how the ticket was resolved: %s',
        'type': 'int',
    }]

    def prepare_options(self):
        self.options[0]['help'] = self.options[0]['help'] % \
                tkt.models.Issue.resolutions_text()

    def ttymain(self):
        if not self.parsed_args and self.parsed_args[0]:
            self.fail("a ticket to close is required")

        tktname = self.parsed_args[0]
        for issue in self.load_project().issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        issue.status = "closed"

        self.store_new_event(
            issue,
            "ticket closed",
            datetime.datetime.now(),
            self.username(),
            self.editor_prompt("Comment"))

    pipemain = ttymain

aliases('finish', 'end')(Close)

class Reopen(Command):
    usage = 'ticket'

    def ttymain(self):
        if not self.parsed_args and self.parsed_args[0]:
            self.fail("a ticket to reopen is required")

        tktname = self.parsed_args[0]
        for issue in self.load_project().issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        if issue.status != "closed":
            self.fail("ticket %s isn't closed, you dummy!" % tktname)

        issue.status = "reopened"

        self.store_new_event(
            issue,
            "ticket reopened",
            datetime.datetime.now(),
            self.username(),
            self.editor_prompt("Comment"))

    pipmain = ttymain

class QA(Command):
    usage = 'ticket'

    def ttymain(self):
        if not self.parsed_args and self.parsed_args[0]:
            self.fail("a ticket to reopen is required")

        tktname = self.parsed_args[0]
        for issue in self.load_project().issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        issue.status = "resolution in QA"

        self.store_new_event(
            issue,
            "ticket sent to QA",
            datetime.datetime.now(),
            self.username(),
            self.editor_prompt("Comment"))

    pipemain = ttymain
