import datetime
import functools
import glob
import itertools
import operator
import optparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import tkt.files
import tkt.models
import tkt.config
import tkt.getplugins
import yaml


CLOSED = tkt.models.Issue.CLOSED
DEFAULT = "todo"

loader_class = yaml.__with_libyaml__ and yaml.CLoader or yaml.Loader
dumper_class = yaml.__with_libyaml__ and yaml.CDumper or yaml.Dumper

_load = yaml.load
def load_yaml(*args, **kwargs):
    kwargs.pop('Loader', 0)
    return _load(*args, Loader=loader_class, **kwargs)
yaml.load = load_yaml

_dump = yaml.dump
def dump_yaml(*args, **kwargs):
    kwargs.pop('Dumper', 0)
    return _dump(*args, Dumper=dumper_class, **kwargs)
yaml.dump = dump_yaml

def main():
    tkt.getplugins.getplugins()
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

    try:
        cmd.main()
    except KeyboardInterrupt:
        cmd.fail("Cancelled")

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

def hextimestamp(dt):
    return "%x" % int(time.mktime(dt.timetuple()))

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
        user = tkt.config.user()
        return "%s <%s>" % (user.username,
                            user.useremail)

    def gather_ticket(self, try_prompting=True, prompt="Ticket:"):
        if not (self.parsed_args and self.parsed_args[0]):
            if try_prompting:
                tktname = self.prompt(prompt)
            else:
                self.fail("a ticket argument is required")
        else:
            tktname = self.parsed_args[0]

        if tktname.startswith("#"):
            tktname = tktname[1:]

        if tktname.isdigit():
            t = int(tktname)
            if t >= len(self.project.issue_filenames):
                self.fail("there is no ticket #%d" % t)
            return self.project._load_issue(t, self.project.issue_filenames[t])

        found = False
        for index, filename in enumerate(self.project.issue_filenames):
            if tktname in os.path.abspath(filename).split(os.sep)[-2]:
                if found:
                    self.fail("more than one ticket matches '%s'" % tktname)
                issue = (index, filename)
                found = True
        if found:
            return self.project._load_issue(*issue)

        for issue in self.project.issues:
            if tktname in issue.valid_names:
                return issue

        self.fail("no ticket found with name %s" % tktname)

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
        return tkt.config.project()

    def store_new_issue(self, **data):
        dt = datetime.datetime.now()
        utc = tkt.timezones.to_utc(dt)
        data['status'] = 'unstarted'
        data['resolution'] = None
        data['events'] = data.get('events') or []
        data['id'] = "%s-%s" % (hextimestamp(utc)[:8], uuid.uuid4().hex[:8])
        data['created'] = dt

        issue = tkt.models.Issue(data)

        issuelist = self.project.issues
        issuelist.append(issue)

        issuepath = tkt.files.issue_filename(issue.id)
        issuedir = os.path.abspath(os.path.join(issuepath, os.pardir))

        if not os.path.exists(issuedir):
            os.makedirs(issuedir)

        self.store_issue(issue)
        self.store_new_event(issue, "ticket created", issue.created,
            self.gather_creator(), "")

        return issue

    def store_new_event(self, issue, title, created, creator, comment):
        utc = tkt.timezones.to_utc(created)
        event = tkt.models.Event({
            'id': "%s-%s" % (hextimestamp(utc)[:8], uuid.uuid4().hex[:8]),
            'title': title,
            'created': created,
            'creator': creator,
            'comment': comment,
        })

        eventlist = issue.events
        eventlist.append(event)

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
            'short': '-i',
            'long': '--plugins',
            'help': 'a comma-separated list of python-paths to plugins',
            'type': 'string'
        }
    ]

    usageinfo = "set up a new tkt repository"

    def gather_plugins(self):
        if self.parsed_options.plugins:
            return [p.strip() for p in self.parsed_options.plugins.split(",")]

        plugins = []
        while 1:
            plugin = self.prompt("Add a plugin [Enter when finished]:")
            if not plugin:
                break
            plugins.append(plugin)

        return plugins

    def main(self):
        projpath, projpathexists = tkt.models.ProjectConfig.findpath()
        datafolder = os.path.dirname(projpath)

        if not os.path.isdir(datafolder):
            os.makedirs(datafolder)

        project = tkt.models.ProjectConfig({'plugins': self.gather_plugins()})

        fp = open(projpath, 'w')
        try:
            project.dump(fp)
        finally:fp.close()

aliases('setup')(Init)

