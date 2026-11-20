# Signed download channel

`stable.signed.json` is the public configuration for the Arabic APK downloader.
It contains base64-encoded UTF-8 JSON and an RSA PKCS#1 v1.5 SHA-256 signature.
The APK embeds only the public key. Never upload a private signing key or an access token here.

Verified payload fields:

- `schema`: 1
- `revision`: increasing integer (initial value 2026112001)
- `release`: the data version
- `manifest_sha256`: SHA-256 of the exact manifest bytes
- `manifest_urls`: ordered HTTPS mirrors of that manifest
- `chunk_bases`: optional ordered HTTPS directories containing `<sha256>.bin`; when supplied, replace the original chunk URL list
- `channel_urls`: optional HTTPS locations for future signed configuration updates

To change sources without an APK update, keep the same signing key, increase `revision`,
sign the new payload with `sign_download_channel.py` from the local build tools, and publish this file.
Only list mirrors that actually contain verified data. Changing a URL does not copy data to the new host.
Do not modify a published data version; publish a new version when file content changes.

Public key DER SHA-256:
`94a8fa4f4c711459e811b7751055a317e8b37dd3746760f76e7ef223b12ffbbf`

Configuration mirrors embedded in APK 1.7:

- https://raw.githubusercontent.com/Moatezsager/pes26ar-updates/main/channels/stable.signed.json
- https://cdn.jsdelivr.net/gh/Moatezsager/pes26ar-updates@main/channels/stable.signed.json

Cached signed configuration and the bundled baseline remain available if configuration hosts are unreachable.
Downloads still require a working data host. HTTP and HTTPS downgrades are rejected.
