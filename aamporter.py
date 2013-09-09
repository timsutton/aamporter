#!/usr/bin/python
#
# aamporter.py
# Tim Sutton
#
# Utility to download AAM 2.0 and higher (read: CS5 and up) updates from Adobe's updater feed.
# Optionally import them into a Munki repo, assuming munkiimport is already configured.
#
# See README.md for more information.

import os
import sys
import urllib
from urlparse import urljoin
import plistlib
import re
from collections import namedtuple
from xml.etree import ElementTree as ET
import optparse
import subprocess
import sqlite3
import logging

SCRIPT_DIR = os.path.abspath(os.path.dirname(sys.argv[0]))
DEFAULT_PREFS = {
    'munki_pkginfo_name_suffix': '_Update',
    'munki_repo_destination_path': 'apps/Adobe/CS_Updates',
    'munkiimport_options': [],
    'local_cache_path': os.path.join(SCRIPT_DIR, 'aamcache'),
    'munki_tool': 'munkiimport'
}
settings_plist = os.path.join(SCRIPT_DIR, 'aamporter.plist')
supported_settings_keys = DEFAULT_PREFS.keys()
supported_settings_keys.append('aam_server_baseurl')
UpdateMeta = namedtuple('update', ['channel', 'product', 'version', 'revoked', 'xml'])
UPDATE_PATH_PREFIX = 'updates/oobe/aam20/mac'
MUNKI_DIR = '/usr/local/munki'
ERROR = 50
WARNING = 40
INFO = 30
VERBOSE = 20
DEBUG = 10


class ColorFormatter(logging.Formatter):
    # http://ascii-table.com/ansi-escape-sequences.php
    BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)
    RESET_SEQ = "\033[0m"
    COLOR_SEQ = "\033[0;%dm"
    COLORS = {'DEBUG': MAGENTA,
              'VERBOSE': GREEN,
              'INFO': BLUE,
              'WARNING': YELLOW,
              'ERROR': RED}
    LEVELS = {10: 'DEBUG', 20: 'VERBOSE', 30: 'INFO', 40: 'WARNING', 50: 'ERROR'}

    def __init__(self, use_color=True, fmt="%(message)s"):
        logging.Formatter.__init__(self)
        self.use_color = use_color

    def format(self, record):
        # Code to prepend level name to log message
        # if record.levelno != 40:
        #     message = "%s: %s" % (self.LEVELS[record.levelno], record.getMessage())
        # else:
        #     message = record.getMessage()
        # record.message = message
        record.message = record.getMessage()
        s = self._fmt % record.__dict__
        if self.use_color:
            if record.levelno != 30:
                color = 30 + self.COLORS[self.LEVELS[record.levelno]]
                s = self.COLOR_SEQ % color + s + self.RESET_SEQ
        return s


def errorExit(err_string, err_code=1):
    L.log(ERROR, err_string)
    sys.exit(err_code)


def pref(name):
    p = {}
    if os.path.exists(settings_plist):
        p = plistlib.readPlist(settings_plist)
    if name in DEFAULT_PREFS.keys() and not name in p.keys():
        value = DEFAULT_PREFS[name]
    elif name in p.keys():
        value = p[name]
    else:
        value = None
    return value


def getURL(type='updates'):
    if pref('aam_server_baseurl'):
        return pref('aam_server_baseurl')
    else:
        if type == 'updates':
            return 'http://swupdl.adobe.com'
        elif type == 'webfeed':
            return 'http://swupmf.adobe.com'


def getFeedData():
    url = urljoin(getURL(type='webfeed'), 'webfeed/oobe/aam20/mac/updaterfeed.xml')
    try:
        opener = urllib.urlopen(url)
    except BaseException as e:
        L.log(ERROR, "Error reading feed data from URL: %s" % url)
        errorExit(e)

    xml = opener.read()
    opener.close()
    search = re.compile("<(.+?)>")
    results = re.findall(search, xml)
    return results