class Todo(Command):
    options = [{
        'short': '-a',
        'long': '--show-all',
        'help': 'also show closed tickets',
    }]

    usageinfo = "list tickets"

    def main(self):
        self.display_issues(self.project.issues)

    def display_issues(self, issuelist):
        notclosed = [i for i in issuelist if i.status != CLOSED]
        issues = self.parsed_options.show_all and issuelist or notclosed

        for issue in issues:
            print issue.view_one_line()

        if not issues:
            if self.parsed_options.show_all:
                print "no tickets"
            else:
                print "no open tickets"

class Show(Command):
    usage = "[<ticket>]"

    usageinfo = "display a ticket in detail"

    def main(self):
        print self.gather_ticket().view_detail()

aliases('view')(Show)

class Close(Command):
    usage = '[<ticket>]'

    usageinfo = "mark a ticket as closed"

    options = [{
        'short': '-r',
        'long': '--resolution',
        'help': 'how the ticket was resolved: %s',
        'type': 'string',
    }]

    required_data = ["ticket", "resolution"]

    def prepare_options(self):
        self.options[0]['help'] = self.options[0]['help'] % \
                tkt.models.Issue.resolutions_text(', ')

    def gather_resolution(self, try_prompting=True):
        resolutions = dict(tkt.models.Issue.resolutions)

        provided = self.parsed_options.resolution
        if provided and provided.isdigit() and int(provided) in resolutions:
            return resolutions[int(provided)]

        if provided:
            if provided not in resolutions.itervalues():
                self.fail("%s is not a known resolution" % provided)
            return provided

        if try_prompting:
            while 1:
                resolution = self.prompt("%s\nResolution:" %
                        tkt.models.Issue.resolutions_text())

                if resolution.isdigit() and int(resolution) in resolutions:
                    return resolutions[int(resolution)]

                if resolution in resolutions.values():
                    return resolution

        self.fail("a resolution is required")

    def ttymain(self):
        data = self.gather()
        issue = data['ticket']
        issue.resolution = data['resolution']
        issue.status = CLOSED

        self.store_issue(issue)
        self.store_new_event(
            issue,
            "ticket closed",
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

    def pipemain(self):
        issue = self.gather_ticket(try_prompting=False)
        issue.resolution = self.gather_resolution(try_prompting=False)
        issue.status = CLOSED

        self.store_issue(issue)
        self.store_new_event(
            issue,
            "ticket closed",
            datetime.datetime.now(),
            self.gather_creator(),
            "")

aliases('finish', 'end')(Close)

class Reopen(Command):
    usage = '[<ticket>]'

    usageinfo = "reopen a closed ticket"

    def main(self):
        issue = self.gather_ticket()

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

class QA(Command):
    usage = '[<ticket>]'

    usageinfo = "mark a ticket as ready for QA"

    def ttymain(self):
        issue = self.gather_ticket()

        issue.status = "resolution in QA"
        issue.resolution = None

        self.store_issue(issue)
        self.store_new_event(
            issue,
            "ticket sent to QA",
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

    def pipemain(self):
        issue = self.gather_ticket(try_prompt=False)

        issue.status = "resolution in QA"
        issue.resolution = None

        self.store_issue(issue)
        self.store_new_event(
            issue,
            "ticket sent to QA",
            datetime.datetime.now(),
            self.gather_creator(),
            "")

class Comment(Command):
    usage = '[<ticket>]'

    usageinfo = "add a comment to a ticket"

    def ttymain(self):
        self.store_new_event(
            self.gather_ticket(),
            "comment added",
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

    def pipemain(self):
        msg = sys.stdin.read()
        if not msg:
            self.fail("a comment is required")

        self.store_new_event(
            self.gather_ticket(try_prompting=False),
            "comment added",
            datetime.datetime.now(),
            self.gather_creator(),
            msg)

aliases('annotate')(Comment)

class Drop(Command):
    usage = '[<ticket>]'

    usageinfo = "completely purge a ticket from the repository"

    def main(self):
        issue = self.gather_ticket()
        shutil.rmtree(os.path.dirname(tkt.files.issue_filename(issue.id)))

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
    usage = "[<ticket>]"

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
        issue = self.gather_ticket()

        data = dict(zip(issue.fields, map(functools.partial(getattr, issue),
                                          issue.fields)))
        dumpdata = {}
        for field in issue.fields:
            if field in self.uneditable_fields:
                continue
            dumpdata[field] = getattr(issue, field)

        temp = tempfile.mktemp()
        fp = open(temp, 'w')
        try:
            yaml.dump(dumpdata, stream=fp, default_flow_style=False)
        finally:
            fp.close()

        proc = subprocess.Popen([os.environ.get("EDITOR", "vi"), temp])
        proc.wait()

        fp = open(temp)
        try:
            loaddata = yaml.load(fp)
        except:
            self.fail("that was invalid yaml")
        finally:
            fp.close()

        if dumpdata == loaddata:
            self.fail("no changes")

        # heavy validation so we don't wind up in an inconsistent state
        for key, value in loaddata.iteritems():
            if key == "status":
                if not self.validate_status_resolution(value,
                        loaddata.get('resolution')):
                    self.fail('edited ticket is invalid')

            if key == "resolution":
                continue

            if not hasattr(self, "validate_%s" % key):
                self.fail("edited ticket is invalid")

            if not getattr(self, "validate_%s" % key)(value):
                self.fail("edited ticket is invalid")

        issue.__dict__.update(loaddata)

        self.store_issue(issue)
        self.store_new_event(
            issue,
            "ticket edited",
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

class Start(Command):
    usage = "[<ticket>]"

    usageinfo = "record work started on a ticket"

    required_data = ["ticket"]

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
    usage = "[<ticket>]"

    usageinfo = "record work stopped on a ticket"

    def main(self):
        issue = self.gather_ticket()

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

    path_regex = re.compile(r"([0-9a-f]{8}-[0-9a-f]{8})/" +
            r"(ticket|[0-9a-f]{8}-[0-9a-f]{8})\.yaml")

    def main(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a regular expression argument required")

        dirname = tkt.config.datapath()
        args = ["grep", "-E", self.parsed_args[0]]
        args.extend(glob.glob("%s%stickets%s*%s*.yaml" %
                (dirname, os.sep, os.sep, os.sep)))

        proc = subprocess.Popen(args, stdout=subprocess.PIPE)
        output = proc.communicate()[0]

        matches = map(self.path_regex.search, output.splitlines())
        matches = set(match.groups()[0] for match in matches if match)

        #TODO: load only the ones we need
        foundone = False
        for issue in self.project.issues:
            if issue.id in matches:
                foundone = True
                print issue.view_one_line()

        if not foundone:
            print "no matches found"

class Search(Command):
    usageinfo = "search for tickets by field/value"

    options = [
        {
            'short': '-i',
            'long': '--id',
            'type': 'string',
            'help': 'the id of a ticket',
        },
        {
            'short': '-n',
            'long': '--title',
            'type': 'string',
            'help': 'the title of a ticket',
        },
        {
            'short': '-c',
            'long': '--creator',
            'type': 'string',
            'help': 'the name or email of the ticket creator',
        },
        {
            'short': '-t',
            'long': '--type',
            'type': 'string',
            'help': 'the type of ticket (%s)',
        },
        {
            'short': '-s',
            'long': '--status',
            'type': 'string',
            'help': 'the current status of the ticket (%s)',
        },
        {
            'short': '-r',
            'long': '--resolution',
            'type': 'string',
            'help': 'the resolution of the ticket (%s)',
        },
        {
            'short': '-d',
            'long': '--description',
            'type': 'string',
            'help': 'a portion of the ticket description',
        },
    ]

    def prepare_options(self):
        self.options[3]['help'] %= ', '.join(p[1] for p in
                                             tkt.models.Issue.types)

        self.options[4]['help'] %= ', '.join(p[1] for p in
                                             tkt.models.Issue.statuses)

        self.options[5]['help'] %= ', '.join(p[1] for p in
                                             tkt.models.Issue.resolutions)

    filters = [
        "id",
        "title",
        "creator",
        "type",
        "status",
        "resolution",
        "description",
    ]

    nulls = set(["null", "none", "nil"])

    def filter_id(self, issue):
        if not self.parsed_options.id:
            return True
        return self.parsed_options.id.lower() in issue.id.lower()

    def filter_title(self, issue):
        if not self.parsed_options.title:
            return True
        return self.parsed_options.title.lower() in issue.title.lower()

    def filter_creator(self, issue):
        if not self.parsed_options.creator:
            return True
        return self.parsed_options.creator.lower() in issue.creator.lower()

    def filter_type(self, issue):
        if not self.parsed_options.type:
            return True
        return self.parsed_options.type.lower() == issue.type.lower()

    def filter_status(self, issue):
        if not self.parsed_options.status:
            return True
        return self.parsed_options.status.lower() == issue.status.lower()

    def filter_resolution(self, issue):
        if not self.parsed_options.resolution:
            return True
        if not issue.resolution:
            return self.parsed_options.resolution.lower() in self.nulls
        if self.parsed_options.resolution.lower() in self.nulls:
            return not issue.resolution
        return self.parsed_options.resolution.lower() == issue.resolution.lower()

    def filter_description(self, issue):
        if not self.parsed_options.description:
            return True
        if not issue.description:
            return self.parsed_options.description.lower() in self.nulls
        return (self.parsed_options.description.lower() in
                issue.description.lower())

    def run_all_filters(self, issue):
        return all(getattr(self, "filter_%s" % f)(issue) for f in self.filters)

    def main(self):
        if not any(getattr(self.parsed_options, i, 0) for i in self.filters):
            self.fail("at least one of the filtering options is required")

        issues = itertools.ifilter(self.run_all_filters, self.project.issues)
        at_least_one = False

        for issue in issues:
            at_least_one = True
            print issue.view_one_line()

        if not at_least_one:
            print "no matching tickets"

aliases('find')(Search)

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
        import tkt.fromditz

        Init().main()

        self.project.plugins = list(set(self.project.plugins or []) | set([
            "tkt.plugins.claiming",
            "tkt.plugins.labels",
            "tkt.plugins.releases"]))

        fp = open(tkt.files.project_filename(), 'w')
        try:
            self.project.dump(fp)
        finally:
            fp.close()

        tkt.getplugins.getplugins()

        tkt.fromditz.main()

aliases('fromditz')(ImportDitz)

class Upgrade(Command):
    usageinfo = "upgrade an old tkt data folder to the latest version"

    usage = "<version>"

    def gather_upgrader(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a version is required")
        upgrader = self.upgrades.get(self.parsed_args[0])
        if not upgrader:
            self.fail("upgrades are %s" % ", ".join(self.upgrades.keys()))
        return upgrader

    def point_three_upgrade(self):
        self.issue_id_map = issue_id_map = {}

        oldfolders = glob.glob("%s%s*" % (tkt.config.datapath(), os.sep))
        oldfolders = filter(os.path.isdir, oldfolders)

        oldidregex = re.compile("^[0-9a-f]{32}$")

        for oldfolder in oldfolders:
            oldid = oldfolder.split(os.path.sep)[-1]

            if not oldidregex.match(oldid):
                continue

            oldpath = os.path.join(oldfolder, "issue.yaml")

            fp = open(oldpath)
            try:
                issuedata = yaml.load(fp)
            finally:
                fp.close()

            newid = "%s-%s" % (hextimestamp(issuedata['created']), oldid[:8])
            issuedata['id'] = newid
            issue_id_map[oldid] = newid

            newfolder = os.path.join(os.path.dirname(oldfolder), newid)
            newpath = os.path.join(newfolder, "issue.yaml")

            os.rename(oldfolder, newfolder)

            fp = open(newpath, 'w')
            try:
                yaml.dump(issuedata, fp, default_flow_style=False)
            finally:
                fp.close()

            for oldeventfile in glob.glob(os.path.join(newfolder, "*.yaml")):
                if oldeventfile.endswith("issue.yaml"):
                    continue

                fp = open(oldeventfile)
                try:
                    eventdata = yaml.load(fp)
                finally:
                    fp.close()

                timestamp = int(time.mktime(eventdata['created'].timetuple()))
                neweventid = "%s-%s" % (hextimestamp(eventdata['created']),
                                        eventdata['id'][:8])
                eventdata['id'] = neweventid

                neweventfile = os.path.join(os.path.dirname(oldeventfile),
                                            "%s.yaml" % neweventid)

                fp = open(neweventfile, 'w')
                try:
                    yaml.dump(eventdata, fp, default_flow_style=False)
                finally:
                    fp.close()

                os.unlink(oldeventfile)

    def point_four_upgrade(self):
        issueid_regex = re.compile("[0-9a-f]{8}-[0-9a-f]{8}")

        folders = glob.glob("%s%s*-*" % (tkt.config.datapath(), os.sep))

        ticketsfolder = os.path.join(tkt.config.datapath(), "tickets")
        if not os.path.exists(ticketsfolder):
            os.makedirs(ticketsfolder)

        for oldfold in folders:
            newfold = os.path.join(ticketsfolder, os.path.basename(oldfold))
            shutil.mv(oldfold, newfold)

        issuefiles = glob.glob(os.path.join(ticketsfolder, "*", "issue.yaml"))
        for oldfile in issuefiles:
            newfile = os.path.join(os.path.dirname(oldfile), "ticket.yaml")
            shutil.mv(oldfile, newfile)

    upgrades = {
        '0.3': point_three_upgrade,
        '0.4': point_four_upgrade,
    }

    def main(self):
        upgrader = self.gather_upgrader()

        upgrader(self)
