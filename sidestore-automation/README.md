# Personal SideStore automatic renewal

This isolated branch builds SideStore from pinned upstream commit 6032424a0e56c1c319762e786099bdd9186a238b with a no-menu renewal interface. It renews RustDesk V2 and then SideStore, verifies installed provisioning profiles, and returns a terminal result for automatic VPN recovery.

The build recipe, validator and reviewed patch live in this directory. The workflow runs on xcode-27, checks the actual iOS SDK, and does not request Apple credentials or sign a device IPA. Existing application identity is retained for normal personal signing and in-place installation.

A push modifying only personal-automation.patch on sidestore-automation-no-menus starts the authorized build. There is no schedule or release publication.

Source compilation, actual registered intent metadata, personal installation, and real-device automatic renewal each need separate validation. Process termination or a locked device is not reported as successful renewal.

Upstream: https://github.com/SideStore/SideStore/tree/6032424a0e56c1c319762e786099bdd9186a238b