def parseFeedData(feed_list):
    updates = []
    for update in feed_list:
        # skip COMBOs (language packs?)
        if not update.startswith('COMBO'):
            cmpnts = update.split(',')
            ver = cmpnts[-1]     # version: last
            prod = cmpnts[-2]     # product: 2nd last
            chan = cmpnts[-3]     # channel: 3rd last
            if cmpnts[0] != "REVOKE":
                revoked = False
            else:
                revoked = True
            L.log(DEBUG, "Parsed: Channel: {0}, Product: {1}, Version: {2}, Revoked: {3}".format(
                chan, prod, ver, revoked))
            updates.append(UpdateMeta(channel=chan, product=prod, version=ver, revoked=revoked, xml=None))
    return updates


def getChannelsFromProductPlists(products):
    """Takes a list of product plist objects and returns a dict of
    channels and what each is an update_for."""
    channels = {}
    for product in products:
        for channel in product['channels']:
            if not channel in channels.keys():
                channels[channel] = {}
                channels[channel]['munki_update_for'] = []
            if 'munki_update_for' in product.keys():
                channels[channel]['munki_update_for'].append(product['munki_update_for'])
            if 'munki_repo_destination_path' in product.keys():
                channels[channel]['munki_repo_destination_path'] = product['munki_repo_destination_path']
    return channels


def getUpdatesForChannel(channel_id, parsed_feed):
    updates = []
    for update in parsed_feed:
        if update.channel == channel_id:
            updates.append(update)
    if not len(updates):
        updates = None
    return updates


def addUpdatesXML(updates, skipTargetLicensingCC=True):
    """Takes a list of UpdateMeta objects and adds an ElementTree object
    with the root of the contents of the update's metadata XML.

    Also, when skipTargetLicensingCC is True, remove any updates
    with TargetLicensingType of '1'. Further explanation:

    TargetLicensingType seems to be 1 for CC updates, 2 for older CS suite updates
    Note: These started showing up between when CS6 was released and when
    the first suite of new Creative Cloud versions were released a year later.
    They seem to be all essentially "point one" minor feature updates versions.

    Originally, they seemed to be a limited set of updates for CS6 suite apps that
    were only available to CC customers. These updates wouldn't be offered by RUM.
    New CC products (ie. Photoshop 14) didn't have this TargetLicensingType.

    However, a new set of CC updates released around late August/early
    September 2013 have this property and will install with RUM.
    At this point, we're skipping them but we need have another mechanism to
    properly discern which can be installed.
    """
    new_updates = []
    for update in updates:
        details_url = urljoin(getURL('updates'), UPDATE_PATH_PREFIX) + \
        '/%s/%s/%s.xml' % (update.product, update.version, update.version)
        try:
            channel_xml = urllib.urlopen(details_url)
        except BaseException as e:
            L.log(DEBUG, "Couldn't read details XML at %s" % details_url)
            L.log(DEBUG, e)
            continue

        try:
            details_xml = ET.fromstring(channel_xml.read())
        except ET.ParseError as e:
            L.log(DEBUG, "Couldn't parse XML: %s" % e)
            continue

        if skipTargetLicensingCC:
            licensing_type_elem = details_xml.find('TargetLicensingType')
            if licensing_type_elem is not None:
                if licensing_type_elem.text == '1':
                    L.log(DEBUG, "TargetLicensingType of %s found. This seems to be Creative Cloud updates. "
                        "Skipping update." % licensing_type_elem.text)
                    continue

        if details_xml is not None:
            new_update = UpdateMeta(
                channel=update.channel,
                product=update.product,
                version=update.version,
                revoked=update.revoked,
                xml=details_xml)
            new_updates.append(new_update)
    return new_updates


