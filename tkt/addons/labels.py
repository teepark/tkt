import collections
import datetime

import tkt.commands
import tkt.models


tkt.models.Issue.fields.append("labels")
tkt.models.Issue.display.append("labels")

def view_labels(self):
    if self.labels:
        return "\n" + "\n".join("- %s" % l for l in self.labels or [])
    return ""
tkt.models.Issue.view_labels = view_labels

class Label(tkt.commands.Command):
    usage = "<ticket> [<label>]"

    usageinfo = "mark a ticket with a label"

    required_data = ["ticket", "label"]

    def gather_ticket(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket to label is required")
        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                return issue
        self.fail("no ticket found with name %s" % tktname)

    def gather_label(self):
        if self.parsed_args[1:]:
            return self.parsed_args[1]

        return self.prompt("Label:")

    def main(self):
        data = self.gather()

        labellist = data['ticket'].labels
        if not labellist:
            data['ticket'].labels = labellist = []
        label = data['label']

        if label not in labellist:
            labellist.append(label)
            print data['ticket'].labels
            self.store_new_event(data['ticket'],
                "ticket labeled with '%s'" % label,
                datetime.datetime.now(),
                self.gather_creator(),
                self.editor_prompt("Comment"))

class Labeled(tkt.commands.Command):
    usage = "[<label>]"

    usageinfo = "show the tickets with a particular label, or any labels"

    def main(self):
        if not self.parsed_args:
            self.display_all_labeled()
        else:
            label = self.parsed_args[0]
            for issue in self.project.issues:
                if label in (issue.labels or []):
                    print issue.view_one_line()

    def display_all_labeled(self):
        data = collections.defaultdict(list)
        for issue in self.project.issues:
            for label in (issue.labels or []):
                data[label].append(issue)

        for label, issues in data.iteritems():
            print "%s\n  %s" % (label, "\n  ".join(
                i.view_one_line() for i in issues))
