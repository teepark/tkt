import collections
import datetime

import tkt.commands
import tkt.models


tkt.models.Issue.fields.append("labels")
tkt.models.Issue.display.append("labels")

tkt.commands.Search.options.append({
    'short': '-l',
    'long': '--label',
    'type': 'string',
    'help': 'limit to tickets with the provided label',
})
tkt.commands.Search.filters.append("label")

def filter_label(self, issue):
    if not self.parsed_options.label:
        return True
    if not issue.labels:
        return self.parsed_options.label.lower() in self.nulls
    return self.parsed_options.label.lower() in \
            [l.lower() for l in issue.labels]
tkt.commands.Search.filter_label = filter_label

def view_labels(self):
    return ", ".join(self.labels or [])
tkt.models.Issue.view_labels = view_labels

def validate_labels(self, labels):
    if not isinstance(labels, (tuple, list, type(None))):
        return False
    if labels:
        for label in labels:
            if not isinstance(label, basestring):
                return False
    return True
tkt.commands.Edit.validate_labels = validate_labels

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
            self.store_issue(data['ticket'])
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

class Unlabel(tkt.commands.Command):
    usage = "<ticket> [<label>]"

    usageinfo = "remove a label from a ticket"

    def gather_ticket(self):
        if not (self.parsed_args and self.parsed_args[0]):
            self.fail("a ticket to label is required")
        tktname = self.parsed_args[0]
        for issue in self.project.issues:
            if tktname in issue.valid_names:
                return issue
        self.fail("no ticket found with name %s" % tktname)

    def main(self):
        issue = self.gather_ticket()

        if self.parsed_args[1:]:
            label = self.parsed_args[1]
            if label not in (issue.labels or []):
                self.fail("%s doesn't have label %s" % (issue.name, label))

            issue.labels.remove(label)
        else:
            text = ["0) None (default)"]

            for i, label in enumerate(issue.labels):
                text.append("%d) %s" % (i + 1, label))

            text.append("Select a label to remove:")

            while 1:
                index = self.prompt("\n".join(text))

                if index == "" or index == "0" or index.lower() == "none":
                    label = None
                    break

                try:
                    label = issue.labels.pop(int(index) - 1)
                    break
                except:
                    continue

        if label:
            self.store_issue(issue)
            self.store_new_event(issue,
                "label '%s' removed" % label,
                datetime.datetime.now(),
                self.gather_creator(),
                self.editor_prompt("Comment"))
