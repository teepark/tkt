import os

import tkt.models
import yaml


DATAFOLDERNAME = '.tkt'

def user():
    if '_user' not in globals():
        path, exists = tkt.models.UserConfig.findpath()
        if exists:
            user = tkt.models.UserConfig.loadfile(path)
        else:
            user = tkt.models.UserConfig({})
        user.filepath = path
        globals()['_user'] = user

    return globals()['_user']

def project():
    if '_project' not in globals():
        path, exists = tkt.models.ProjectConfig.findpath()
        if exists:
            project = tkt.models.ProjectConfig.loadfile(path)
        else:
            project = tkt.models.ProjectConfig({})
        project.filepath = path
        globals()['_project'] = project

    return globals()['_project']

def datapath():
    return os.path.dirname(project().filepath)
