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
UpdateMeta = namedtuple('update', ['channel', 'product', 'version', 'revoked'])
UPDATE_PATH_PREFIX = 'updates/oobe/aam20/mac'
MUNKI_DIR = '/usr/local/munki'


def errorExit(err_string, err_code=1):
    print err_string
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
    opener = urllib.urlopen(urljoin(getURL(type='webfeed'), 'webfeed/oobe/aam20/mac/updaterfeed.xml'))
    xml = opener.read()
    opener.close()
    search = re.compile("<(.+?)>")
    results = re.findall(search, xml)
    return results


def parseFeedData(feed_list):
    updates = []
    for update in feed_list:
        # skip COMBOs (language packs?) and FEATUREs (Creative Cloud updates)
        if not update.startswith('COMBO') and not update.startswith('FEATURE'):
            cmpnts = update.split(',')
            ver = cmpnts[-1]     # version: last
            prod = cmpnts[-2]     # product: 2nd last
            chan = cmpnts[-3]     # channel: 3rd last
            if cmpnts[0] != "REVOKE":
                revoked = False
            else:
                revoked = True
            updates.append(UpdateMeta(channel=chan, product=prod, version=ver, revoked=revoked))
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


def updateIsRevoked(channel, product, version, parsed_feed):
    """Returns True if an update is listed as revoked for a channel"""
    for update in parsed_feed:
        if (update.product, update.version) == (product, version) \
            and update.channel in [channel, 'ALL'] \
            and update.revoked == True:
                return True
    return False


def buildProductPlist(esd_path, munki_update_for):
    plist = {}
    for root, dirs, files in os.walk(esd_path):
        if 'payloads' in dirs and 'Install.app' in dirs:
            payload_dir = os.path.join(root, 'payloads')
            channels = []
            from glob import glob
            proxies = glob(payload_dir + '/*/*.proxy.xml')
            for proxy in proxies:
                print "Found %s" % os.path.basename(proxy)
                pobj = ET.parse(proxy).getroot()
                chan = pobj.find('Channel')
                if chan is not None:
                    channels.append(chan.get('id'))
            plist['channels'] = channels
            if munki_update_for:
                plist['munki_update_for'] = munki_update_for
            break
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
        help="Given a path to a mounted Adobe product ESD installer, save a containing every Channel ID found for the product.")
    o.add_option("-u", "--munki-update-for", action="store",
        help="To be used with the --build-product-plist option, specifies the base Munki product.")

    opts, args = o.parse_args()

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

    # pull feed info and populate channels
    feed = getFeedData()
    parsed = parseFeedData(feed)
    channels = getChannelsFromProductPlists(product_plists)

    # begin caching run and build updates dictionary with product/version info
    updates = {}
    for channelid in channels.keys():
        print "Channel %s" % channelid
        channel_updates = getUpdatesForChannel(channelid, parsed)
        if not channel_updates:
            print "No updates for channel %s" % channelid
            continue

        for update in channel_updates:
            print "Update %s, %s..." % (update.product, update.version)

            if opts.include_revoked is False and \
            updateIsRevoked(update.channel, update.product, update.version, parsed):
                print "Update is revoked. Skipping update."
                continue
            details_url = urljoin(getURL('updates'), UPDATE_PATH_PREFIX) + \
                '/%s/%s/%s.xml' % (update.product, update.version, update.version)
            try:
                channel_xml = urllib.urlopen(details_url)
            except:
                print "Couldn't read details XML at %s" % details_url
                break

            try:
                details_xml = ET.fromstring(channel_xml.read())
            except ET.ParseError:
                print "Couldn't parse XML."
                break

            if details_xml is not None:
                licensing_type_elem = details_xml.find('TargetLicensingType')
                if licensing_type_elem is not None:
                    licensing_type_elem = licensing_type_elem.text
                    # TargetLicensingType seems to be 1 for CC updates, 2 for "regular" updates
                    if licensing_type_elem == '1':
                        print "TargetLicensingType of %s found. This seems to be Creative Cloud updates. Skipping update." % licensing_type_elem
                        break

                file_element = details_xml.find('InstallFiles/File')
                if file_element is None:
                    print "No File XML element found. Skipping update."
                else:
                    filename = file_element.find('Name').text
                    bytes = file_element.find('Size').text
                    description = details_xml.find('Description/en_US').text
                    display_name = details_xml.find('DisplayName/en_US').text

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
                            print "Skipping download of %s, we already have it." % update.product
                            need_to_dl = False
                        else:
                            print "Incomplete download (%s bytes on disk, should be %s), re-starting." % (
                                we_have_bytes, bytes)
                    if need_to_dl:
                        print "Downloading update at %s" % dmg_url
                        urllib.urlretrieve(dmg_url, output_filename)
    print "Done caching updates."

    # begin munkiimport run
    if opts.munkiimport:
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
                    print "Looking for a matching pkginfo for %s %s.." % (
                        item_name, version_name)
                    matchingpkginfo = munkiimport.findMatchingPkginfo(pkginfo)
                    if matchingpkginfo:
                        print "Got a matching pkginfo."
                        if ('installer_item_hash' in matchingpkginfo and
                            matchingpkginfo['installer_item_hash'] ==
                            pkginfo.get('installer_item_hash')):
                            need_to_import = False
                            print "We already have an exact match in the repo. Skipping import."
                    else:
                        need_to_import = True

                if need_to_import:
                    print "Importing %s into munki." % item_name
                    munkiimport_opts = pref('munkiimport_options')[:]
                    if pref("munki_tool") == 'munkiimport':
                        if 'munki_repo_destination_path' in version_meta.keys():
                            subdir = version_meta['munki_repo_destination_path']
                        else:
                            subdir = pref('munki_repo_destination_path')
                        munkiimport_opts.append('--subdirectory')
                        munkiimport_opts.append(subdir)
                    if not 'munki_update_for' in version_meta.keys():
                        print "Warning: %s does not have an update_for key specified!"
                    else:
                        print "Applicable base products for Munki: %s" % ', '.join(version_meta['munki_update_for'])
                        for base_product in version_meta['munki_update_for']:
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
                        print "Not sure what tool you wanted to use; munki_tool should be 'munkiimport' " + \
                        "or 'makepkginfo' but we got '%s'.  Skipping import." % (pref('munki_tool'))
                        break
                    # Load our app munkiimport options overrides last
                    import_cmd += munkiimport_opts
                    import_cmd.append(version_meta['local_path'])
                    print "Calling %s on %s version %s, file %s." % (
                        pref('munki_tool'), update_name, version_name, version_meta['local_path'])
                    print import_cmd
                    munkiprocess = subprocess.Popen(import_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    # wait for the process to terminate
                    stdout, stderr = munkiprocess.communicate()
                    import_retcode = munkiprocess.returncode
                    if import_retcode:
                        print "munkiimport returned an error. Skipping update.."
                    else:
                        if pref('munki_tool') == 'makepkginfo':
                            plist_path = os.path.splitext(version_meta['local_path'])[0] + ".plist"
                            with open(plist_path, "w") as plist:
                                plist.write(stdout)
                                print "pkginfo written to %s" % plist_path


        print "Done importing into Munki."
        if opts.make_catalogs:
            munkiimport.makeCatalogs()

if __name__ == '__main__':
    main()