def updateIsRevoked(channel, product, version, parsed_feed):
    """Returns True if an update is considered revoked for a channel.

    Deduced revocation logic:

    An update can be listed multiple times, and both with and without
    'REVOKE,[channel]' or 'REVOKE,ALL' lines. It seems an update is
    only eligible if it has appeared _more times_ than a line with
    REVOKE.

    Therefore, to determine whether an update is REVOKE'd, we maintain a
    counter and declare it revoked only if there are fewer REVOKE lines
    than non-REVOKE lines.

    A couple samples of feed entries, in order of appearance in the webfeed,
    September 9, 2013, below.

    AdobePremiereProCS6-6.0.0-Trial:
    - when 6.0.2 was the most recent update being offered, it appeared three
      times in the feed, but only once as REVOKE,ALL
    - when it was surpassed by 6.0.3, a second REVOKE line was added

    curl -s http://swupmf.adobe.com/webfeed/oobe/aam20/mac/updaterfeed.xml | grep AdobePremiereProCS6-6.0.0-Trial

    <REVOKE,ALL,AdobePremiereProCS6-6.0.0-Trial,6.0.4>
    <AdobePremiereProCS6-6.0.0-Trial,AdobePremiereProCS6-6.0.0-Trial,6.0.5>
    <REVOKE,ALL,AdobePremiereProCS6-6.0.0-Trial,6.0.2>
    <AdobePremiereProCS6-6.0.0-Trial,AdobePremiereProCS6-6.0.0-Trial,6.0.4>
    <AdobePremiereProCS6-6.0.0-Trial,AdobePremiereProCS6-6.0.0-Trial,6.0.2>
    <REVOKE,ALL,AdobePremiereProCS6-6.0.0-Trial,6.0.2>
    <AdobePremiereProCS6-6.0.0-Trial,AdobeDynamicLinkMediaServer-1.0,1.0.1>
    <REVOKE,ALL,AdobePremiereProCS6-6.0.0-Trial,6.0.1>
    <AdobePremiereProCS6-6.0.0-Trial,AdobePremiereProCS6-6.0.0-Trial,6.0.2>
    <COMBO,AdobePremiereProCS6-6.0.0-Trial,AdobePremiereProCS6-6.0.0-Trial,6.0.2,6.0.2,AdobePremiereProCS6LangPackde_DE-6.0.0,AdobePremiereProCS6LangPacken_US-6.0.0,AdobePremiereProCS6LangPackes_ES-6.0.0,AdobePremiereProCS6LangPackfr_FR-6.0.0,AdobePremiereProCS6LangPackit_IT-6.0.0,AdobePremiereProCS6LangPackja_JP-6.0.0,AdobePremiereProCS6LangPackko_KR-6.0.0>
    <AdobePremiereProCS6-6.0.0-Trial,AdobeCSXSInfrastructureCS6-3,3.0.2>
    <AdobePremiereProCS6-6.0.0-Trial,AdobePremiereProCS6-6.0.0-Trial,6.0.1>
    <COMBO,AdobePremiereProCS6-6.0.0-Trial,AdobePremiereProCS6-6.0.0-Trial,6.0.1,6.0.1,AdobePremiereProCS6LangPackde_DE-6.0.0,AdobePremiereProCS6LangPacken_US-6.0.0,AdobePremiereProCS6LangPackes_ES-6.0.0,AdobePremiereProCS6LangPackfr_FR-6.0.0,AdobePremiereProCS6LangPackit_IT-6.0.0,AdobePremiereProCS6LangPackja_JP-6.0.0,AdobePremiereProCS6LangPackko_KR-6.0.0>
    <AdobePremiereProCS6-6.0.0-Trial,AdobeCSXSInfrastructureCS6-3,3.0.1>

    PhotoshopCameraRaw764bit-7:

    curl -s http://swupmf.adobe.com/webfeed/oobe/aam20/mac/updaterfeed.xml | grep PhotoshopCameraRaw764bit-7.0

    <REVOKE,PhotoshopCameraRaw7-7.0,PhotoshopCameraRaw764bit-7.0,7.1.71>
    <REVOKE,PhotoshopCameraRaw7-7.0,PhotoshopCameraRaw764bit-7.0,7.2.82>
    <PhotoshopCameraRaw7-7.0,PhotoshopCameraRaw764bit-7.0,7.2.82>
    <PhotoshopCameraRaw7-7.0,PhotoshopCameraRaw764bit-7.0,7.1.71>

    Some revoke-related strings from
    Adobe Application\ Manager/UWA/UpdaterCore.framework/Versions/A/UpdaterCore:

    Revoke Update: Invalid tracker input.No Recommendation
    Revoke Update: Removing whole update as its a REVOKE ALL.
    Revoke Update: Invalid tracker input.ChannelID should be uniquely present
    Revoke Update: Invalid tracker input.OwningID and UpdateID should be uniquely present
    Revoke Update: Removing whole update as this was the last recommentation.
    Revoke Update: Removing only this recommentation and not the whole update.

    """
    revoke_count = 0
    for update in parsed_feed:
        if (update.product, update.version) == (product, version) \
            and update.channel in [channel, 'ALL']:
            if update.revoked == True:
                L.log(DEBUG, "REVOKE counter +1")
                revoke_count += 1
            else:
                L.log(DEBUG, "REVOKE counter -1")
                revoke_count -= 1
    if revoke_count > -1:
        return True
    else:
        return False


