import datetime

import tkt.commands
import tkt.files
import tkt.models


tkt.models.Issue.fields.append("dependencies")
tkt.models.Issue.display.append("dependencies")

def validate_dependencies(self, deps):
    depset = set(deps or [])
    if len(deps) > len(depset):
        return False
    if set(i.id for i in self.project.issues) < depset:
        return False
    for issue in self.project.issues:
        try:
            # not the most efficient way of finding cyclic dependencies
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
    if other in self.deps:
        return False
    if self in other.deps:
        return True
    return oldlt(self, other)
tkt.models.Issue.__lt__ = lessthan

def listissues(self):
    if not hasattr(self, "issuedata"):
        issues = []
        for issueid in self.issueids or []:
            fp = open(tkt.files.issue_filename(issueid))
            try:
                issue = tkt.models.Issue.load(fp)
                issue.project = self
                issues.append(issue)
            finally:
                fp.close()
        self.issuedata = issues

        for issue in issues:
            issue.deps = get_dependencies(issue, 0)

        tkt.models.Issue.__lt__ = oldlt
        issues.sort()
        self.assign_issue_names()

        tkt.models.Issue.__lt__ = lessthan
        issues.sort()

    return self.issuedata
tkt.models.Project.issues = property(listissues)

class Depend(tkt.commands.Command):
    usage = "<ticket> [<dependency>]"

    usageinfo = "note that one ticket depends on another"

    def main(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket set a dependency for is required")

        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        if self.parsed_args[1:]: # [<dependency>] provided
            tktname = self.parsed_args[1]
            for otherissue in self.project.issues:
                if tktname in otherissue.valid_names:
                    break
            else:
                self.fail("no ticket found with name %s" % tktname)
        else:
            while 1:
                tktname = self.prompt("ticket %s depends on:" % issue.name)
                for otherissue in self.project.issues:
                    if tktname in otherissue.valid_names:
                        break
                else:
                    sys.stderr.write("no ticket found with name %s\n" % tktname)
                    continue
                break

        if issue.id == otherissue.id:
            self.fail("an issue can't depend on itself")

        if not issue.dependencies:
            issue.dependencies = []
        issue.dependencies.append(otherissue.id)

        self.store_new_event(issue,
            "dependency on %s added" % otherissue.name,
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))
