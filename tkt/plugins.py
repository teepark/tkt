import sys
import traceback

import tkt.config

for plugin in tkt.config.config.plugins:
    try:
        # plugins are responsible for attaching to the right hooks
        # all we do here is to import them
        __import__(plugin)
    except:
        titleline = "exception in '%s' plugin" % plugin
        print titleline
        print "-" * len(titleline)
        print "".join(traceback.format_exception(*sys.exc_info()))
