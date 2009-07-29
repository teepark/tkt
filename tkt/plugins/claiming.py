import datetime
import re

import tkt.commands
import tkt.config
import tkt.models


tkt.models.Issue.fields.append("owner")
tkt.models.Issue.display.append("owner")

tkt.commands.Search.options.append({
    'short': '-o',
    'long': '--owner',
    'type': 'string',
    'help': 'the claimer/owner of the ticket',
})
tkt.commands.Search.filters.append("owner")

def view_owner(self):
    return self.owner or "unassigned"
tkt.models.Issue.view_owner = view_owner

def validate_owner(self, owner):
    return isinstance(owner, (basestring, type(None)))
tkt.commands.Edit.validate_owner = validate_owner

def filter_owner(self, issue):
    if not self.parsed_options.owner:
        return True
    if not issue.owner:
        return self.parsed_options.owner.lower() in self.nulls
    return self.parsed_options.owner.lower() in issue.owner.lower()
tkt.commands.Search.filter_owner = filter_owner

class Claim(tkt.commands.Command):
    usage = "[<ticket>]"

    usageinfo = "take responsibility for a ticket"

    def main(self):
        issue = self.gather_ticket()
        issue.owner = tkt.config.user().useremail

        self.store_issue(issue)
        self.store_new_event(issue,
            "ticket claimed",
            datetime.datetime.now(),
            self.gather_creator(),
            self.editor_prompt("Comment"))

class Assign(tkt.commands.Command):
    usage = "[<ticket>]"

    options = [{
        'short': '-u',
        'long': '--user',
        'type': 'string',
        'help': "the email address of the assigned developer",
    }]

    usageinfo = "assign a ticket to someone"

    def main(self):
        issue = self.gather_ticket()

        issue.owner = self.parsed_options.user or self.prompt(
                "E-mail of developer the ticket is assigned to:")

        self.store_issue(issue)
        self.store_new_event(issue,
            "ticket assigned to %s" % issue.owner,
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
    usage = "[<ticket>]"

    usageinfo = "remove ticket owner"

    def main(self):
        issue = self.gather_ticket()

        issue.owner = None

        self.store_issue(issue)
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
