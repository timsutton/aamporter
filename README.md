# aamporter

## Usage

Define a set of products and Adobe Channel IDs as shown in the example `aamporter.plist` file. This file is used as a manifest of what products to search for applicable updates.

Invoking it with no arguments will simply download the updates to the current directory.

Passing the `--munkiimport` option will run `munkiimport --nointeractive` on each downloaded update, automatically setting appropriate `name`, `display_name`, `description`, `update_for` keys, and additional options that can be specified in `aamporter.plist`.

### Revoked updates

Unlike Apple, Adobe retains its old updates in its feed, marking them as revoked. By default, aamporter will not fetch these, but this can be overrided with the `--include-revoked` option.

## aamporter.plist options

**local_cache_path**

A local path for cached updates. If it doesn't yet exist it will be created, and it defaults to 'aamcache' created in aamporter directory.

**pkginfo_name_suffix**

A suffix to be added to the pkginfo names (the 'name' key, not the filename) for each update that's imported into Munki.

**munkiimport_options**

A series of supplemental options for munkiimport. For example, an alternate catalog name could be specified here, minimum/maximum os versions, etc.

## Current issues:
* missing a number of helpful options
* code is messy
* console output is messy
* there are likely still many bugs (luckily `munkiimport` is very safe with manipulating a Munki repo)
