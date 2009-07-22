import bisect
import collections
import datetime
import functools
import glob
import operator
import optparse
import os
import random
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

import tkt.files
import tkt.models
import tkt.config
import yaml


CLOSED = tkt.models.Issue.CLOSED
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
    cmd = cmd()

    cmd.prepare_options()

    cmd.main()

def track_opens():
    builtinopen = __builtins__.open
    globals()['openedfiles'] = opened = []
    def opener(name, mode='rb'):
        opened.append((name, mode))
        return builtinopen(name, mode)
    __builtins__.open = opener

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
    # usage = "foo [bar]" -> "usage: tkt <commandname> foo [bar] [<options>]"
    usage = ""

    required_data = ["creator"]

    if len(sys.argv) > 1 and sys.argv[1] and not sys.argv[1].startswith('-'):
        argv = sys.argv[2:]
    else:
        argv = sys.argv[1:]

    def main(self):
        if sys.stdin.isatty():
            self.ttymain()
        else:
            self.pipemain()

    def ttymain(self):
        raise NotImplementedError()

    def pipemain(self):
        raise NotImplementedError()

    def prepare_options(self):
        pass

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

    def gather_creator(self):
        return "%s <%s>" % (tkt.config.config.username,
                            tkt.config.config.useremail)

    def gather(self):
        data = {}
        for name in self.required_data:
            data[name] = getattr(self, "gather_%s" % name)()
        return data

    def prompt(self, msg):
        print msg,
        return raw_input()

    def editor_prompt(self, message=""):
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

    @property
    def project(self):
        if not hasattr(tkt.config.config, "project"):
            tkt.config.config.project = self.load_project()
        return tkt.config.config.project

    @classmethod
    def load_project(cls):
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

    def store_new_issue(self, **data):
        data['status'] = 'unstarted'
        data['resolution'] = None
        data['events'] = data.get('events') or []
        data['id'] = uuid.uuid4().hex
        data['created'] = datetime.datetime.now()

        issue = tkt.models.Issue(data)

        issuelist = self.project.issues
        bisect.insort(issuelist, issue)

        issuepath = tkt.files.issue_filename(issue.id)
        issuedir = os.path.abspath(os.path.join(issuepath, os.pardir))

        if not os.path.exists(issuedir):
            os.makedirs(issuedir)

        self.store_issue(issue)
        self.store_new_event(issue, "issue created", issue.created,
            self.gather_creator(), "")

        return issue

    def store_new_event(self, issue, title, created, creator, comment):
        event = tkt.models.Event({
            'id': uuid.uuid4().hex,
            'title': title,
            'created': created,
            'creator': creator,
            'comment': comment,
        })

        eventlist = issue.events
        bisect.insort(eventlist, event)

        fp = open(tkt.files.event_filename(issue.id, event.id), 'w')
        try:
            event.dump(fp)
        finally:
            fp.close()

        return event

    def store_issue(self, issue):
        fp = open(tkt.files.issue_filename(issue.id), 'w')
        try:
            issue.dump(fp)
        finally:
            fp.close()

    def store_new_configuration(self, username, useremail, datafolder):
        config = tkt.models.Configuration({
            'username': username,
            'useremail': useremail,
            'datafolder': datafolder,
        })

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

        parser.usage = "tkt %s %s [<options>]" % (
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

    required_data = ['title', 'description', 'type', 'creator']

    def prepare_options(self):
        self.options[1]['help'] = self.options[1]['help'] % \
                tkt.models.Issue.types_text()

    def gather_title(self):
        return self.parsed_options.title or self.prompt("Title:")

    def gather_type(self):
        typeoptions = set(pair[0] for pair in tkt.models.Issue.types)

        typeprompt = "Type - %s:" % tkt.models.Issue.types_text()

        type = self.parsed_options.type or self.prompt(typeprompt)
        while type not in typeoptions:
            type = self.parsed_options.type or self.prompt(typeprompt)

        return dict(tkt.models.Issue.types)[type]

    def gather_description(self):
        return self.editor_prompt("Description")

    def ttymain(self):
        self.store_new_issue(**self.gather())

    def pipemain(self):
        self.require_all_options()

        title = self.parsed_options.title

        typeoptions = set(pair[0] for pair in tkt.models.Issue.types)
        type = self.parsed_options.type
        if type not in typeoptions:
            sys.stderr.write("bad issue type: %s\n" % type)
            sys.exit(1)

        description = sys.stdin.read()

        self.store_new_issue(
            title=title,
            description=description,
            type=type,
            creator=self.gather_creator())

aliases('new')(Add)

class Help(Command):
    usage = "[<command>]"

    usageinfo = "explain tkt commands"

    def main(self):
        if not self.parsed_args:
            print "Commands (use 'tkt help <cmd>' to see more detail)\n"
            print self.list_args()
            sys.exit()
        arg = self.parsed_args[0]
        cmd = self.cmds.get(arg)
        if cmd is None:
            sys.stderr.write("unknown tkt command: %s\n" % arg)
            sys.exit(1)
        cmd = cmd()
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
                output.append(" %s: %s" % (names.rjust(longest), cmd.usageinfo))
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
        },
        {
            'short': '-i',
            'long': '--plugins',
            'help': 'a comma-separated list of python-paths to plugins',
            'type': 'string'
        }
    ]

    usageinfo = "set up a new tkt repository"

    def main(self):
        self.configobj = tkt.models.Configuration(None)
        Command.main(self)

    def ttymain(self):
        default_username = self.configobj.get('username')
        username = self.parsed_options.username or \
                self.prompt("Your Name [%s]:" % default_username) or \
                default_username

        default_email = self.configobj.get('useremail')
        useremail = self.parsed_options.useremail or \
                self.prompt("Your E-Mail [%s]:" % default_email) or \
                default_useremail

        default_folder = self.configobj.get('datafolder')
        datafolder = self.parsed_options.foldername or \
                self.prompt("tkt Data Folder [%s]:" % default_folder) or \
                default_folder

        default_project = os.path.basename(os.path.abspath('.'))
        projectname = self.parsed_options.projectname or\
                self.prompt("Project Name [%s]:" % default_project) or\
                default_project

        if self.parsed_options.plugins:
            plugins = self.parsed_options.plugins.split(',')
        else:
            plugins = []
            while 1:
                plugin = self.prompt("Plugin Python-Path [Enter to end]:")
                if not plugin:
                    break
                plugins.append(plugin)

        if not self.configobj._filepresent:
            self.store_new_configuration(username, useremail, datafolder)

        self.project.name = projectname
        self.project.plugins = plugins

        fp = open(tkt.files.project_filename(), 'w')
        try:
            self.project.dump(fp)
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

    usageinfo = "list tickets"

    def main(self):
        self.display_issues(self.project.issues)

    def display_issues(self, issuelist):
        notclosed = [i for i in issuelist if i.status != CLOSED]
        issues = self.parsed_options.show_closed and issuelist or notclosed

        for issue in issues:
            print issue.view_one_line()

        if not issues:
            if self.parsed_options.show_closed:
                print "no tickets"
            else:
                print "no open tickets"

