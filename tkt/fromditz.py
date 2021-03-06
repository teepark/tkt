#!/usr/bin/env python

import datetime
import glob
import itertools
import operator
import os
import uuid

import tkt.config
import tkt.files
import tkt.models
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

class DitzThing(yaml.YAMLObject, UTCTimestampSwitcher):
    def __getattr__(self, name):
        try:
            return object.__getattribute__(self, name)
        except AttributeError:
            return object.__getattribute__(self, ":%s" % name)

class DitzProject(DitzThing):
    yaml_tag = u'!ditz.rubyforge.org,2008-03-06/project'

class DitzComponent(DitzThing):
    yaml_tag = u'!ditz.rubyforge.org,2008-03-06/component'

class DitzRelease(DitzThing):
    yaml_tag = u'!ditz.rubyforge.org,2008-03-06/release'

class DitzIssue(DitzThing):
    yaml_tag = u'!ditz.rubyforge.org,2008-03-06/issue'

class DitzLabel(DitzThing):
    yaml_tag = u'!ditz.rubyforge.org,2008-03-06/label'

def load_project(ditzdir):
    fp = open(os.path.join(ditzdir, 'project.yaml'))
    try:
        project = yaml.load(fp)
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

def main():
    import tkt.getplugins

    ditzdir = '.ditz'
    ditzproject = load_project(ditzdir)
    ditzissues = load_issues(ditzdir)
    ditzarchived = load_archived_issues(ditzdir)

    components = [c.name for c in ditzproject.components]
    releases = {}
    for release in ditzproject.releases:
        if release.release_time:
            releases[release.name] = tkt.timezones.to_local(
                    release.release_time)
        else:
            releases[release.name] = None

    tktproj = tkt.commands.Command().load_project()
    tktproj.releases = tktproj.releases or {}
    tktproj.releases.update(releases)

    fp = open(tkt.files.project_filename(), 'w')
    try:
        tktproj.dump(fp)
    finally:
        fp.close()

    issues = []
    events = {}
    now = datetime.datetime.now()
    utcnow = tkt.timezones.to_utc(now)
    for di in (ditzissues + ditzarchived):
        issue = tkt.models.Issue({
            'id': "%s-%s" % (tkt.commands.hextimestamp(di.creation_time)[:8],
                             uuid.uuid4().hex[:8]),
            'title': di.title,
            'description': di.desc,
            'type': di.type[1:],
            'component': di.component,
            'release': di.release,
            'creator': di.reporter,
            'status': di.status[1:],
            'resolution': di.disposition and di.disposition[1:] or "",
            'created': tkt.timezones.to_local(di.creation_time),
            'owner': None,
            'labels': [],
        })

        if hasattr(di, 'labels'):
            issue.labels = [l.name for l in di.labels]

        if hasattr(di, 'claimer'):
            issue.owner = di.claimer

        events[issue.id] = [tkt.models.Event({
            'id': "%s-%s" % (tkt.commands.hextimestamp(ev[0])[:8],
                             uuid.uuid4().hex[:8]),
            'title': ev[2],
            'created': tkt.timezones.to_local(ev[0]),
            'creator': ev[1],
            'comment': ev[3],
        }) for ev in di.log_events]

        user = tkt.config.user()
        events[issue.id].append(tkt.models.Event({
            'id': "%s-%s" % (tkt.commands.hextimestamp(utcnow)[:8],
                             uuid.uuid4().hex[:8]),
            'title': 'ticket imported from ditz',
            'created': now,
            'creator': "%s <%s>" % (user.username, user.useremail),
            'comment': "",
        }))

        issues.append(issue)

    for issue in issues:
        os.mkdir(os.path.dirname(tkt.files.issue_filename(issue.id)))

        for ev in events[issue.id]:
            fp = open(tkt.files.event_filename(issue.id, ev.id), 'w')
            try:
                ev.dump(fp)
            finally:
                fp.close()

        fp = open(tkt.files.issue_filename(issue.id), 'w')
        try:
            issue.dump(fp)
        finally:
            fp.close()


if __name__ == "__main__":
    main()
