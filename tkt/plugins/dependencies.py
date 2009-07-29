import datetime

import tkt.commands
import tkt.files
import tkt.models


tkt.models.Issue.fields.append("dependencies")
tkt.models.Issue.display.append("dependencies")

tkt.commands.Search.options.append({
    'short': '-p',
    'long': '--dependency',
    'type': 'string',
    'help': 'limit to tickets which depend on the provided ticket',
})
tkt.commands.Search.filters.append("dependency")

def filter_dependency(self, issue):
    if not self.parsed_options.dependency:
        return True
    if not issue.dependencies:
        return self.parsed_options.dependency.lower() in self.nulls
    for iss in self.project.issues:
        if self.parsed_options.dependency.lower() in iss.valid_names:
            break
    else:
        self.fail("not a valid issue name: %s" %
                self.parsed_options.dependency)

    if not hasattr(issue, 'deps'):
        issue.deps = get_dependencies(issue)

    return iss in issue.deps
tkt.commands.Search.filter_dependency = filter_dependency

def validate_dependencies(self, deps):
    deps = deps or []
    depset = set(deps)
    if len(deps) > len(depset):
        return False
    if set(i.id for i in self.project.issues) < depset:
        return False
    for issue in self.project.issues:
        try:
            # not the most efficient way of finding cyclic dependencies...
            get_dependencies(issue)
        except RuntimeError:
            return False
    return True
tkt.commands.Edit.validate_dependencies = validate_dependencies

def get_dependencies(self, sort=True):
    dep_issues = set()
    depids = set(self.dependencies or [])
    for issue in self.project.issues:
        if not depids:
            break
        if issue.id in depids:
            depids.discard(issue.id)
            dep_issues.add(issue)
            dep_issues.update(get_dependencies(issue))

    if not sort:
        return dep_issues

    return sorted(dep_issues)

def view_dependencies(self):
    return ", ".join(d.name for d in get_dependencies(self))

tkt.models.Issue.view_dependencies = view_dependencies

oldlt = tkt.models.Issue.__lt__
def lessthan(self, other):
    "monkeypatch Issue.__lt__ so that ticket sorting considers dependencies"
    if (hasattr(self, 'deps') and hasattr(other, 'deps')):
        if other in self.deps:
            return False

        if self in other.deps:
            return True

    return oldlt(self, other)

tkt.models.ProjectConfig._oldissues = tkt.models.ProjectConfig.issues
def listissues(self):
    issuelist = self._oldissues
    if not hasattr(self, "_issues_dependency_sorted"):
        self._issues_dependency_sorted = 1

        for issue in issuelist:
            issue.deps = get_dependencies(issue, 0)

        tkt.models.Issue.__lt__ = lessthan
        issuelist.sort()

    return issuelist
tkt.models.ProjectConfig.issues = property(listissues)

class Depend(tkt.commands.Command):
    usage = "<ticket> [<dependency>]"

    usageinfo = "note that one ticket depends on another"

    def main(self):
        issue = self.gather_ticket(try_prompting=False)

        self.parsed_args.pop(0)

        otherissue = self.gather_ticket(
                prompt="Ticket %s depends on:" % issue.name)

        if issue.id == otherissue.id:
            self.fail("an issue can't depend on itself")

        if not issue.dependencies:
            issue.dependencies = []
        issue.dependencies.append(otherissue.id)
        issue.deps.add(otherissue)

        try:
            issue.deps.update(get_dependencies(otherissue))
            get_dependencies(issue)
        except RuntimeError:
            self.fail("no cyclic dependencies")

        self.store_issue(issue)
        self.store_new_event(issue,
            "dependency on %s added" % otherissue.id,
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

tkt.commands.aliases('dependency', 'depends')(Depend)

oldstartmain = tkt.commands.Start.main
def startmain(self):
    issue = self.gather_ticket()
    self.gather_ticket = lambda: issue

    if not hasattr(issue, 'deps'):
        issue.deps = get_dependencies(issue)

    opendeps = [d for d in issue.deps if d.status != tkt.models.Issue.CLOSED]
    opendeps = [d for d in opendeps if d.id in (issue.dependencies or [])]
    if opendeps:
        if opendeps[1:]:
            print "Ticket has open dependencies %s" % \
                    ", ".join(d.name for d in opendeps)
        else:
            print "Ticket has open dependency %s" % opendeps[0].name
        response = self.prompt("Start this ticket anyway? [y/N]")

        if not response or response[0].lower() != 'y':
            return

    oldstartmain(self)

tkt.commands.Start.main = startmain

oldclosemain = tkt.commands.Close.main
def closemain(self):
    issue = self.gather_ticket()
    self.gather_ticket = lambda: issue

    if not hasattr(issue, 'deps'):
        issue.deps = get_dependencies(issue)

    opendeps = [d for d in issue.deps if d.status != tkt.models.Issue.CLOSED]
    opendeps = [d for d in opendeps if d.id in (issue.dependencies or [])]
    if opendeps:
        if opendeps[1:]:
            print "Ticket has open dependencies %s" % \
                    ", ".join(d.name for d in opendeps)
        else:
            print "Ticket has open dependency %s" % opendeps[0].name
        response = self.prompt("Close this ticket and remove open " +
                               "depenencies? [y/N]")

        if not response or response[0].lower() != 'y':
            return

    if issue.dependencies:
        for baddep in opendeps:
            issue.dependencies.remove(baddep.id)

    oldclosemain(self)

tkt.commands.Close.main = closemain

oldqamain = tkt.commands.QA.main
def qamain(self):
    issue = self.gather_ticket()
    self.gather_ticket = lambda: issue

    opendeps = [d for d in issue.deps if d.status != tkt.models.Issue.CLOSED]
    opendeps = [d for d in opendeps if d.id in (issue.dependencies or [])]
    if opendeps:
        if opendeps[1:]:
            print "Ticket has open dependencies %s" % \
                    ", ".join(d.name for d in opendeps)
        else:
            print "Ticket has open dependency %s" % opendeps[0].name
        response = self.prompt("Send this ticket to QA anyway? [y/N]")

        if not response or response[0].lower() != 'y':
            return

    oldqamain(self)

tkt.commands.QA.main = qamain

olddropmain = tkt.commands.Drop.main
def dropmain(self):
    issue = self.gather_ticket()
    self.gather_ticket = lambda: issue

    for otherissue in self.project.issues:
        if issue.id in (otherissue.dependencies or []):
            otherissue.dependencies.remove(issue.id)
            otherissue.deps = get_dependencies(otherissue)
            fp = open(tkt.files.issue_filename(otherissue.id), 'w')
            try:
                otherissue.dump(fp)
            finally:
                fp.close()

    olddropmain(self)

tkt.commands.Drop.main = dropmain

oldpointthreeupgrade = tkt.commands.Upgrade.point_three_upgrade
def point_three_upgrade(self):
    oldpointthreeupgrade(self)
    for issue in self.project.issues:
        if issue.dependencies:
            issue.dependencies = map(self.issue_id_map.get, issue.dependencies)
        self.store_issue(issue)
tkt.commands.Upgrade.upgrades['0.3'] = point_three_upgrade
