import functools
import glob
import operator
import os
import stat
import subprocess

import tkt.files
import tkt.flextime
import tkt.timezones
import yaml


class Model(object):
    def __init__(self, data):
        data = data or {}
        for field in self.fields:
            self.__dict__.setdefault(field, None)

        if not isinstance(data, dict):
            data = dict(data)
        self.__dict__.update(data)

    def timezones_to_utc(self):
        pass

    def timezones_to_local(self):
        pass

    fields = []

    def yamlable(self):
        getter = functools.partial(getattr, self)
        data = dict(zip(self.fields, map(getter, self.fields)))
        for k, v in data.items():
            if isinstance(v, Model):
                data[k] = v.yamlable()
            elif isinstance(v, list) and v and isinstance(v[0], Model):
                data[k] = map(lambda x: x.yamlable(), v)
        return data

    @classmethod
    def load(cls, stream):
        obj = cls(yaml.load(stream))
        obj.timezones_to_local()
        return obj

    def dump(self, stream=None):
        self.timezones_to_utc()
        data = self.yamlable()
        self.timezones_to_local()
        return yaml.dump(data, stream=stream, default_flow_style=False)

    def view_one_char(self):
        return "?"

    def view_one_line(self):
        return "not implemented"

    def view_detail(self):
        return "not implemented"

class Configuration(Model):
    fields = ['username', 'useremail', 'datafolder']

    RCFILENAME = '.tktrc.yaml'
    DEFAULT_DATAFOLDER = '.tkt'

    def __init__(self, data):
        Model.__init__(self, data)
        self._filepresent = any(self.__dict__.values())
        for fieldname in self.fields:
            if not getattr(self, fieldname):
                setattr(self, fieldname,
                        getattr(self, "default_%s" % fieldname)())

    def get(self, name):
        attr = getattr(self, name, None)
        if attr is None:
            return getattr(self, "default_%s" % name)()
        return attr

    @classmethod
    def _find(cls, name, searchhome=False):
        path = os.path.abspath(os.curdir)
        parentpath = os.path.abspath(os.path.join(path, os.pardir))

        rcpath = os.path.join(path, name)
        if os.path.exists(rcpath):
            return rcpath

        # the theory is that once we reach the root, the parent folder's path
        # is the same as the current folder's path
        while path != parentpath:
            path = parentpath
            parentpath = os.path.abspath(os.path.join(path, os.pardir))

            rcpath = os.path.join(path, name)
            if os.path.exists(rcpath):
                return rcpath

        if searchhome:
            homedir = os.environ.get('HOME')
            if not homedir:
                return None

            rcpath = os.path.abspath(os.path.join(homedir, name))
            if os.path.exists(rcpath):
                return rcpath
        return None

    @classmethod
    def rcfile(cls):
        rcfile = cls._find(cls.RCFILENAME, searchhome=True)
        if not rcfile:
            rcfile = os.path.abspath(os.path.join('.', cls.RCFILENAME))
            os.mknod(rcfile, 0644, stat.S_IFREG)
        return rcfile

    @property
    def datapath(self):
        if not hasattr(self, "_datapath"):
            folder = self._find(self.datafolder)
            if not folder:
                folder = os.path.abspath(os.path.join('.',
                        self.DEFAULT_DATAFOLDER))
                os.mkdir(folder)
            self._datapath = folder
        return self._datapath

    def default_username(self):
        return (os.environ.get('USER') or 'anonymous user').title()

    def default_useremail(self):
        if not hasattr(self, 'username'):
            self.username = self.default_username()
        try:
            proc = subprocess.Popen("hostname", stdout=subprocess.PIPE)
            hostname = proc.communicate()[0].rstrip()
        except:
            hostname = "localhost.localdomain"
        return "%s@%s" % (self.username.lower().replace(" ", "."), hostname)

    def default_datafolder(self):
        return self.DEFAULT_DATAFOLDER

class Event(Model):
    fields = [
        "id",
        "title",
        "created",
        "creator",
        "comment",
    ]

    def __lt__(self, other):
        return self.created < other.created

    def timezones_to_utc(self):
        self.created = tkt.timezones.to_utc(self.created)

    def timezones_to_local(self):
        self.created = tkt.timezones.to_local(self.created)

    def view_detail(self):
        if self.comment:
            comment = "\n  > %s" % "\n  > ".join(self.comment.splitlines())
        else:
            comment = ""
        return "- %s (%s, %s)%s" % (
            self.title,
            self.creator,
            "%s ago" % tkt.flextime.since(self.created),
            comment)

