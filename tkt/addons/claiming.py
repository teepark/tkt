import datetime
import re

import tkt.commands
import tkt.config
import tkt.models


tkt.models.Issue.fields.append("owner")
tkt.models.Issue.display.append("owner")

def view_owner(self):
    return self.owner or "unassigned"
tkt.models.Issue.view_owner = view_owner

def validate_owner(self, owner):
    return isinstance(owner, (basestring, type(None)))
tkt.commands.Edit.validate_owner = validate_owner

class Claim(tkt.commands.Command):
    usage = "<ticket>"

    usageinfo = "take responsibility for a ticket"

    def main(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket to claim is required")
        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        issue.owner = tkt.config.config.useremail

        self.store_new_event(issue,
            "ticket claimed",
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

class Assign(tkt.commands.Command):
    usage = "<ticket> [<user's email>]"

    usageinfo = "assign a ticket to someone"

    def main(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket to assign is required")
        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        if self.parsed_args[1:]:
            user = self.parsed_args[1]
        else:
            user = self.prompt("Email of user ticket is assigned to:")

        issue.owner = user

        self.store_new_event(issue,
            "ticket assigned to %s" % user,
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

class Ownedby(tkt.commands.Command):
    usage = "<user regex>"

    usageinfo = "list the tickets owned by a particular user"

    def main(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a search string is required")
        searcher = re.compile(self.parsed_args[0])

        for issue in self.project.issues:
            if issue.owner and searcher.search(issue.owner):
                print issue.view_one_line()

class Unassign(tkt.commands.Command):
    usage = "<ticket>"

    usageinfo = "remove ticket owner"

    def main(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket to unassign is required")
        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                break
        else:
            self.fail("no ticket found with name %s" % tktname)

        issue.owner = None

        self.store_new_event(issue,
            "ticket owner removed",
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

tkt.commands.aliases("unclaim")(Unassign)

class Unassigned(tkt.commands.Command):
    usageinfo = "list tickets which have no owner"

    def main(self):
        for issue in self.project.issues:
            if not issue.owner:
                print issue.view_one_line()

tkt.commands.aliases("unclaimed")(Unassigned)
tkt.commands.aliases("unowned")(Unassigned)
