# aamporter

# Important note

Adobe's mid-June 2016 product updates [described here](https://helpx.adobe.com/creative-cloud/packager/apps-deployed-without-their-base-versions.html), and all new releases for CC 2017, use a new installer technology (known internally as "HyperDrive"). These applications and their updates are not compatible with the updates feed or mechanisms that aamporter understands. aamporter is therefore only useful for doing updates for Adobe CS5-CS6 and CC versions up until the original 2015 releases. In February 2017 (this latest doc update), there are very few applications whose most recent version still uses this original format (Adobe Lightroom, for example).

## Overview

aamporter is a tool for automating the downloading of updates to Adobe Creative Cloud and Creative Suite applications, and optionally importing them into a [Munki](https://github.com/munki/munki) repo.

The 'aam' in the name refers to Adobe Application Manager, the user-facing name for Adobe's installer and licensing subsystem for Creative Cloud/Suite products.

The download functionality attempts to replicate the same logic used by the AAM system and the Creative Cloud Packager tools. The Munki-importing functionality is possible because Munki is the only Mac software application

to retrieve the user-definable sets of updates for Adobe Creative Suite products and suites. It also automates the process of importing these into a [Munki](http://code.google.com/p/munki) repo. Later, the tool can be re-run to pull in new updates as they are released and you can begin testing.

## Usage

Build a 'product plist' with a list of channels you would like to check for updates. For a list of Channel IDs and product names, see the [tech note on Channel IDs for Creative Suite and Creative Cloud](https://forums.adobe.com/servlet/JiveServlet/downloadBody/2434-102-2-4406/AdobeRemoteUpdateManager_ChannelIds.pdf) for a list of updates that you're likely to be most interested in. See the `product-plist-examples` folder for a few example plists and the section below on generating product plists. Each channel may have multiple different updates available to it, and every product that can be purchased from Adobe, whether a suite or a single product, is comprised of many Channel IDs. Typically only several of these will ever actually have updates available.

If you plan to have updates imported into Munki, you should also set the `munki_update_for` key within the plist. This is either a string or array corresponding to the item(s) in Munki you would make these an `update_for` (in other words, the base product(s) you are putting in a Munki manifest).

Now, run aamporter with the plist path as an argument to fetch all the latest updates for these channels:

`./aamporter.py SomeAdobeProduct.plist` (this plist can be named whatever you'd like)

You can specify as many plists as you like, to check multiple products at once.

See the [`local_cache_path`](#config_local_cache_path) configuration option to override the default location these are stored.

Use the `--platform win` option to fetch the latest Adobe updates for Windows products (as .zip files) using the these channels. `--platform` defaults to `mac`.

Note: Munki isn't designed to understand Windows based Adobe updates so the `--platform win` option cannot be used with the --munkiimport option.


### Importing into Munki

Using the `--munkiimport` option will effectively run `munkiimport --nointeractive` on each downloaded update, automatically setting appropriate `name`, `display_name`, `description`, `update_for` keys, and additional options that can be specified in the `aamporter.plist` preference file. You may also override the destination pkg/pkginfo path per product plist using the `munki_repo_destination_path` key in a product plist (string value). This is useful if you like to group your CS updates by version along with your installers.


**Important**: If multiple plists are specified and any channels are shared between one or more products (ie. Photoshop, which is part of many suites), the update's pkginfo will have an `update_for` item for each product to which it applies. If it's expected that an update will apply to multiple base products (Camera Raw, for example), it's important to specify all relevant product plists in a single run.

aamporter calls upon functionality in munkiimport that will detect whether you already have an item in your repo. The default behaviour of aamporter will skip the duplicate import, but this can be overridden with the `--force-import` option.

Once a run is complete and new items have been imported, catalogs will not be rebuilt by default. The `--make-catalogs` option, when set, will trigger makecatalogs at the end of the run.

Some organizations can't use `munkiimport` and need to use `makepkginfo` instead.  You can have aamporter call `makepkginfo` by setting `munki_tool` to `makepkginfo` in the `aamporter.plist` file.

#### More documentation for Munki

[Nick McSpadden](https://twitter.com/mrnickmcspadden) has done a [comprehensive writeup on the Munki Wiki](https://github.com/munki/munki/wiki/Munki%20And%20Adobe%20CC) on importing Adobe Creative Cloud installers and updates into Munki, covering aamporter.

### Generating product plists

The `--build-product-plist` option will generate a product plist automatically, using all Channel IDs found at the path of an Adobe ESD installer or a .ccp file from a (Mac or Windows) installer built using Creative Cloud Packager:

`./aamporter.py --build-product-plist "/Volumes/CS6 DesWebPrm"`

`./aamporter.py --build-product-plist "AdobeCCPhotoshopInstaller.ccp"`

This will save a plist named after the location given, but you can name it anything you'd like. You may want to modify it to include only the updates you're interested in for the product. Most suites have roughly a dozen "base product" channels that will get updates for themselves and shared components like Dynamic Link Media Server and CSXS Infrastructure. For example, we could reduce this list down to something like:

* AdobeAPE3.3_Mac_NoLocale
* AdobeBridgeCS6-5.0
* PhotoshopCameraRaw7-7.0
* AdobeDreamweaverCS6-12
* AdobeExtensionManagerCS6-6.0
* AdobeFireworksCS6-12.0.0-mul
* FlashPro12.0
* AdobeIllustrator16-mul
* AdobeInDesignCS6-8.0
* AdobePhotoshopCS6-13.0
* AdobeMediaEncoderCS6-6

It's possible this may miss some obscure update that an automatically-generated plist wouldn't, but using the main application Channel IDs should catch most, if not all, of what you want.

### Revoked updates

Adobe retains some old updates in its feed, marking them as revoked. By default, aamporter will not fetch and import these, but this can be overrided with the `--include-revoked` option. CS updates seem to be always cumulative patches, and CS apps are not easily reverted to previous versions (instead requiring a full uninstall/reinstall), but you may want to collect previous versions if there are issues with installing the latest updates.

### Creative Cloud updates

The `--build-product-plist` option can also be used against a CC application installer ESD in the same manner as CS-era products. However, currently aamporter does not fetch every single CC update available.

There was period after CS6's release when some CS6-era products received updates only available to Creative Cloud customers - Illustrator and DreamWeaver got point-one updates that would not be installed by running [RemoteUpdateManager](http://helpx.adobe.com/creative-cloud/packager/using-remote-update-manager.html). These are mostly all branded with the `FEATURE` descriptor in the metadata feed, and seem to use a metadata element, `TargetLicensingType`, with a value of `1` to identify a CC update.

When the first CC application patch updates were released in June 2013, they did _not_ specify this CC-related metadata, but the Photoshop 14.1 update released in September 2013 _does_, and RemoteUpdateManager will still install these. So, more work must be done to determine how these updates are discerned by RemoteUpdateManager.

### Bonus: Importing CCP packages into Munki

Since Creative Cloud doesn't really have the notion of a "suite" of apps, you may have a large number of individual CC application installers built using Creative Cloud Packager. Since the process of importing these all into Munki is time-consuming, I wrote a short script to automate this process, which I included in this repo [here](https://github.com/timsutton/aamporter/tree/master/scripts/munkiimport_cc_installers.py).

## Caveats<a name="caveats"></a>

### Product plists are your responsibility

The example product/channel ID mappings provided aren't a definitive list. You should decide which updates you want to deploy, and test them thoroughly. You may well decide you only care about the main application updates and so can keep a relatively small list of channels for a given product.

There is usually at least one update with every major version of the CS suite that has major issues with a "silent install," for example hanging in non-GUI installation contexts (Flash Pro 12.0.2 [triggering an Extension Manager installer](http://blogs.adobe.com/flashpro/2012/09/25/flash-professional-cs6-update2)), or improper cleanup following an install (Dreamweaver CS5 11.0.3 and Extension Manager [re-launch looping](http://blogs.adobe.com/csupdates/2010/08/31/dreamweaver-cs5-11-0-3-updater)). Nothing new here.

### Conflicts with updates already in your repo

The munkiimport functionality will create pkginfos named according to the internal update name, substituting the hyphen with an underscore (so Munki doesn't interpret as the pkginfo version) and with a custom suffix added (see `munki_pkginfo_name_suffix` below). For example: `AdobePhotoshopCS6Support_13.0_Update`.

If you already have several updates for a product in your repo and they (likely) don't use this naming convention, you'll have duplicate pkginfos for the same product. You may want to first clear existing updates from your repo or only test aamporter with a product you are just beginning to configure in Munki and for which you don't already have updates available in production.

### Undocumented order of installation

There has been at least one case (Photoshop CS5 updates 12.0.2 through 12.0.4, pointed out by Greg Neagle) where an application would only patch itself successfully if the updates were applied in the order they were actually released. I've not discovered anything in the webfeed XML that documents when an update was released, so again, test thoroughly.

### Manually-generated installs keys may still be needed for Munki

I've found that most CS suite applications will keep a proper installed state using the installs item that's automatically generated by makepkginfo/munkiimport. This may not always be the case for _every_ application in the suite. You may want to use your own installs keys for the base application and each update, rather than letting Munki track these by the `/Library/Application Support/Adobe/Uninstall/{guid}.db` files used by default.

See the [Adobe CS area](http://code.google.com/p/munki/wiki/MunkiAndAdobeCS5Updates) of the Munki wiki for more details on Adobe CS5/5.5/6 pkginfos.

### Adobe Help uses AIR

Adobe Help uses a different, AIR-based method to install and requires an alternate approach to deploy. Greg has [outlined this on his blog](http://managingosx.wordpress.com/2011/05/02/more-help-from-adobe) and written a helpful wrapper script for deploying Adobe Help updates within a .pkg format. Adobe has since made the use of the AIR silent install mode in a `launchd bsexec` context their official workaround (see the [Adobe Enterprise CS Deployment Guide](http://wwwimages.adobe.com/www.adobe.com/content/dam/Adobe/en/devnet/creativesuite/pdfs/AdobeApplicationManagerEnterpriseEditionDeploymentGuide_v_3_1.pdf)). There have been a number of reports of this method not working reliably and/or reporting errors. Jim Zajkowski has documented on the [munki-dev mailing list](https://groups.google.com/d/topic/munki-dev/Iio2AFjeasg/discussion) a script to repeat the entire AIR installer logic, effectively repackaging it by pre-staging all its components.

### CS apps still a pain

In summary, this utility doesn't resolve any issues with patching Adobe installers. It is simply useful for removing much of the tedium in tracking/downloading updates from project team blog posts, RSS feeds, and Adobe's update websites, and the time required to manually import each one into Munki and apply small tweaks. Given the caveats above, work is still required, but aamporter should get you about 80% of the way there in the configuration/import phase.

If you were previously using AAMEE to fetch and package updates, while this tool won't handle packaging for you, it can fetch updates for CS5, CS5.5 and CS6. AAMEE currently won't retrieve updates for both CS5/5.5 and CS6 without installing both 2.x and 3.x (which is not supported: see [Remove AAMEE](http://wwwimages.adobe.com/www.adobe.com/content/dam/Adobe/en/devnet/creativesuite/pdfs/Remove_AAMEE.pdf)).

<a name="adobe_cs_docs"></a>There is official Adobe documentation available at the [CS Enterprise Deployment documentation area](http://forums.adobe.com/community/download_install_setup/creative_suite_enterprise_deployment?view=documents)

## aamporter.plist options

You may specify the following options below in an `aamporter.plist` file residing in the script directory:

<a name="config_local_cache_path"></a>**local_cache_path**

A local path for cached updates. If it doesn't yet exist it will be created, and it defaults to 'aamcache' in the aamporter script directory.

<a name="config_munki_pkginfo_name_suffix"></a>**munki_pkginfo_name_suffix**

A suffix to be added to the pkginfo names (the 'name' key, not the filename) for each update that's imported into Munki.

<a name="config_munkiimport_options"></a>**munkiimport_options**

An array of strings representing supplemental options for munkiimport as they would be passed to the shell. For example, an alternate catalog name could be specified here, minimum/maximum os versions, etc.

<a name="config_aam_server_baseurl"></a>**aam_server_baseurl**

The base URL for a local AUSST server, if you have one already configured and would like to pull your updates from that as opposed to Adobe's servers. Adobe's documentation on using the 'override' file would have you configure multiple server entries for both the 'webfeed' and 'update' functions and for both version 1.0 and 2.0 of AUSST. `aam_server_baseurl` is only a single value to configure, as it assumes nobody with an AUSST configuration is actually using two separate hosts to separate the feed and payload files.

<a name="config_munki_repo_destination_path"></a>**munki_repo_destination_path**

Configure the destination path for updates globally. This option can also be set within each product plist, if you like to keep your updates grouped by CS version.

<a name="munki_tool"></a>**munki_tool**

Select either `munkiimport` or `makepkginfo`.  `munkiimport` is the default.

## Current issues:

* console output is not nicely structured.
* for channels shared across product plists, the `update_for` keys in pkginfos will only take these products into account for plists passed to aamporter in a single command invocation. in other words, they are not (yet) implicitly loaded from other plists on disk.
* see [Caveats](#caveats) section

## Thanks

Greg Neagle gave a lot of constructive and insightful feedback since this was first posted, and his testing has greatly helped shape the functionality of aamporter.
