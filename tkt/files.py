import os

import tkt.config


def filename(objtype, id):
    return os.path.join(tkt.config.datapath, "%s-%s.yaml" % (objtype, id))
