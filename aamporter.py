#!/usr/bin/python
#
# aamporter.py
# Tim Sutton
#
# Utility to download AAM 2.0 and higher (read: CS5 and up) updates from Adobe's updater feed.
# Optionally import them into a Munki repo, assuming munkiimport is already configured.
#
# Configure updates applicable to your managed products in aamporter.plist. What's included by default
# may be used as examples, but are not a definitive, tested list.
#
# Adobe CS deployment documentation:
# http://forums.adobe.com/community/download_install_setup/creative_suite_enterprise_deployment?view=documents

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

FEED_PATH = 'webfeed/oobe/aam20/mac/updaterfeed.xml'
UPDATE_PATH_PREFIX = 'updates/oobe/aam20/mac'
MUNKI_DIR = '/usr/local/munki'
SCRIPT_DIR = os.path.abspath(os.path.dirname(sys.argv[0]))
DEFAULT_MUNKI_PKG_SUBDIR = 'apps/Adobe/CS_Updates'
DEFAULT_LOCAL_CACHE_PATH = os.path.join(SCRIPT_DIR, 'aamcache')
OFFLINE_DEBUG = False
updates_plist = os.path.join(SCRIPT_DIR, 'aamporter.plist')
updates_manifest = plistlib.readPlist(updates_plist)

UpdateMeta = namedtuple('update', ['channel', 'product', 'version', 'revoked'])

# check our aam server if defined
if 'aam_server_baseurl' in updates_manifest.keys():
    aam_webfeed20_baseurl = updates_manifest['aam_server_baseurl']
    aam_updates20_baseurl = updates_manifest['aam_server_baseurl']
else:
    aam_webfeed20_baseurl = 'http://swupmf.adobe.com'
    aam_updates20_baseurl = 'http://swupdl.adobe.com'


def getFeedData(test=False):
    if test:
        with open(os.path.join(os.getcwd(), 'feed.xml')) as fd:
            xml = fd.read()
    else:
        opener = urllib.urlopen(urljoin(aam_webfeed20_baseurl, FEED_PATH))
        xml = opener.read()
        opener.close()
    search = re.compile("<(.+)>")
    results = re.findall(search, xml)
    return results


def parseFeedData(feed_list):
    updates = []
    for update in feed_list:
        # TODO: Figure out what FEATURE is (ie. Illustrator 16.2??)
        if not update.startswith('COMBO'):      # skipping COMBOs for now
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


def getUpdatesForChannel(channel_id, parsed_feed):
    updates = []
    for update in parsed_feed:
        if update.channel == channel_id:
            updates.append(update)
    if not len(updates):
        updates = None
    return updates


def getBaseProductsForChannel(channel_id, updates_plist):
    base_products = []
    for base in updates_plist['products']:
        if channel_id in base['channels']:
            base_products.append(base['name'])

    if not len(base_products):
        base_products = None
    return base_products


def updateIsRevoked(channel, product, version, parsed_feed):
    for update in parsed_feed:
        if (update.product, update.version) == (product, version) \
            and update.channel in [channel, 'ALL'] \
            and update.revoked == True:
                return True
    return False


def errorExit(err_string, err_code=1):
    print err_string
    sys.exit(err_code)


