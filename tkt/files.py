import os


def project_filename():
    import tkt.config
    return os.path.join(
            tkt.config.config.datapath,
            "project.yaml")

def issue_filename(issueid):
    import tkt.config
    return os.path.join(
            tkt.config.config.datapath,
            issueid,
            "issue.yaml")

def event_filename(issueid, eventid):
    import tkt.config
    return os.path.join(
            tkt.config.config.datapath,
            issue.id,
            "%s.yaml" % eventid)
