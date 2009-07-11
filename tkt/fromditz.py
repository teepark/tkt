import datetime
import glob
import operator
import os

import tkt.timezones
import yaml


class UTCTimestampSwitcher(object):
    def timestamps_to_local(self):
        if hasattr(self, "creation_time"):
            self.creation_time = tkt.timezones.to_local(self.creation_time)

        if isinstance(getattr(self, "log_events", 0), list):
            for group in self.log_events:
                if isinstance(group[0], datetime.datetime):
                    group[0] = tkt.timezones.to_local(group[0])

        if isinstance(getattr(self, "components", 0), list):
            for component in self.components:
                if isinstance(component, UTCTimestampSwitcher):
                    component.timestamps_to_local()

        if isinstance(getattr(self, "releases", 0), list):
            for release in self.releases:
                if isinstance(release, UTCTimestampSwitcher):
                    release.timestamps_to_local()

    def timestamps_to_utc(self):
        if hasattr(self, "creation_time"):
            self.creation_time = tkt.timezones.to_utc(self.creation_time)

        if isinstance(getattr(self, "log_events", 0), list):
            for group in self.log_events:
                if isinstance(group[0], datetime.datetime):
                    group[0] = tkt.timezones.to_utc(group[0])

        if isinstance(getattr(self, "components", 0), list):
            for component in self.components:
                if isinstance(component, UTCTimestampSwitcher):
                    component.timestamps_to_utc()

        if isinstance(getattr(self, "releases", 0), list):
            for release in self.releases:
                if isinstance(release, UTCTimestampSwitcher):
                    release.timestamps_to_utc()

class DitzProject(yaml.YAMLObject, UTCTimestampSwitcher):
    yaml_tag = u'!ditz.rubyforge.org,2008-03-06/project'

class DitzComponent(yaml.YAMLObject, UTCTimestampSwitcher):
    yaml_tag = u'!ditz.rubyforge.org,2008-03-06/component'

class DitzRelease(yaml.YAMLObject, UTCTimestampSwitcher):
    yaml_tag = u'!ditz.rubyforge.org,2008-03-06/release'

class DitzIssue(yaml.YAMLObject, UTCTimestampSwitcher):
    yaml_tag = u'!ditz.rubyforge.org,2008-03-06/issue'

def load_project(ditzdir):
    fp = open(os.path.join(ditzdir, 'project.yaml'))
    try:
        project = yaml.load(open(fp))
    finally:
        fp.close()
    project.timestamps_to_local()
    return project

def load_issues(ditzdir):
    paths = glob.glob(os.path.join(ditzdir, "issue-*.yaml"))
    issues = []
    for fp in itertools.imap(open, paths):
        try:
            issues.append(yaml.load(fp))
        finally:
            fp.close()
    map(operator.methodcaller("timestamps_to_local"), issues)

    return issues

def load_archived_issues(ditzdir):
    paths = glob.glob(os.path.join(ditzdir, "archive", "ditz-archive-*"))
    issues = []
    for path in paths:
        issues.extend(load_issues(path))
    return issues
