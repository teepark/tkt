import sys
import traceback

import tkt.config


def getplugins():
    plugins = set(tkt.config.user().plugins + tkt.config.project().plugins)

    # we'll have to reload configs, so bust that cache
    del tkt.config._user
    del tkt.config._project

    for plugin in plugins:
        try:
            # plugins are responsible for attaching to the right hooks
            # all we do here is to import them
            __import__(plugin)
        except:
            titleline = "exception in '%s' plugin" % plugin
            print titleline
            print "-" * len(titleline)
            print "".join(traceback.format_exception(*sys.exc_info()))
