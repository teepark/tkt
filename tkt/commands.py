import optparse
import sys

import tkt.plugins


DEFAULT = "todo"

def main():
    arg = len(sys.argv) > 1 and sys.argv[1] or DEFAULT
    cmd = Command.cmds.get(arg)
    if cmd is None:
        print "unknown tkt command %s" % arg
        sys.exit(1)
    cmd().main()

def aliases(*names):
    def decorator(cls):
        for name in names:
            globals[name.title()] = cls
        return cls
    return decorator

class CommandTracker(type):
    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, 'cmds'):
            cls.cmds = {}
        else:
            cls.cmds[cls.__name__.lower()] = cls

class Command(object):
    __metaclass__ = CommandTracker

    options = []
    usage = ""
    argv = sys.argv[2:]

    def main(self):
        raise NotImplementedError()

    @property
    def options(self):
        if not hasattr(self, "_options_args"):
            self._options_args = self.build_parser().parse_args(sys.argv)
        return self._options_args[0]

    @property
    def args(self):
        if not hasattr(self, "_options_args"):
            self._options_args = self.build_parser().parse_args(self.argv)
        return self._options_args[1]

    def build_parser(self):
        parser = optparse.OptionParser()

        for opt in self.options:
            short = opt.get("short")
            long = opt.get("long")
            kwargs = {}

            type = opt.get("type")
            if type is None:
                kwargs["action"] = "store_true"
            else:
                kwargs["type"] = type
                kwargs["action"] = "store"

            kwargs["default"] = opt.get("default")

            help = opt.get("help")
            if help: kwargs["help"] = help

            parser.add_option(short, long, **kwargs)

        parser.usage = "tkt %s %s [options]" % (
                self.__class__.__name__.lower(), self.usage)

        return parser
