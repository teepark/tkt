import os

import tkt.config


def project_filename():
    return tkt.config.project().filepath

def issue_filename(issueid):
    return os.path.join(
            tkt.config.datapath(),
            issueid,
            "issue.yaml")

def event_filename(issueid, eventid):
    return os.path.join(
            tkt.config.datapath(),
            issueid,
            "%s.yaml" % eventid)
