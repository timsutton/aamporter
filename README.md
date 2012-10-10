# aamporter

## Usage

Define a set of products and Adobe Channel IDs as shown in the example `aamporter.plist` file. This file is used as a manifest of what products to search for applicable updates.

Invoking it with no arguments will simply download the updates to the current directory.

Passing the `--munkiimport` option will run `munkiimport --nointeractive` on each downloaded update, automatically setting appropriate `name`, `display_name`, `description`, `update_for` keys, and additional options that can be specified in `aamporter.plist`.

## Revoked updates

Unlike Apple, Adobe retains its old updates in its feed, marking them as revoked. By default, aamporter will not fetch these, but this can be overrided with the `--include-revoked` option.

## Current issues:
* missing a number of helpful options
* code is messy
* console output is messy
* there are likely still many bugs (luckily `munkiimport` is very safe with manipulating a Munki repo)
