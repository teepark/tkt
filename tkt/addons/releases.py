import tkt.models


tkt.models.Issue.fields.append("release") # string, the name
tkt.models.Project.fields.append("releases") # list of dicts

class Project(tkt.models.Project):
    def __init__(self, data):
        super(Project, self).__init__(data)
        self.releases = self.releases or []
        self.releases = dict((d['name'], d['released']) for d in self.releases)
tkt.models.Project = Project