def getHighestVersionOfProduct(updates, product, include_revoked=False):
    """Given a list of UpdateMeta tuples, return a string of the
    highest detected version. We should be able to rely entirely on
    the webfeed revoke logic and not use this, but this helps catch
    at least one edge case: AdobeCSXSInfrastructureCS6_3
    """
    from distutils.version import LooseVersion

    def compare_versions(a, b):
        """Internal comparison function for use with sorting"""
        return cmp(LooseVersion(a), LooseVersion(b))

    versions = []
    for update in updates:
        if update.product == product:
            if not include_revoked and not update.revoked:
                versions.append(update.version)
    if versions:
        versions.sort(compare_versions)
        highest = versions[-1]
        return highest
    else:
        return None


def buildProductPlist(esd_path, munki_update_for):
    plist = {}
    for root, dirs, files in os.walk(esd_path):
        if 'payloads' in dirs and 'Install.app' in dirs:
            payload_dir = os.path.join(root, 'payloads')
            channels = []

            media_db_path = os.path.join(payload_dir, 'Media_db.db')
            if os.path.exists(media_db_path):
                conn = sqlite3.connect(media_db_path)
                c = conn.cursor()
                c.execute("""SELECT value from PayloadData where PayloadData.key = 'ChannelID'""")
                result = c.fetchall()
                c.close()
                if result:
                    channels = [i[0] for i in result]
                else:
                    errorExit("Error: No ChannelIds could be retrieved from the Media_db!")
            else:
                # fall back to old method of scraping proxy.xml, not compatible with CC products
                L.log(WARNING, "Warning: No Media_db.db file found to scrape ChannelIds, "
                      "falling back to using *.proxy.xml files.")
                from glob import glob
                proxies = glob(payload_dir + '/*/*.proxy.xml')
                for proxy in proxies:
                    L.log(INFO, "Found %s" % os.path.basename(proxy))
                    pobj = ET.parse(proxy).getroot()
                    chan = pobj.find('Channel')
                    if chan is not None:
                        channels.append(chan.get('id'))
            plist['channels'] = channels
            if munki_update_for:
                plist['munki_update_for'] = munki_update_for
    return plist


