import functools
import glob
import itertools
import os
import platform

import tkt.config
import tkt.flextime
import tkt.timezones
import tkt.utils
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

    @classmethod
    def loadfile(cls, filename):
        fp = open(filename)
        try:
            return cls.load(fp)
        finally:
            fp.close()

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

class UserConfig(Model):
    fields = ['username', 'useremail', 'plugins']

    RCFILENAME = '.tktrc.yaml'

    def __init__(self, data):
        Model.__init__(self, data)

        self.plugins = self.plugins or []
        self.username = self.username or self.default_username()
        self.useremail = self.useremail or self.default_useremail()

    @classmethod
    def findpath(cls):
        if 'HOME' in os.environ:
            path = os.path.join(os.environ['HOME'], cls.RCFILENAME)
            return path, os.path.isfile(path)

        here = os.path.abspath('.')
        path = os.path.join(here, cls.RCFILENAME)
        parent = os.path.dirname(here)

        if os.path.isfile(path):
            return path, True

        while here != parent:
            here = parent
            parent = os.path.dirname(here)
            if os.path.isfile(path):
                return path, True

        return os.path.join(os.path.abspath('.'), cls.RCFILENAME), False

    def default_username(self):
        return (os.environ.get('USER') or 'anonymous user').title()

    def default_useremail(self):
        if not hasattr(self, 'username'):
            self.username = self.default_username()
        hostname = platform.uname()[1]
        return "%s@%s" % (self.username.lower().replace(" ", "."), hostname)

class ProjectConfig(Model):
    fields = ['plugins']

    RCFILENAME = 'project.yaml'

    def __init__(self, data):
        Model.__init__(self, data)
        self.plugins = self.plugins or []

    @classmethod
    def findpath(cls):
        subpath = os.path.join(tkt.config.DATAFOLDERNAME, cls.RCFILENAME)

        here = os.path.abspath('.')
        path = os.path.join(here, subpath)
        parent = os.path.dirname(here)

        if os.path.isfile(path):
            return path, True

        while here != parent:
            here = parent
            path = os.path.join(here, subpath)
            parent = os.path.dirname(here)

            if os.path.isfile(path):
                return path, True

        return os.path.join(os.path.abspath('.'), tkt.config.DATAFOLDERNAME,
                            cls.RCFILENAME), False

    def _load_issue(self, number, filename):
        issue = Issue.loadfile(filename)
        issue.project = self
        issue.name = "#%d" % number
        issue.__class__.longestname = max(len(issue.name),
                                          issue.__class__.longestname)
        return issue

    @property
    def issue_filenames(self):
        if not hasattr(self, "_issue_filenames"):
            self._issue_filenames = names = glob.glob("%s%s*%sissue.yaml" % (
                    tkt.config.datapath(), os.sep, os.sep))
            names.sort()
        return self._issue_filenames

    @property
    def issues(self):
        if not hasattr(self, "issuedata"):
            issuefiles = self.issue_filenames
            self.issuedata = tkt.utils.LazyLoadingList(itertools.starmap(
                self._load_issue, enumerate(issuefiles)))
        return self.issuedata

class OverallConfig(object):
    def __init__(self, user, project):
        self.user = user
        self.project = project

    @property
    def username(self):
        return self.user.username

    @property
    def useremail(self):
        return self.user.useremail

    @property
    def plugins(self):
        allplugs = self.user.plugins + self.project.plugins
        return sorted(set(allplugs), key=allplugs.index)

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

    longestname = 0

    @classmethod
    def resolutions_text(cls, splitter='\n'):
        return splitter.join("(%d) %s" % pair for pair in cls.resolutions)

    def _load_event(self, filename):
        event = Event.loadfile(filename)
        event.issue = self
        return event

    @property
    def events(self):
        if not hasattr(self, "eventdata"):
            eventfiles = glob.glob("%s%s%s%s*.yaml" % (
                tkt.config.datapath(), os.sep, self.id, os.sep))
            eventfiles = [f for f in eventfiles
                          if os.path.basename(f) != "issue.yaml"]
            eventfiles.sort()
            self.eventdata = tkt.utils.LazyLoadingList(
                    itertools.imap(self._load_event, eventfiles))
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
