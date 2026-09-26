# Study Hub guide

This guide describes the features in source version 26.08.2. Installing an
older release may show a different interface.

## Concepts and Card Library

**Concepts** groups concepts into expandable deck sections, sorted by deck
name. Each section shows its entry count. Subdecks display their full names,
such as `Science::Geology`. When several decks are listed, their sections
start collapsed; a single deck starts expanded.

Search matches deck names, concept titles, and descriptions. Matching sections
open automatically and other sections disappear. Clearing the search restores
the sections' previous expansion state.

Click a concept to view or edit its title, description, key points, and visual
aid. Back, Cancel, Save, and the Concepts sidebar return to the list you opened
it from: all decks or a particular deck. Titles and description previews wrap
to fit the cards; open the editor to read the full description.

**Card Library** uses the same deck sections. Search matches deck names, note
previews, and note types. Click an entry to edit its fields, or choose **Add
card** to create a note. The library currently displays the newest 500 notes;
its counts and search apply to that loaded set. Notes with multiple cards are
listed once, under the deck of their first card.

## Focus sessions

In Study, enable focus mode and choose a card goal and an optional timer before
starting. The reviewer displays progress and provides a break control. Pausing
excludes break time from the session timer and prevents answering while paused.

The session finishes after rating a card when the goal or time limit has been
reached. A recap also appears when the session ends early or runs out of cards.
Focus sessions are temporary and do not resume after closing the application.

## Background audio

Open the audio controls while studying to choose a local audio file or generated
white, pink, or brown noise. Playback loops and has its own volume and mute
controls. **Start this sound with focus sessions** is optional. Local background
audio pauses during focus breaks and stops when leaving the reviewer.

The myNoise choices are website bookmarks. Use **Open in app** to visit a sound
page in a browser tab, or open it in your external browser. AnkiGPT does not
bundle or download myNoise sound libraries. Website playback is controlled by
the site; the local audio volume, break, and session controls do not control it.

## Browser tabs and bookmarks

Choose **Web browser** from the sidebar to open a browser tab alongside Study.
Enter an HTTP or HTTPS address, use the navigation buttons, or open a bookmark.
Default bookmarks include **myNoise** and **How to Study** (`how-to-study.com`).
You can add and remove bookmarks, open more tabs, mute a tab, save downloads,
or open the current page externally.

Website audio can continue when returning to Study. Switching to a browser tab
pauses an active focus session; returning resumes it only if the browser caused
the pause. A session you paused manually stays paused.

Bookmarks persist in the profile. Browser cookies and sign-ins are temporary
and are cleared when the browser profile is disposed, including on profile
close. Websites run separately from Anki's internal page bridge. External sites
retain their own terms, account requirements, and privacy policies.

## Storage and backups

The default Windows profile directory is:

```text
%APPDATA%\Anki2\<profile name>\
```

For example, the default `User 1` profile is under
`C:\Users\<Windows user>\AppData\Roaming\Anki2\User 1\`.
A custom base directory supplied when launching the application changes this
location.

| File or folder | Contents |
| --- | --- |
| `collection.anki2` | Decks, notes, cards, and scheduling data |
| `collection.media/` | Card images, audio, and other media |
| `ankigpt.sqlite` | Additional AnkiGPT source and study data |
| `backups/` | Anki collection backups |

Close AnkiGPT before copying an entire profile folder for a manual backup.
Automatic collection backups are not a complete copy of the profile's media
and AnkiGPT sidecar database. Recompiling the application normally does not
change these profile files.

## Building version 26.08.2

The root [`.version`](../../.version) file supplies the application build version.
The Windows MSI workflow can override it through its version input or release
tag. Follow the [README build instructions](../../README.md#building-from-source)
to build locally; generated installers are placed in `out/installer/dist/`.
A source version bump does not by itself publish a new installer.