class Issue(Model):
    fields = [
        "id",
        "title",
        "description",
        "created",
        "type",
        "status",
        "resolution",
        "creator",
    ]

    types = [
        ("b", "bugfix"),
        ("f", "feature"),
        ("t", "task"),
    ]

    type_map = dict(p[::-1] for p in types)

    @classmethod
    def types_text(cls):
        text = []
        for char, name in cls.types:
            index = name.find(char)
            text.append("%s(%s)%s" % (name[:index], char, name[index + 1:]))
        return ", ".join(text)

    CLOSED = "closed"

    statuses = [
        ("x", CLOSED),
        ("q", "resolution in QA"),
        ("r", "reopened"),
        ("_", "unstarted"),
        ("=", "paused"),
        (">", "in progress"),
    ]

    resolutions = [
        (1, "fixed"),
        (2, "won't fix"),
        (3, "invalid"),
        (4, 'reorganized'),
    ]

    display = [
        "title",
        "description",
        "creator",
        "created",
        "type",
        "status",
        "resolution",
        "identifier",
    ]

    @classmethod
    def resolutions_text(cls, splitter='\n'):
        return splitter.join("(%d) %s" % pair for pair in cls.resolutions)

    @property
    def events(self):
        if not hasattr(self, "eventdata"):
            eventfiles = glob.glob("%s%s%s%s*.yaml" % (
                tkt.config.config.datapath, os.sep, self.id, os.sep))
            eventfiles = [f for f in eventfiles
                          if os.path.basename(f) != "issue.yaml"]
            self.eventdata = events = []
            for eventfile in eventfiles:
                fp = open(eventfile)
                try:
                    event = Event.load(fp)
                finally:
                    fp.close()
                event.issue = self
                events.append(event)
            events.sort()
        return self.eventdata

    def __lt__(self, other):
        return self.created < other.created

    def timezones_to_utc(self):
        self.created = tkt.timezones.to_utc(self.created)

    def timezones_to_local(self):
        self.created = tkt.timezones.to_local(self.created)

    def view_one_char(self):
        for char, status in self.statuses:
            if self.status == status:
                return char
        return "?"

    @property
    def valid_names(self):
        names = set([self.name, self.id])
        if self.name.startswith("#"):
            names.add(self.name[1:])
        return names

    def view_one_line(self):
        return "%s %s %s: %s" % (
            self.view_one_char(),
            self.type_map[self.type],
            self.name.rjust(self.longestname),
            self.title)

    def view_resolution(self):
        return self.resolution or ''

    def view_title(self):
        return self.title

    def view_description(self):
        descr = self.description.splitlines()
        if len(descr) > 1:
            return "\n> %s\n" % "\n> ".join(descr)
        return descr and descr[0] or ""

    def view_creator(self):
        return self.creator

    def view_created(self):
        return "%s ago" % tkt.flextime.since(self.created)

    def view_type(self):
        return self.type

    def view_status(self):
        return self.status

    def view_identifier(self):
        return self.id

    def view_detail(self):
        width = max(map(len, self.display)) + 4
        contents = "\n".join(
            "%s: %s" % (item.title().rjust(width),
                        getattr(self, "view_%s" % item)())
            for item in self.display
        )

        return '''Issue %s
%s
%s

Event Log:
%s''' % (self.name,
         '-' * (len(str(self.name)) + 6),
         contents,
         self.event_log())

    def event_log(self):
        return "\n".join(e.view_detail() for e in self.events)

class Project(Model):
    fields = ["name", "plugins"]

    def __init__(self, data):
        Model.__init__(self, data)

        self.plugins = self.plugins or []

    @property
    def issues(self):
        if not hasattr(self, "issuedata"):
            issuefiles = glob.glob("%s%s*%sissue.yaml" % (
                tkt.config.config.datapath, os.sep, os.sep))
            issues = []
            for issuefile in issuefiles:
                fp = open(issuefile)
                try:
                    issue = Issue.load(fp)
                finally:
                    fp.close()
                issue.project = self
                issues.append(issue)
            self.issuedata = issues

            issues.sort()
            self.assign_issue_names()

        return self.issuedata

    def assign_issue_names(self):
        longestname = len(str(len(self.issuedata)))
        for i, issue in enumerate(self.issuedata):
            self.issuedata[i].name = "#%d" % i
            self.issuedata[i].longestname = longestname