def main():
    usage = """

%prog --product-plist path/to/plist [-p path/to/another] [--munkiimport] [options]
%prog --build-product-plist path/to/Adobe/ESD/volume [--munki-update-for] BaseProductPkginfoName

The first form will check and cache updates for the channels listed in the plist
specified by the --product-plist option.

The second form will generate a product plist containing every channel ID available
for the product whose ESD installer volume is mounted at the path.

See %prog --help for more options and the README for more detail."""

    o = optparse.OptionParser(usage=usage)
    o.add_option("-m", "--munkiimport", action="store_true", default=False,
        help="Process downloaded updates with munkiimport using options defined in %s." % os.path.basename(settings_plist))
    o.add_option("-r", "--include-revoked", action="store_true", default=False,
        help="Include updates that have been marked as revoked in Adobe's feed XML.")
    o.add_option("-f", "--force-import", action="store_true", default=False,
        help="Run munkiimport even if it finds an identical pkginfo and installer_item_hash in the repo.")
    o.add_option("-c", "--make-catalogs", action="store_true", default=False,
        help="Automatically run makecatalogs after importing into Munki.")
    o.add_option("-p", "--product-plist", "--plist", action="append",
        help="Path to an Adobe product plist, for example as generated using the --build-product-plist option. \
Can be specified multiple times.")
    o.add_option("-b", "--build-product-plist", action="store",
        help="Given a path to a mounted Adobe product ESD installer, save a product plist containing every Channel ID found for the product.")
    o.add_option("-u", "--munki-update-for", action="store",
        help="To be used with the --build-product-plist option, specifies the base Munki product.")
    o.add_option("-v", "--verbose", action="count", default=0,
        help="Output verbosity. Can be specified either '-v' or '-vv'.")
    o.add_option("--no-colors", action="store_true", default=False,
        help="Disable colored ANSI output.")

    opts, args = o.parse_args()

    # setup logging
    global L
    L = logging.getLogger('com.github.aamporter')
    log_stdout_handler = logging.StreamHandler(stream=sys.stdout)
    log_stdout_handler.setFormatter(ColorFormatter(
        use_color=not opts.no_colors))
    L.addHandler(log_stdout_handler)
    # INFO is level 30, so each verbose option count lowers level by 10
    L.setLevel(INFO - (10 * opts.verbose))

    # arg/opt processing
    if len(sys.argv) == 1:
        o.print_usage()
        sys.exit(0)
    if opts.munki_update_for and not opts.build_product_plist:
        errorExit("--munki-update-for requires the --build-product-plist option!")
    if not opts.build_product_plist and not opts.product_plist:
        errorExit("One of --product-plist or --build-product-plist must be specified!")

    if opts.build_product_plist:
        esd_path = opts.build_product_plist
        if esd_path.endswith('/'):
            esd_path = esd_path[0:-1]
        plist = buildProductPlist(esd_path, opts.munki_update_for)
        if not plist:
            errorExit("Couldn't build payloads from path %s." % esd_path)
        else:
            if opts.munki_update_for:
                output_plist_name = opts.munki_update_for
            else:
                output_plist_name = os.path.basename(esd_path.replace(' ', ''))
            output_plist_name += '.plist'
            output_plist_file = os.path.join(SCRIPT_DIR, output_plist_name)
            try:
                plistlib.writePlist(plist, output_plist_file)
            except:
                errorExit("Error writing plist to %s" % output_plist_file)
            print "Product plist written to %s" % output_plist_file
            sys.exit(0)

    # munki sanity checks
    if opts.munkiimport:
        if not os.path.exists('/usr/local/munki'):
            errorExit("No Munki installation could be found. Get it at http://code.google.com/p/munki")
        sys.path.insert(0, MUNKI_DIR)
        munkiimport_prefs = os.path.expanduser('~/Library/Preferences/com.googlecode.munki.munkiimport.plist')
        if pref('munki_tool') == 'munkiimport':
            if not os.path.exists(munkiimport_prefs):
                errorExit("Your Munki repo seems to not be configured. Run munkiimport --configure first.")
            try:
                import imp
                # munkiimport doesn't end in .py, so we use imp to make it available to the import system
                imp.load_source('munkiimport', os.path.join(MUNKI_DIR, 'munkiimport'))
                import munkiimport
                munkiimport.REPO_PATH = munkiimport.pref('repo_path')
            except ImportError:
                errorExit("There was an error importing munkilib, which is needed for --munkiimport functionality.")
            if not munkiimport.repoAvailable():
                errorExit("The Munki repo cannot be located. This tool is not interactive; first ensure the repo is mounted.")

    # set up the cache path
    local_cache_path = pref('local_cache_path')
    if os.path.exists(local_cache_path) and not os.path.isdir(local_cache_path):
        errorExit("Local cache path %s was specified and exists, but it is not a directory!" %
            local_cache_path)
    elif not os.path.exists(local_cache_path):
        try:
            os.mkdir(local_cache_path)
        except OSError:
            errorExit("Local cache path %s could not be created. Verify permissions." %
                local_cache_path)
        except:
            errorExit("Unknown error creating local cache path %s." % local_cache_path)
    try:
        os.access(local_cache_path, os.W_OK)
    except:
        errorExit("Cannot write to local cache path!" % local_cache_path)

    # load our product plists
    product_plists = []
    for plist_path in opts.product_plist:
        try:
            plist = plistlib.readPlist(plist_path)
        except:
            errorExit("Couldn't read plist at %s!" % plist_path)
        if 'channels' not in plist.keys():
            errorExit("Plist at %s is missing a 'channels' array, which is required." % plist_path)
        else:
            product_plists.append(plist)

    # sanity-check the settings plist for unknown keys
    if os.path.exists(settings_plist):
        try:
            app_options = plistlib.readPlist(settings_plist)
        except:
            errorExit("There was an error loading the settings plist at %s" % settings_plist)
        for k in app_options.keys():
            if k not in supported_settings_keys:
                print "Warning: Unknown setting in %s: %s" % (os.path.basename(settings_plist), k)

    L.log(INFO, "Starting aamporter run..")
    if opts.munkiimport:
        L.log(INFO, "Will import into Munki (--munkiimport option given).")

    L.log(DEBUG, "aamporter preferences:")
    for key in supported_settings_keys:
        L.log(DEBUG, " - {0}: {1}".format(key, pref(key)))

    # pull feed info and populate channels
    L.log(INFO, "Retrieving feed data..")
    feed = getFeedData()
    parsed = parseFeedData(feed)
    channels = getChannelsFromProductPlists(product_plists)
    L.log(INFO, "Processing the following Channel IDs:")
    [ L.log(INFO, "  - %s" % channel) for channel in sorted(channels) ]

    # begin caching run and build updates dictionary with product/version info
    updates = {}
    for channelid in channels.keys():
        L.log(VERBOSE, "Getting updates for Channel ID %s.." % channelid)
        channel_updates = getUpdatesForChannel(channelid, parsed)
        if not channel_updates:
            L.log(DEBUG, "No updates for channel %s" % channelid)
            continue
        channel_updates = addUpdatesXML(channel_updates)

        for update in channel_updates:
            L.log(VERBOSE, "Considering update %s, %s.." % (update.product, update.version))

            if opts.include_revoked is False:
                highest_version = getHighestVersionOfProduct(channel_updates, update.product)
                if update.version != highest_version:
                    L.log(DEBUG, "%s is not the highest version available (%s) for this update. Skipping.." % (
                        update.version, highest_version))
                    continue

                if updateIsRevoked(update.channel, update.product, update.version, parsed):
                    L.log(DEBUG, "Update is revoked. Skipping update.")
                    continue

                file_element = update.xml.find('InstallFiles/File')
                if file_element is None:
                    L.log(DEBUG, "No File XML element found. Skipping update.")
                else:
                    filename = file_element.find('Name').text
                    bytes = file_element.find('Size').text
                    description = update.xml.find('Description/en_US').text
                    display_name = update.xml.find('DisplayName/en_US').text

                    if not update.product in updates.keys():
                        updates[update.product] = {}
                    if not update.version in updates[update.product].keys():
                        updates[update.product][update.version] = {}
                        updates[update.product][update.version]['channel_ids'] = []
                        updates[update.product][update.version]['update_for'] = []
                    updates[update.product][update.version]['channel_ids'].append(update.channel)
                    for opt in ['munki_repo_destination_path', 'munki_update_for']:
                        if opt in channels[update.channel].keys():
                            updates[update.product][update.version][opt] = channels[update.channel][opt]
                    updates[update.product][update.version]['description'] = description
                    updates[update.product][update.version]['display_name'] = display_name
                    dmg_url = urljoin(getURL('updates'), UPDATE_PATH_PREFIX) + \
                            '/%s/%s/%s' % (update.product, update.version, filename)
                    output_filename = os.path.join(local_cache_path, "%s-%s.dmg" % (
                            update.product, update.version))
                    updates[update.product][update.version]['local_path'] = output_filename
                    need_to_dl = True
                    if os.path.exists(output_filename):
                        we_have_bytes = os.stat(output_filename).st_size
                        if we_have_bytes == int(bytes):
                            L.log(INFO, "Skipping download of %s %s, it is already cached." 
                                % (update.product, update.version))
                            need_to_dl = False
                        else:
                            L.log(VERBOSE, "Incomplete download (%s bytes on disk, should be %s), re-starting." % (
                                we_have_bytes, bytes))
                    if need_to_dl:
                        L.log(INFO, "Downloading update at %s" % dmg_url)
                        urllib.urlretrieve(dmg_url, output_filename)
    L.log(INFO, "Done caching updates.")

    # begin munkiimport run
    if opts.munkiimport:
        L.log(INFO, "Beginning Munki imports..")
        for (update_name, update_meta) in updates.items():
            for (version_name, version_meta) in update_meta.items():
                need_to_import = True
                item_name = "%s%s" % (update_name.replace('-', '_'),
                    pref('munki_pkginfo_name_suffix'))
                # Do 'exists in repo' checks if we're not forcing imports
                if opts.force_import is False and pref("munki_tool") == "munkiimport":
                    pkginfo = munkiimport.makePkgInfo(['--name',
                                            item_name,
                                            version_meta['local_path']],
                                            False)
                    # Cribbed from munkiimport
                    L.log(VERBOSE, "Looking for a matching pkginfo for %s %s.." % (
                        item_name, version_name))
                    matchingpkginfo = munkiimport.findMatchingPkginfo(pkginfo)
                    if matchingpkginfo:
                        L.log(VERBOSE, "Got a matching pkginfo.")
                        if ('installer_item_hash' in matchingpkginfo and
                            matchingpkginfo['installer_item_hash'] ==
                            pkginfo.get('installer_item_hash')):
                            need_to_import = False
                            L.log(INFO,
                                ("We have an exact match for %s %s in the repo. Skipping.." % (
                                    item_name, version_name)))
                    else:
                        need_to_import = True

                if need_to_import:
                    munkiimport_opts = pref('munkiimport_options')[:]
                    if pref("munki_tool") == 'munkiimport':
                        if 'munki_repo_destination_path' in version_meta.keys():
                            subdir = version_meta['munki_repo_destination_path']
                        else:
                            subdir = pref('munki_repo_destination_path')
                        munkiimport_opts.append('--subdirectory')
                        munkiimport_opts.append(subdir)
                    if not version_meta['munki_update_for']:
                        L.log(WARNING,
                            "Warning: {0} does not have an 'update_for' key "
                            "specified in the product plist!".format(item_name))
                        update_catalogs = []
                    else:
                        # handle case of munki_update_for being either a list or a string
                        flatten = lambda *n: (e for a in n
                            for e in (flatten(*a) if isinstance(a, (tuple, list)) else (a,)))
                        update_catalogs = list(flatten(version_meta['munki_update_for']))
                        for base_product in update_catalogs:
                            munkiimport_opts.append('--update_for')
                            munkiimport_opts.append(base_product)
                    munkiimport_opts.append('--name')
                    munkiimport_opts.append(item_name)
                    munkiimport_opts.append('--displayname')
                    munkiimport_opts.append(version_meta['display_name'])
                    munkiimport_opts.append('--description')
                    munkiimport_opts.append(version_meta['description'])
                    if '--catalog' not in munkiimport_opts:
                        munkiimport_opts.append('--catalog')
                        munkiimport_opts.append('testing')
                    if pref('munki_tool') == 'munkiimport':
                        import_cmd = ['/usr/local/munki/munkiimport', '--nointeractive']
                    elif pref('munki_tool') == 'makepkginfo':
                        import_cmd = ['/usr/local/munki/makepkginfo']
                    else:
                        # TODO: validate this pref earlier
                        L.log(ERROR, "Not sure what tool you wanted to use; munki_tool should be 'munkiimport' " + \
                        "or 'makepkginfo' but we got '%s'.  Skipping import." % (pref('munki_tool')))
                        break
                    # Load our app munkiimport options overrides last
                    import_cmd += munkiimport_opts
                    import_cmd.append(version_meta['local_path'])

                    L.log(INFO, "Importing {0} {1} into Munki. Update for: {2}".format(
                        item_name, version_name, ', '.join(update_catalogs)))
                    L.log(VERBOSE, "Calling %s on %s version %s, file %s." % (
                        pref('munki_tool'),
                        update_name,
                        version_name,
                        version_meta['local_path']))
                    munkiprocess = subprocess.Popen(import_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    # wait for the process to terminate
                    stdout, stderr = munkiprocess.communicate()
                    import_retcode = munkiprocess.returncode
                    if import_retcode:
                        L.log(ERROR, "munkiimport returned an error. Skipping update..")
                    else:
                        if pref('munki_tool') == 'makepkginfo':
                            plist_path = os.path.splitext(version_meta['local_path'])[0] + ".plist"
                            with open(plist_path, "w") as plist:
                                plist.write(stdout)
                                L.log(INFO, "pkginfo written to %s" % plist_path)


        L.log(INFO, "Done Munki imports.")
        if opts.make_catalogs:
            munkiimport.makeCatalogs()

if __name__ == '__main__':
    main()
