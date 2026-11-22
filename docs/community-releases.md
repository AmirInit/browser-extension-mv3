# Community-patched Windscribe builds

**UNOFFICIAL COMMUNITY BUILD — NOT AFFILIATED WITH OR ENDORSED BY WINDSCRIBE.**

These are unsigned, unpacked Chromium extensions built by this fork. They are
not Chrome Web Store releases, do not auto-update, and have not been reviewed
or endorsed by Windscribe. Every automated release is a **prerelease**. Tests
cannot prove that authentication, all proxy routes, WebRTC leak protection,
filtering, or other privacy features work. Validate a candidate independently
before relying on it. A browser extension proxy is not a system-wide VPN.

## Monitoring and build

The [workflow](../.github/workflows/community-patch-release.yml) runs every
Monday at 04:31 UTC and can also be started from Actions → **Community patched
extension** → **Run workflow**, on the `public` branch. It examines Windscribe's
`public` branch, branch list, tags, exact commit, `package.json`, and
`src/manifest.json`. A newer numeric official tag is selected only if its
package and manifest versions agree and its commit descends from the selected
public source; ambiguous tags fail safely. Experimental branch heads are
reported but are not automatically built. A fingerprint covers the source tree except documentation;
a changed commit with an unchanged version still triggers a build if the
fingerprint changes. A complete existing release for the same source and
patch fingerprint is skipped. Select **force_build** to create a new revision
intentionally. Existing tags, releases, and assets are never overwritten.

On GitHub's public repositories, scheduled workflows can be automatically
disabled after 60 days without repository activity. GitHub also describes
scheduled runs as best effort; they may be delayed. Check the workflow's state
in the Actions tab and re-enable it if necessary. A manual run remains available.
See [GitHub's scheduled-event documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

The candidate is checked out from the exact official commit, not from the
fork's default-branch extension source. The reviewed Redux patch and build-data
support are applied in a disposable checkout. If upstream appears to contain an
independent equivalent fix, the pipeline runs the trusted transport tests
against that upstream dependency; ambiguous changes fail rather than suppressing
messaging. Changes to content-script/Redux wiring, the uBO submodule, its origin,
permissions, incompatible patch contexts, or an incomplete audit require manual
review. The current uBO commit is kept as-is; future uBO changes require the
checklist in the upstream repository's `docs/ubo-lite-mirror.md`.

Build-time warp metadata comes from Windscribe's publicly accessible Chrome
location endpoints on its official primary CDN or documented fallback. The
pipeline fetches the free and Pro lists, retains only IDs, country codes, time
zones, and coordinates, requires them to agree, and requires recent HTTP
`Date`, `Last-Modified`, and `Age` headers. It aborts if metadata is unavailable,
stale, inconsistent, or invalid. These checks do not prove that an
account-specific location set is complete. No account credentials, user
sessions, browsing data, or private location export are used in CI. Runtime
Windscribe login is unchanged.

The current 4.3.1 overlay updates the lockfile for known critical advisories in
`crypto-js`, `@babel/traverse`, `basic-ftp`, `loader-utils`, `proxy-addr`,
`websocket-driver`, and `webpack`. It is a change
from the previously installed local build and needs its own authenticated
validation. The full dependency audit must complete with **zero critical**
findings; lower-severity findings, including high-severity findings, remain
visible in each release's `BUILD-INFO.json`, including unique high-severity
advisory IDs. A passed audit is not a security
certification. Critical failures preserve the previous release and leave the
workflow failed.

Dependency installation uses a frozen lockfile and disables lifecycle scripts.
Upstream build and test code runs in a constrained container with no GitHub
release credentials; the test/build container has no network. Generated-script validator errors,
which upstream currently logs without failing its build, also block publication. A second offline, read-only container
loads the built extension in Chrome for Testing 131, checks its popup, Redux
state and enabled filtering rulesets, and stops and reactivates its MV3 worker.
The separate
publishing job has `contents: write`, does not run candidate code, verifies the
current run's artifact ID and SHA-256 against GitHub's artifact API, checks the
archive and manifest, creates a new tag atomically, creates a draft, verifies
all uploaded asset digests, and only then publishes the prerelease. An artifact
hash binds data to the run; it is not an independent source audit or a signed
software attestation. Actions and the build image are pinned by digest.

## Install and verify a prerelease

1. Download `windscribe-community.zip`, `SHA256SUMS`, `CHANGELOG.md`, and
   `BUILD-INFO.json` from a prerelease in this fork. In the download directory,
   run `sha256sum --check SHA256SUMS`. The checksum detects transfer errors; a
   checksum from the same release is not an independent signature.
2. Extract the archive into a **new, empty** directory and load that directory
   via Vivaldi's Extensions page → Developer mode → **Load unpacked**. Use an
   isolated browser profile for initial testing. Do not remove or reset an
   existing extension or profile. A separately loaded directory usually has a
   different extension ID and separate settings and sign-in.
3. Sign in normally, check the intended proxy route and privacy settings, test
   WebRTC and filtering relevant to your use, and restart the test browser.
   Never put credentials into GitHub issues or build logs.

## Updating an existing unpacked installation

Do not simply load a new folder into a working profile and assume it will use
the same extension storage: unpacked extension IDs depend on the manifest key
or on the installed path. A changed ID means a separate extension and storage.

After validating a candidate in isolation, gracefully close Vivaldi. Back up
the existing **extension program directory** to a new, uniquely named private
backup; do not touch the browser profile or extension storage. Stage the new
archive in a new directory on the same filesystem. Move the existing program
directory intact to the private backup and move the validated staged directory
to the **same original absolute path**. Preserve the old directory for rollback.
Restart Vivaldi, confirm that the extension ID and its settings are unchanged,
and repeat the connection and privacy checks. A changed manifest key or browser
behavior can still change identity; if it does, restore the prior program
directory rather than deleting or migrating extension storage. Never overwrite
an existing backup.

For the original local repair, the stable program path is
`~/.local/share/windscribe-custom-builds/4.3.1-7d3bead-993zszht/extension`.
The pipeline does not read, write, replace, or update this directory.

To roll back a program update, close Vivaldi, move the new program directory to
a new unique location, and restore the backed-up program directory at the
original path. Alternatively, disable the custom extension in Vivaldi and
re-enable the still-installed official extension. Do not uninstall either or
clear its storage. Proxy-controlling extensions can conflict; avoid enabling
multiple proxy controllers simultaneously.

## Maintenance

The workflow definitions and verified patch overlays live on the fork's
`public` branch; the existing performance branch and upstream PR are separate.
If an upstream source, submodule, dependency, API, or manifest change makes
an overlay incompatible, the workflow fails safely. Review the failing run,
update the overlay and tests in a feature branch, review the lockfile and uBO
checklist, then merge without rewriting existing branches. No stale server list,
credentials, personal profiles, or browsing data should be committed.