def main():
    feed = getFeedData(test=OFFLINE_DEBUG)
    parsed = parseFeedData(feed)

    o = optparse.OptionParser()
    o.add_option("-m", "--munkiimport", action="store_true", default=False,
        help="Process downloaded updates with munkiimport using options defined in %s." % os.path.basename(updates_plist))
    o.add_option("-r", "--include-revoked", action="store_true", default=False,
        help="Include updates that have been marked as revoked in Adobe's feed XML.")
    o.add_option("-f", "--force-import", action="store_true", default=False,
        help="Run munkiimport even if it finds an identical pkginfo and installer_item_hash in the repo.")

    opts, args = o.parse_args()

    if opts.munkiimport:
        if not os.path.exists('/usr/local/munki'):
            errorExit("No Munki installation could be found. Get it at http://code.google.com/p/munki")
        sys.path.insert(0, MUNKI_DIR)
        munkiimport_prefs = os.path.expanduser('~/Library/Preferences/com.googlecode.munki.munkiimport.plist')
        if not os.path.exists(munkiimport_prefs):
            errorExit("Your Munki repo seems to not be configured. Run munkiimport --configure first.")

        try:
            import imp
            # munkiimport doesn't end in .py, so we use imp to make it available to the import system
            imp.load_source('munkiimport', os.path.join(MUNKI_DIR, 'munkiimport'))
            import munkiimport

        except ImportError:
            errorExit("There was an error importing munkilib, which is needed for --munkiimport functionality.")

    # set our output directory and perform sanity checks
    if 'local_cache_path' not in updates_manifest.keys():
        local_cache_path = DEFAULT_LOCAL_CACHE_PATH
    else:
        local_cache_path = updates_manifest['local_cache_path']

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

    for product in updates_manifest['products']:
        print "Product %s" % product['name']
        for channel in product['channels']:
            print "Channel %s" % channel
            channel_updates = getUpdatesForChannel(channel, parsed)
            if not channel_updates:
                print "No updates for channel %s" % channel
                continue
            for update in channel_updates:
                print "Update %s, %s..." % (update.product, update.version)
                # if update.channel in product['channels']:
                if update.channel not in product['channels']:
                    continue

                if opts.include_revoked is False and \
                updateIsRevoked(update.channel, update.product, update.version, parsed):
                    print "Update is revoked. Skipping update."
                    continue
                if OFFLINE_DEBUG:
                    continue
                details_url = urljoin(aam_updates20_baseurl, UPDATE_PATH_PREFIX) + \
                    '/%s/%s/%s.xml' % (update.product, update.version, update.version)
                try:
                    channel_xml = urllib.urlopen(details_url)
                except:
                    print "Couldn't read details XML at %s" % details_url
                    break

                try:
                    details_xml = ET.fromstring(channel_xml.read())
                except:
                    print "Couldn't parse XML."
                    break

                if details_xml is not None:
                    file_element = details_xml.find('InstallFiles/File')
                    if file_element is None:
                        print "No File XML element found. Skipping update."
                    else:
                        filename = file_element.find('Name').text
                        bytes = file_element.find('Size').text
                        description = details_xml.find('Description/en_US').text
                        display_name = details_xml.find('DisplayName/en_US').text
                        dmg_url = urljoin(aam_updates20_baseurl, UPDATE_PATH_PREFIX) + \
                            '/%s/%s/%s' % (update.product, update.version, filename)
                        output_filename = os.path.join(local_cache_path, "%s-%s.dmg" % (
                            update.product, update.version))
                        need_to_dl = True
                        if os.path.exists(output_filename):
                            we_have_bytes = os.stat(output_filename).st_size
                            if we_have_bytes == int(bytes):
                                print "Skipping download of %s, we already have it." % update.product
                                need_to_dl = False
                            else:
                                print "Incomplete download, re-starting."
                        if need_to_dl:
                            print "Downloading update at %s" % dmg_url
                            urllib.urlretrieve(dmg_url, output_filename)

                        if opts.munkiimport:
                            need_to_import = True
                            item_name = "%s%s" % (
                                update.product.replace('-', '_'),
                                updates_manifest['pkginfo_name_suffix'])
                            # Do 'exists in repo' checks if we're not forcing imports
                            if opts.force_import is False:
                                pkginfo = munkiimport.makePkgInfo(['--name', item_name, output_filename], False)
                                # Cribbed from munkiimport
                                print "Looking for a matching pkginfo via munkiimport.."
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
                                print "Importing into munki."
                                munkiimport_opts = updates_manifest['munkiimport_options'][:]
                                print "Base munkiimport opts: %s" % munkiimport_opts
                                if '--subdirectory' not in munkiimport_opts:
                                    munkiimport_opts.append('--subdirectory')
                                    munkiimport_opts.append(DEFAULT_MUNKI_PKG_SUBDIR)
                                base_products = getBaseProductsForChannel(
                                    update.channel, updates_manifest)
                                print "Applicable base products for Munki: %s" % ', '.join(base_products)
                                for base_product in base_products:
                                    munkiimport_opts.append('--update_for')
                                    munkiimport_opts.append(base_product)
                                munkiimport_opts.append('--name')
                                munkiimport_opts.append(item_name)
                                munkiimport_opts.append('--displayname')
                                munkiimport_opts.append(display_name)
                                munkiimport_opts.append('--description')
                                munkiimport_opts.append(description)

                                import_cmd = ['/usr/local/munki/munkiimport',
                                '--nointeractive']
                                import_cmd += munkiimport_opts
                                import_cmd.append(output_filename)
                                print "Calling munkiimport on %s version %s, file %s." % (
                                    update.product, update.version, output_filename)
                                import_retcode = subprocess.call(import_cmd)
                                if import_retcode:
                                    print "munkiimport returned an error. Skipping update.."
                                    continue
                                else:
                                    # Rebuilding catalogs so that if the next update for import
                                    # applies to a different channel, we won't import it again
                                    # - ideally munkiimport should be done after _all_ downloads
                                    #   are verified so that we wouldn't need to rebuild catalogs,
                                    #   ie. we'd be able to check the state of each update in the
                                    #   repo prior and only import once
                                    munkiimport.makeCatalogs()

if __name__ == '__main__':
    main()
