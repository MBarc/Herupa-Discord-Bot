import yaml
import os
from pathlib import Path


def configFile():

    configPath = Path(Path(os.path.abspath(os.path.dirname(__file__))).absolute(), "config.yml")
    with open(configPath, "r") as ymlfile:
        config = yaml.load(ymlfile, yaml.FullLoader)

    return config


