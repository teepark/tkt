import os
import stat
import subprocess

import tkt.files
import tkt.timezones
import yaml


class Model(object):
    def __init__(self, data):
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
        data = dict(zip(self.fields, map(self.__getattr__, self.fields)))
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

class Configuration(Model):
    fields = ['username', 'useremail', 'datafolder']

    RCFILENAME = '.tktrc.yaml'
    DEFAULT_DATAFOLDER = '.tkt'

    def __init__(self, data):
        super(Configuration, self).__init__(data)
        for fieldname in self.fields:
            if not getattr(self, fieldname):
                setattr(self, fieldname,
                        getattr(self, "default_%s" % fieldname)())

    @classmethod
    def _find(cls, name):
        path = os.path.abspath(os.curdir)
        parentpath = os.path.abspath(os.path.join(path, os.pardir))

        rcpath = os.path.join(path, name)
        if os.path.exists(rcpath):
            return rcpath, True

        # the theory is that once we reach the root, the parent folder's path
        # is the same as the current folder's path
        while path != parentpath:
            path = parentpath
            parentpath = os.path.abspath(os.path.join(path, os.pardir))

            rcpath = os.path.join(path, name)
            if os.path.exists(rcpath):
                return rcpath, True

        homedir = os.environ.get('HOME')
        if not homedir:
            raise RuntimeError("no %s or HOME directory found" % name)

        rcpath = os.path.abspath(os.path.join(homedir, name))
        return rcpath, os.path.exists(rcpath)

    @classmethod
    def rcfile(cls):
        rcfile, present = cls._find(cls.RCFILENAME)
        if not present:
            os.mknod(rcfile, 0644, stat.S_IFREG)
        return rcfile

    @property
    def datapath(self):
        if not hasattr(self, "_datapath"):
            rc, present = cls._find(self.datafolder)
            if not present:
                os.mkdir(rc)
            self._datapath = rc
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

class Issue(Model):
    fields = [
        "id",
        "title",
        "description",
        "creationtime",
        "type",
        "status",
        "resolution",
        "creator",
        "events",
    ]

    def timezones_to_utc(self):
        this.creationtime = tkt.timezones.to_utc(this.creationtime)

    def timezones_to_local(self):
        this.creationtime = tkt.timezones.to_local(this.creationtime)

class Project(Model):
    fields = ["name", "issues"]

    def __init__(self, data):
        super(Project, self).__init__(data)

    @classmethod
    def load(cls, stream):
        super(Project, cls).load(stream)
        self.issues = [Issue.load(tkt.files.filename('issue', i['id']))
                       for i in self.issues]

    def dump(self, stream=None):
        fullissues = self.issues
        self.issues = [i.id for i in fullissues]
        data = super(Project, self).dump(stream)
        self.issues = fullissues
        return data
