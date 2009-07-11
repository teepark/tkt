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
