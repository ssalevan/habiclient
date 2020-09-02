Habiclient: C64 Client For Lucasfilm's Habitat
==============================================

[![Build Status](https://travis-ci.org/ssalevan/habiclient.svg?branch=master)](https://travis-ci.org/ssalevan/habiclient)
[![license](https://img.shields.io/github/license/mashape/apistatus.svg)](https://github.com/ssalevan/habiclient/blob/master/LICENSE)
[![Twitter Follow](https://img.shields.io/twitter/follow/NeoHabitatProj.svg?style=social&label=Follow)](https://twitter.com/NeoHabitatProj)
[![Slack](http://slack.neohabitat.org/badge.svg)](http://slack.neohabitat.org/)

This repository contains the source code for the original Commodore 64 client used to
connect to the world's first MMO,
[Lucasfilm's Habitat](https://en.wikipedia.org/wiki/Habitat_(video_game)), alongside all
necessary build tooling and scripting. If you're interested in learning more about how it
works, we've included all the automation required to spin up fresh client disk images.

Builds are accomplished via [docker-compose](https://docs.docker.com/compose/), which
will spin up a true powerhouse of a Commodore 64 development container then run through
the client build procedure.

Latest Release
--------------

The latest release of the Habitat client can be downloaded here:

-  [Habitat-A.d64](https://s3.amazonaws.com/habiclient/ssalevan/habiclient/5/5.1/Dist/Habitat-A.d64)
-  [Habitat-B.d64](https://s3.amazonaws.com/habiclient/ssalevan/habiclient/5/5.1/Dist/Habitat-B.d64)

Please Note
-----------

This project is not supported by the [Neohabitat Project](http://neohabitat.org) and is
designed for educational purposes. We definitely accept pull requests, however, and
encourage adventurous hacking, especially if you enjoy 6502 assembly. There are no
guarantees of stability, only of adventure.

Building
--------

To build the client, follow these steps:

1.  Install [Docker](https://www.docker.com/get-started) for your computer's respective
    platform.
2.  From the checkout root, execute `dockerbuild`, which will cook up a special
    `docker-compose.yml` file to trigger the build process.
3.  When the build completes, the `Habitat-A.d64` and `Habitat-B.d64` images will land
    in the `Dist` subdirectory.

Development
-----------

We've supplied a `dockershell` script which will launch a Bash console within the Docker
container used to build the client. The local repository will be mirrored into the 
`/habiclient` directory within this container environment.

The `Makefile` at the root of the repository contains all necessary targets to build
the client's disk images. In particular, running `make diska` will build the
`Habitat-A.d64` image while running `make diskb` will build the `Habitat-B.d64` image.

Testing
-------

Once client images have been built, you can test them by simply launching `Habitat-A.d64`
in [VICE](https://vice-emu.sourceforge.io) under drive #8. As you might imagine, you can
bring it up with `LOAD"*",8,1`. Once you've entered in your details and the Habitat
splash screen appears, the client will ask you to insert the next disk. This is your cue
to swap `Habitat-B.d64` into drive #8.

Help!
-----

This client is not officially supported by the Neohabitat Project, but enterprising
developers often congregate on the project's [Slack](http://slack.neohabitat.org) within
the **#troubleshooting** room.

Credits
-------

All client code was written by Chip Morningstar, F. Randall Farmer, Aric Wilmunder and
Janet Hunter. The Neohabitat launcher as well as the `a65toprg`, `filldisk`, `habdiska`,
`mcmgtrim` and `mtobin` build tools were written by Gary Lake. Dockerization and
buildmeistering support was provided by Steve Salevan.
