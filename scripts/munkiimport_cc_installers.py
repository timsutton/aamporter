#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Tool to call 'munkiimport' against a set of Adobe Creative Cloud installers
# built from CCP.
# Requires at least Munki tools 2.1.0.2322, which has initial, explicit support
# for CCP installers and uninstallers.
#
# You may customize options passed to munkiimport using the constant
# 'MUNKIIMPORT_OPTIONS' defined below. Please note that the following
# options will be added automatically later in the script:
# --nointeractive
# --uninstallerpkg (along with the path to the item's matching installer)
#
# Expects a single argument: a folder containing one or more folders
# of output CCP package builds. For example:
#
# ./munkiimport_cc_installers.py MyCCPackages
#
# MyCCPackages hierarchy:
# .
# ├── AdobeAfterEffectsCC2014
# │   ├── AdobeAfterEffectsCC2014.ccp
# │   ├── Build
# │   │   ├── AdobeAfterEffectsCC2014_Install.pkg
# │   │   └── AdobeAfterEffectsCC2014_Uninstall.pkg
# │   └── Exceptions
# ├── AdobeAuditionCC2014
# │   ├── AdobeAuditionCC2014.ccp
# │   ├── Build
# │   │   ├── AdobeAuditionCC2014_Install.pkg
# │   │   └── AdobeAuditionCC2014_Uninstall.pkg
# │   └── Exceptions

import os
import subprocess
import sys

from glob import glob

MUNKIIMPORT_OPTIONS = [
    "--subdirectory", "apps/Adobe/CC/2014",
    "--developer", "Adobe",
    "--category", "Creativity",
]


if len(sys.argv) < 2:
    sys.exit("This script requires a single argument. See the script comments.")

PKGS_DIR = sys.argv[1]
PKGS_DIR = os.path.abspath(PKGS_DIR)

for product in os.listdir(PKGS_DIR):
    if not os.path.isdir(product):
        continue
    install_pkg_path = glob(os.path.join(product, "Build/*Install.pkg"))[0]
    uninstall_pkg_path = glob(os.path.join(product, "Build/*Uninstall.pkg"))[0]
    cmd = [
        "/usr/local/munki/munkiimport",
        "--nointeractive",
        ]
    cmd += MUNKIIMPORT_OPTIONS
    cmd += ["--uninstallerpkg", uninstall_pkg_path]
    cmd.append(install_pkg_path)
    subprocess.call(cmd)
