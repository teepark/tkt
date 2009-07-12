import tkt.models
import yaml


_path = tkt.models.Configuration.rcfile()

config = tkt.models.Configuration.load(open(_path))
