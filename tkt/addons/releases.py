import datetime

import tkt.commands
import tkt.files
import tkt.flextime
import tkt.models


tkt.models.Issue.fields.append("release") # string, the name
tkt.models.Project.fields.append("releases") # list of dicts
tkt.models.Issue.display.append("release")

ParentProject = tkt.models.Project
class Project(ParentProject):
    def __init__(self, data):
        ParentProject.__init__(self, data)
        self.releases = self.releases or {}

tkt.models.Project = Project

ParentIssue = tkt.models.Issue
class Issue(ParentIssue):
    def view_release(self):
        return self.release

tkt.models.Issue = Issue

tkt.commands.Add.usage = "[release [<title>]]"
tkt.commands.Add.usageinfo = "creates a new ticket or release"

tkt.commands.Add.required_data.append("release")
tkt.commands.Add.options += [{
    'short': '-r',
    'long': '--release',
    'help': 'the release the ticket is assigned to',
    'type': 'string',
    'default': None,
}]

def gather_release(self):
    release = self.parsed_options.release

    if release is None and len(self.project.releases) > 0:
        text = ["Select a release for the ticket:",
                "0) None (default)"]
        releases = [k for k, v in self.project.releases.items() if not v]
        for i, release in enumerate(releases):
            text.append("%d) %s" % (i + 1, release))

        text[-1] += ":"

        while 1:
            index = self.prompt("\n".join(text))

            if index == "" or index == "0" or index.lower() == "none":
                release = None
                break

            try:
                release = releases[int(index) - 1]
                break
            except:
                continue

    return release
tkt.commands.Add.gather_release = gather_release

oldmain = tkt.commands.Add.main
def addmain(self):
    if not self.parsed_args:
        oldmain(self)
        return

    if len(self.parsed_args) > 1:
        name = self.parsed_args[1]
    else:
        name = self.prompt("Release Title:")

    if name in self.project.releases:
        self.fail("a release named '%s' already exists" % name)

    self.project.releases[name] = None

    fp = open(tkt.files.project_filename(), 'w')
    try:
        self.project.dump(fp)
    finally:
        fp.close()
tkt.commands.Add.main = addmain

tkt.commands.Drop.usageinfo = "completely purge a ticket or release from the repository"
tkt.commands.Drop.usage = "[<name>]"

def findforname(self, name):
    for release in self.project.releases:
        if release == name:
            return 1, name

    for issue in self.project.issues:
        if name in issue.valid_names:
            return 0, issue

    self.fail("no ticket found with name %s" % tktname)

olddropmain = tkt.commands.Drop.main
def dropmain(self):
    if not (self.parsed_args and self.parsed_args[0]):
        self.fail("something to drop is required")

    isrelease, item = findforname(self, self.parsed_args[0])

    if not isrelease:
        olddropmain(self)
        return

    del self.project.releases[item]

    fp = open(tkt.files.project_filename(), 'w')
    try:
        self.project.dump(fp)
    finally:
        fp.close()
tkt.commands.Drop.main = dropmain

class Release(tkt.commands.Command):
    usageinfo = "release the named release"

    usage = "<releasename>"

    def main(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("releasename argument required")

        name = self.parsed_args[0]

        releases = self.project.releases

        if name not in releases:
            self.fail("don't have a release named %s" % name)

        if releases[name]:
            self.fail("release %s was released %s ago" %
                      (name, tkt.flextime.since(releases[name])))

        releases[name] = datetime.datetime.now()

        fp = open(tkt.files.project_filename(), 'w')
        try:
            self.project.dump(fp)
        finally:
            fp.close()

class Releases(tkt.commands.Command):
    usageinfo = "show all released and planned releases"

    def main(self):
        releases = self.project.releases
        for name, released in releases.iteritems():
            if released:
                print name, "(released %s ago)" % tkt.flextime.since(released)
            else:
                print name, "(unreleased)"

class ChangeLog(tkt.commands.Command):
    usageinfo = "show all the tickets in a release"

    usage = "<releasename>"

    def main(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("releasename argument required")

        name = self.parsed_args[0]

        releases = self.project.releases

        if name not in releases:
            self.fail("don't have a release named %s" % name)

        released = releases[name]

        print "== %s / %s" % (name,
                released and release.strftime("%Y-%m-%d") or "unreleased")

        empty = True

        for issue in self.project.issues:
            if issue.release == name:
                print "* %s" % issue.title
                empty = False

        if empty:
            print "(empty milestone)"

tkt.commands.aliases('releasenotes')(ChangeLog)

class Schedule(tkt.commands.Command):
    usageinfo = "set a release for a ticket, or set it to 'None'"

    usage = "<ticket> [<release>]"

    def main(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket is required")

        tktname = self.parsed_args[0]
        releases = self.project.releases

        unreleased = [r for r in releases.keys() if not releases[r]]
        if self.parsed_args[1:]:
            release = self.parsed_args[1]

            if release not in releases:
                self.fail("don't have a release named %s" % release)

            if release not in unreleased:
                self.fail("%s was already released" % release)
        else:
            self.parsed_options.release = None
            release = gather_release(self)

        if release is not None and releases[release]:
            self.fail("%s was already released" % release)

        for issue in self.project.issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        issue.release = release

        if release:
            eventtitle = "ticket set for release '%s'" % release
        else:
            eventtitle = "ticket's scheduled release deleted"

        self.store_new_event(issue,
            eventtitle,
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

tkt.commands.aliases('assignrelease')(Schedule)
tkt.commands.aliases('setrelease')(Schedule)

def validate_release(self, release):
    return release is None or release in self.project.releases
tkt.commands.Edit.validate_release = validate_release