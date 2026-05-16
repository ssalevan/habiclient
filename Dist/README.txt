HABITAT FOR ULTIMATE 64
=======================

Lucasfilm's Habitat (1986) - the world's first MMO,
running from EasyFlash cartridge on Ultimate 64.

SETUP
-----
1. Copy the contents of this folder to your Ultimate 64's
   USB drive (e.g. USB1/HABICART/).

2. Load the configuration:
   - Press the power button briefly to open the Ultimate menu
   - Navigate to HABICART/ on your USB drive
   - Select habitat-u64.cfg and press RETURN
   - Choose "Load into current config"
   - Press RETURN when it says 'Loading configuration
     successful!'
   - Press F1 and navigate down to 'Configuration' then press
     RETURN
   - Select 'Save to Flash'
     + If you don't do this, the configuration will not persist
       across restarts. If such persistence is not desired, you
       must reload this configuration each time.

3. Run the cartridge:
   - Navigate to Habitat.crt in the same folder
   - Press RETURN and choose "Run Cartridge"

PLAYING
-------
- On the launcher screen:
  - Type your character name (up to 12 characters)
  - Press RETURN to move to the server connection field
  - Press RETURN to connect to the main Neohabitat server
  - Prepare to join the world's first Metaverse...

REQUIREMENTS
------------
- Ultimate 64 (any model) with firmware 3.7 or later
- Network connection (Ethernet or WiFi) already configured
- Neohabitat server running at the configured host

MODEM SETTINGS
--------------
The included .cfg sets up the ACIA/SwiftLink modem
emulation at $DF80 with NMI interrupts. These are the
required settings for Habitat's serial driver.

If you need to configure manually (F2 menu):
  Modem Interface:        ACIA / SwiftLink
  ACIA (6551) Mapping:    DF80/NMI
  Hardware Mode:           SwiftLink
  Drop connection on DTR low: Disabled
  Set Socket Opt TCP_NODELAY: Enabled

TROUBLESHOOTING
---------------
- No video after loading .cfg: The .cfg does not change
  video settings. If you lost video, you may have factory
  reset by accident. Connect via composite/S-Video to
  reconfigure HDMI in F2 > U64 Specific Settings.
- "Lost carrier" message: Check network connection
- Game freezes on connect: Verify modem settings above
- Region transitions slow: Normal - loading from cartridge

SOURCE CODE
-----------
Source repository:
  https://github.com/ssalevan/habiclient

Detailed install + troubleshooting guide:
  https://github.com/ssalevan/habiclient/blob/main/docs/U64.md

All releases (stable + rolling):
  https://github.com/ssalevan/habiclient/releases
