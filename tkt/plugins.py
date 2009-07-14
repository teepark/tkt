import tkt.config

for plugin in tkt.config.config.plugins:
    try:
        # plugins are responsible for attaching to the right hooks
        # all we do here is to import them
        __import__(plugin)
    except:
        pass
