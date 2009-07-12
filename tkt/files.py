import os

import tkt.config


def project_filename():
    return os.path.join(
            tkt.config.config.datapath,
            "project.yaml")

def issue_filename(issueid):
    return os.path.join(
            tkt.config.config.datapath,
            issueid,
            "issue.yaml")

def event_filename(issueid, eventid):
    return os.path.join(
            tkt.config.config.datapath,
            issue.id,
            "%s.yaml" % eventid)
