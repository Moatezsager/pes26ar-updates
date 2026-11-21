# PES26AR updates

Signed update metadata is published at `channels/stable.signed.json`. Clients verify the RSA signature before trusting file hashes, APK versions or download URLs.

The channel may advertise both the game data catalog and an `apk` entry. Keep the APK entry when publishing a data-only change. Each APK requires an increasing Android `versionCode`, the same package and the same signing certificate.

Data release `2026.11.21.1` changes only `Game/img/dt06.img`; the other 270 files retain their previous hashes and GitLab sources. New dt06 chunks are served from GitHub Releases. Per-chunk URLs are required for this mixed-source catalog; do not set a global `chunk_bases` override.

APK 1.10.0 (versionCode 110) was confirmed by the user to install over the previous version and open maintenance, settings and the game on their phone. Full fresh game download, the combined dt06 data update and the next-version in-app installer flow still need device validation. The signed channel's APK entry reports release notes and the exact download hash.

Private signing keys and account credentials must never be committed to this repository.
