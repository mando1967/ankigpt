# Local release artifacts

Copy locally generated installers and other distributable build artifacts into
this directory when you want to keep them with your working copy. Git ignores
the contents of this directory except for this README, so MSI files placed here
will not be committed or pushed.

The Windows MSI build normally writes its output to `out/installer/dist/`.
Copy the finished installer here for local safekeeping, or publish it as a
GitHub Release asset when it should be available to other users.
