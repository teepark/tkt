import bisect
import datetime
import os
import uuid

import tkt.commands
import tkt.files
import tkt.models


# add fields
tkt.models.Issue.fields.append("component")
tkt.models.Project.fields.append("components")

ParentProject = tkt.models.Project
class Project(tkt.models.Project):
    def __init__(self, *args, **kwargs):
        ParentProject.__init__(self, *args, **kwargs)
        self.components = self.components or []

    def assign_issue_names(self):
        componentcounts = {}

        for issue in self.issues:
            if not issue.component:
                if len(self.components or []) == 1:
                    issue.component = self.components
                else:
                    issue.component = self.name

            count = componentcounts.setdefault(issue.component, 0)
            componentcounts[issue.component] += 1

            issue.name = "%s-%d" % (issue.component, count)

        longest = self.issues and max(len(i.name) for i in self.issues) or 0
        for issue in self.issues:
            issue.longestname = longest

tkt.models.Project = Project

class Add(tkt.commands.Add):
    options = tkt.commands.Add.options + [{
        'short': '-c',
        'long': '--component',
        'help': 'the component for this ticket',
        'type': 'string',
    }]

    def get_component(self):
        if not self.project.components:
            return self.project.name

        if len(self.project.components) == 1:
            return self.project.components[0]

        if self.parsed_options.component in self.project.components:
            return self.parsed_options.component

        msg = "Pick a component\n[0]) %s" % self.project.components[0]
        msg += "".join("\n%d) %s" % p for p
                       in list(enumerate(self.project.components))[1:])

        while 1:
            index = self.prompt(msg + ":")
            if index.isdigit():
                index = int(index)
            if 0 <= int(index) < len(self.project.components):
                return self.project.components[index]

    def get_data(self):
        title, type, description, username = super(Add, self).get_data()

        component = self.get_component()

        return title, type, description, username, component

    def store_new_issue(self, title, type, description, user, component):
        # almost cut'n pasted from the original
        issue = tkt.models.Issue({
            'id': uuid.uuid4().hex,
            'title': title,
            'description': description,
            'created': datetime.datetime.now(),
            'type': dict(tkt.models.Issue.types)[type],
            'status': 'open',
            'resolution': None,
            'creator': user,
            'events': [],
            'component': component})

        bisect.insort(self.project.issues, issue)

        issuepath = tkt.files.issue_filename(issue.id)
        issuedir = os.path.abspath(os.path.join(issuepath, os.pardir))

        if not os.path.exists(issuedir):
            os.makedirs(issuedir)

        fp = open(tkt.files.project_filename(), 'w')
        try:
            self.project.dump(fp)
        finally:
            fp.close()

        # this dumps the issue too
        self.store_new_event(issue, "issue created", issue.created, user, "")

        return issue

tkt.commands.aliases("new")(Add)

class Status(tkt.commands.Status):
    usage = "[component]"

    def main(self):
        if self.parsed_args:
            component = self.parsed_args[0]
            if component in self.project.components:
                self.display_status([i for i in self.project.issues
                                     if i.component == component])
            else:
                self.fail("%s is not a recognized component" % component)
        else:
            super(Status, self).main()

class Component(tkt.commands.Command):
    usage = "ticket component"

    usageinfo = "set the component of a ticket"

    def main(self):
        if not (self.parsed_args and len(self.parsed_args) > 1 and \
                self.parsed_args[0] and self.parsed_args[1]):
            self.fail("a ticket and component are required")

        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        component = issue.component = self.parsed_args[1]
        if component not in self.project.components:
            self.project.components.append(component)
            fp = open(tkt.files.project_filename(), 'w')
            try:
                self.project.dump(fp)
            finally:
                fp.close()

        fp = open(tkt.files.issue_filename(issue.id), 'w')
        try:
            issue.dump(fp)
        finally:
            fp.close()

class Edit(tkt.commands.Edit):
    def validate_component(self, component):
        return isinstance(component, basestring)