class Show(Command):
    usage = "<ticket>"

    usageinfo = "display a ticket in detail"

    def main(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket to show is required")

        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        print issue.view_detail()

aliases('view')(Show)

class Close(Command):
    usage = '<ticket>'

    usageinfo = "mark a ticket as closed"

    options = [{
        'short': '-r',
        'long': '--resolution',
        'help': 'how the ticket was resolved: %s',
        'type': 'int',
    }]

    def prepare_options(self):
        self.options[0]['help'] = self.options[0]['help'] % \
                tkt.models.Issue.resolutions_text()

    def prompt_resolution(self):
        resolutions = dict(tkt.models.Issue.resolutions)
        while 1:
            resolution = self.prompt("Resolution - %s:" %
                    tkt.models.Issue.resolutions_text())
            try:
                resolution = int(resolution)
            except ValueError:
                continue
            if resolution in resolutions:
                return resolutions[resolution]

    def gather_ticket(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket to close is required")

        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                return issue
        self.fail("no ticket found with name %s" % tktname)

    def main(self):
        issue = self.gather_ticket()
        issue.status = CLOSED
        issue.resolution = self.prompt_resolution()

        self.store_issue(issue)
        self.store_new_event(
            issue,
            "ticket closed",
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

aliases('finish', 'end')(Close)

class Reopen(Command):
    usage = '<ticket>'

    usageinfo = "reopen a closed ticket"

    def ttymain(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket to reopen is required")

        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        if issue.status != CLOSED:
            self.fail("ticket %s isn't closed, you dummy!" % tktname)

        issue.status = "reopened"
        issue.resolution = None

        self.store_issue(issue)
        self.store_new_event(
            issue,
            "ticket reopened",
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

    pipmain = ttymain

class QA(Command):
    usage = '<ticket>'

    usageinfo = "mark a ticket as ready for QA"

    def main(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket to send to QA is required")

        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        issue.status = "resolution in QA"
        issue.resolution = None

        self.store_issue(issue)
        self.store_new_event(
            issue,
            "ticket sent to QA",
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

class Comment(Command):
    usage = '<ticket>'

    usageinfo = "add a comment to a ticket"

    def main(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket to comment is required")

        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        self.store_new_event(
            issue,
            "comment added",
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

aliases('annotate')(Comment)

class Drop(Command):
    usage = '<ticket>'

    usageinfo = "completely purge a ticket from the repository"

    def gather_ticket(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket to drop is required")

        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                return issue
        self.fail("no ticket found with name %s" % tktname)

    def main(self):
        issue = self.gather_ticket()

        shutil.rmtree(os.path.dirname(tkt.files.issue_filename(issue.id)))

        self.project.issues.remove(issue)

        fp = open(tkt.files.project_filename(), 'w')
        try:
            self.project.dump(fp)
        finally:
            fp.close()

aliases('delete')(Drop)

class Status(Command):
    usageinfo = 'print a rundown of the progress on all tickets'

    def main(self):
        print self.display_status(self.project.issues)

    def display_status(self, issues):
        tickets = {}
        for issue in issues:
            tickets.setdefault(issue.type, []).append(issue)

        text = []
        types = sorted(tkt.models.Issue.types, key=operator.itemgetter(1))
        for char, type in types:
            issuegroup = tickets.get(type, [])
            text.append("%d/%d %s" % (
                len([i for i in issuegroup if i.status == CLOSED]),
                len(issuegroup),
                type))

        issuechars = [issue.view_one_char() for issue in issues]
        self.charoptions = [s[0] for s in tkt.models.Issue.statuses]
        issuechars.sort(key=self.issuecharkeyfunc)

        return "%s  %s" % (",  ".join(text), "".join(issuechars))

    def issuecharkeyfunc(self, s):
        if s in self.charoptions:
            return self.charoptions.index(s)
        return -1

class Edit(Command):
    usage = "<ticket>"

    usageinfo = "edit the ticket data directly with your text editor"

    uneditable_fields = ["id"]

    def validate_title(self, title):
        return isinstance(title, basestring)

    def validate_description(self, description):
        return isinstance(description, basestring)

    def validate_created(self, created):
        return isinstance(created, datetime.datetime)

    def validate_type(self, type):
        for char, name in tkt.models.Issue.types:
            if name == type:
                return True
        return False

    def validate_status_resolution(self, status, resolution):
        if resolution is None:
            return status != CLOSED

        if status != CLOSED:
            return False

        for char, name in tkt.models.Issue.statuses:
            if name == status:
                break
        else:
            return False

        for num, name in tkt.models.Issue.resolutions:
            if name == resolution:
                break
        else:
            return False

        return True

    def validate_creator(self, creator):
        return isinstance(creator, basestring)

    def validate_status(self, status):
        return status in [p[1] for p in tkt.models.Issue.statuses]

    def main(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket to edit is required")

        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        data = dict(zip(issue.fields, map(functools.partial(getattr, issue),
                                          issue.fields)))
        data = {}
        for field in issue.fields:
            if field in self.uneditable_fields:
                continue
            data[field] = getattr(issue, field)

        temp = tempfile.mktemp()
        fp = open(temp, 'w')
        try:
            yaml.dump(data, stream=fp, default_flow_style=False)
        finally:
            fp.close()

        proc = subprocess.Popen([os.environ.get("EDITOR", "vi"), temp])
        proc.wait()

        fp = open(temp)
        try:
            data = yaml.load(fp)
        except:
            self.fail("that was invalid yaml")
        finally:
            fp.close()

        # heavy validation so we don't wind up in an inconsistent state
        for key, value in data.iteritems():
            if key == "status":
                if not self.validate_status_resolution(value,
                        data.get('resolution')):
                    print "status/resolution fail"
                    self.fail('edited ticket is invalid')

            if key == "resolution":
                continue

            if not hasattr(self, "validate_%s" % key):
                print "no validator for %s" % key
                self.fail("edited ticket is invalid")

            if not getattr(self, "validate_%s" % key)(value):
                print "validation failed for %s" % key
                self.fail("edited ticket is invalid")

        issue.__dict__.update(data)

        self.store_issue(issue)
        self.store_new_event(
            issue,
            "ticket edited",
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

class Start(Command):
    usage = "<ticket>"

    usageinfo = "record work started on a ticket"

    required_data = ["ticket"]

    def gather_ticket(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket to start is required")

        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                return issue

        self.fail("no ticket found with name %s" % tktname)

    def main(self):
        issue = self.gather_ticket()

        issue.status = "in progress"
        issue.resolution = None

        self.store_issue(issue)
        self.store_new_event(
            issue,
            "work on ticket started",
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

aliases('work')(Start)

class Stop(Command):
    usage = "<ticket>"

    usageinfo = "record work stopped on a ticket"

    def main(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket to stop is required")

        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        if issue.status != "in progress":
            self.fail("ticket %s isn't in progress, you dummy!" % tktname)

        issue.status = "paused"
        issue.resolution = None

        self.store_issue(issue)
        self.store_new_event(
            issue,
            "work on ticket stopped",
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

aliases('pause')(Stop)

class Grep(Command):
    usage = "<regular-expression>"

    usageinfo = "search for tickets that match a regular expression"

    def main(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a regular expression argument required")

        dirname = os.path.dirname(tkt.files.project_filename())
        args = ["grep", "-E", self.parsed_args[0]]
        args.extend(glob.glob("%s%s*%s*.yaml" % (dirname, os.sep, os.sep)))

        proc = subprocess.Popen(args, stdout=subprocess.PIPE)
        output = proc.communicate()[0]

        regex = re.compile("([0-9a-f]{32})/((issue)|([0-9a-f]{32}))\.yaml:")
        matches = map(regex.search, output.splitlines())
        matches = set(match.groups()[0] for match in matches if match)

        foundone = False
        for issue in self.project.issues:
            if issue.id in matches:
                foundone = True
                print issue.view_one_line()

        if not foundone:
            print "no matches found"

aliases('search')(Grep)

class Log(Command):
    usage = "[<ticket>]"

    usageinfo = "short form of recent activity"

    def main(self):
        if self.parsed_args:
            tktname = self.parsed_args[0]
            for issue in self.project.issues:
                if tktname in issue.valid_names:
                    events = issue.events
                    break
            else:
                self.fail("no ticket found with name %s" % tktname)
        else:
            events = []
            for issue in self.project.issues:
                events.extend(issue.events)
            events.sort()

        if not events:
            print "nothing to report"
            sys.exit()

        log = []
        for event in events:
            log.append([
                "%s ago" % tkt.flextime.since(event.created),
                event.issue.name,
                event.issue.creator, 
                event.title
            ])

        longest = [0] * len(log[0])
        for item in log:
            for i, text in enumerate(item):
                longest[i] = max(longest[i], len(text))

        for item in log:
            for i, text in list(enumerate(item)):
                if i == len(item) - 1:
                    item[i] = text.ljust(longest[i])
                else:
                    item[i] = text.rjust(longest[i])

            print " " + " | ".join(item)

aliases('shortlog')(Log)

class ImportDitz(Command):
    usageinfo = "start your new repository from the current ditz repo"

    def main(self):
        Init().main()

        import tkt.fromditz
        tkt.fromditz.main()

aliases('fromditz')(ImportDitz)
