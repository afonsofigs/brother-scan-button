# brother-scan-button

The scan button on Brother scanners, working on Linux and configured from a [NAPS2](https://www.naps2.com/) profile.

Put a page in and press the button. The scan is saved as PDF, JPEG, PNG or TIFF in the folder set in NAPS2. That folder can be local, on Google Drive, or another folder mounted in GNOME. A desktop notification shows the file name and the folder.

## How it works

```
scan button ─▶ brscan-skey (Brother) ─▶ brother-scan-button scan
                                              │
             NAPS2 profile ◀── reads ─────────┤  destination, format, dpi, colour, source, page size
                                              ├─▶ scanimage       scans, with scanner options such as
                                              │                   Brother's AutoDocumentSize and AutoDeskew
                                              └─▶ naps2 console   writes the file, with optional OCR
                                                     └─▶ local folder, or `gio copy` to a gvfs folder
```

Brother's `brscan-skey` daemon detects the button and runs this tool. The tool reads the NAPS2 profile, scans with `scanimage` and saves with `naps2 console`. Scanning through `scanimage` lets scanner-specific on/off options work, which NAPS2 8.3.2 and older don't apply.

## Requirements

| What | Where |
|---|---|
| The Brother SANE driver for your model (`brscan4`, `brscan5`...) | [support.brother.com](https://support.brother.com), your model, Downloads, Linux |
| `brscan-skey`, Brother's button daemon | [.deb](https://download.brother.com/welcome/dlf006652/brscan-skey-0.3.4-0.amd64.deb) or [.rpm](https://download.brother.com/welcome/dlf006650/brscan-skey-0.3.4-0.x86_64.rpm). It works with brscan4 and brscan5 models, including ones whose download page doesn't list it. |
| NAPS2 | The .deb or .rpm from [GitHub releases](https://github.com/cyanfish/naps2/releases), or `naps2-bin` from the AUR. The Flatpak ships its own SANE and can't see Brother's driver. |
| `scanimage` | Debian/Ubuntu `sane-utils`, Fedora and openSUSE `sane-backends`, Arch `sane` |
| `sudo`, Python 3.9+, a systemd user session | Standard on current distributions |
| `notify-send` | For notifications. Debian/Ubuntu `libnotify-bin`, Fedora and Arch `libnotify`, openSUSE `libnotify-tools` |
| `gio` | For Google Drive and network folders. Debian/Ubuntu `libglib2.0-bin`, Fedora and Arch `glib2`, openSUSE `glib2-tools`. GNOME installs it. |

Brother's Linux software is built for x86 only, so ARM computers such as a Raspberry Pi can't run it.

After installing the Brother driver, `scanimage -L` has to list the scanner for your normal user. If it doesn't, unplug the scanner and plug it back in so the driver's udev rule applies.

## Install

```sh
wget https://raw.githubusercontent.com/afonsofigs/brother-scan-button/main/brother-scan-button
python3 brother-scan-button setup
```

`curl -LO` works as well as `wget`. Run `setup` as your normal user and close NAPS2 first. `setup` then does the following:

1. Installs the tool as `~/.local/bin/brother-scan-button`.
2. Writes `~/.config/brother-scan-button/config.ini` and turns on `AutoDocumentSize` and `AutoDeskew` when the scanner has them.
3. Adds a NAPS2 profile called "Scan Button" that saves to `Scans/scan_<date>_<time>.pdf` in your Documents folder. The page size is Letter where the locale uses it and A4 elsewhere.
4. Points `/opt/brother/scanner/brscan-skey/brscan-skey.config` at the tool. This uses `sudo`, and the original file is kept as `brscan-skey.config.orig`.
5. Starts `brother-scan-button.service`, a systemd user service that runs `brscan-skey`.

Options:

- `--profile NAME` uses or creates another NAPS2 profile and records it in `config.ini`.
- `--device DEVICE` picks a scanner when there are several.
- `--force` takes over `brscan-skey.config` when it points at another user's copy.

`setup` stops when another `brscan-skey` listener is set up, such as a `brscan-skey` autostart entry, because every press would then scan twice. It prints how to stop that listener.

Running `setup` again is safe and keeps the configured profile. It's also how to update: download the new file and run `setup` again.

Then put a page in and press the scan button. `setup` says whether the page goes in the feeder or on the glass.

## Settings

Open NAPS2, then Profiles, then "Scan Button", then Edit. Changes apply from the next press.

| NAPS2 setting | Used by the button |
|---|---|
| Auto Save file path | Folder and file name. The extension sets the format: `.pdf`, `.jpg`, `.png` or `.tif`. Date placeholders work anywhere in the path: `$(YYYY) $(YY) $(MM) $(DD) $(hh) $(mm) $(ss)`. The counter `$(n)`, `$(nn)`, `$(nnn)` works in the file name. |
| Auto Save, file per page or per scan | Yes |
| Resolution | Yes, the nearest one the scanner supports |
| Bit depth: colour, greyscale, black and white | Yes |
| Paper source: glass, feeder, duplex | Yes. If the scanner lacks it, the closest source is used and the log says so. |
| Page size | Yes, unless `AutoDocumentSize` is on |
| Rotation, NAPS2's own auto-deskew | Yes |
| JPEG quality | From `config.ini` |
| Brightness, contrast, exclude blank pages | No. Use scanner options such as `SkipBlankPage=yes` in `config.ini`. |

An existing file is never replaced. A name that is taken gets ` (2)`, ` (3)` and so on, or the next counter number.

### Google Drive and network folders

In Files (Nautilus), open the folder, press Ctrl+L and copy the address. A Google Drive address such as `google-drive://you@gmail.com/0AB.../1CD...` can go straight into the profile, followed by the file name:

```
google-drive://you@gmail.com/0AB.../1CD.../scan_$(YYYY)-$(MM)-$(DD)_$(hh)-$(mm)-$(ss).pdf
```

The equivalent local path under `/run/user/<uid>/gvfs/` works as well, and it is what the NAPS2 folder picker gives.

Each file is saved locally first and then copied with `gio`. Missing folders are created. For Google Drive, the tool mounts the account again when the mount has dropped. When the account stays unmounted, the files go to the fallback folder. The uploads of one press get 20 minutes in total. A file that isn't copied in time stays in the fallback folder, `Scans/unsent` in your Documents folder, and the notification lists it. When the folder can't be listed, the files also go to the fallback folder, so that nothing there is overwritten.

To inspect a Drive folder from a terminal, use its `/run/user/...` path or the account root, `google-drive://you@gmail.com/`. GNOME mounts every `google-drive://you@gmail.com/<id>/...` sub-folder address separately, and Files then shows several Google Drives.

### config.ini

This is the file `setup` writes:

```ini
[general]
# NAPS2 profile used by the button
profile = Scan Button
# Scanners with a "Scan to" menu can use a profile per function
# profile_image =
# profile_ocr =
# profile_email =
# profile_file =

[scanner]
# Any option listed by `scanimage -d <device> -A`
options = AutoDocumentSize=yes AutoDeskew=yes
# Pages per press with a feeder; 0 means until empty, capped at 500
max_pages = 0

[output]
jpeg_quality = 90
# OCR language for PDFs, e.g. eng. Install it first: naps2 console --install ocr-eng
ocr_lang =
# Where scans go when the destination can't be reached
fallback_dir = ~/Documents/Scans/unsent
```

Scanner options can also go in the profile's `<KeyValueOptions>` in `~/.config/naps2/profiles.xml`, and those win over `config.ini`. NAPS2 8.3.2 removes them when the profile is edited in its window, so `config.ini` is the safer place.

`options` ignores the settings that come from the NAPS2 profile or from the tool itself: `source`, `mode`, `resolution`, the scan area (`x`, `y`, `l`, `t`), `format`, `device-name` and the `batch` options. `max_pages` accepts up to 1000.

Some feeder scanners have no `source` option. For those, set `max_pages` to more than 0 so that one press scans every page.

## Commands

```sh
brother-scan-button status          # checks the installation; exit status 1 if something is wrong
brother-scan-button scan --dry-run  # the scanimage command and target of a press, without scanning
brother-scan-button uninstall       # stops the service and restores brscan-skey.config
journalctl --user -u brother-scan-button -n 50   # output of the listener itself
brscan-skey -l                      # scanners that Brother's daemon knows about
```

`~/.local/bin` has to be on `PATH` for the short form. `setup` says when it isn't. The full path `~/.local/bin/brother-scan-button` always works.

The log is `~/.cache/brother-scan-button.log`. Every press adds a `scan requested` line. Then come `OK <file>` for files at the destination, `KEPT <file>` for files in the fallback folder, `WARNING` lines, or `FAILED: <reason>`. `RECOVERED` lines report pages of a killed scan moved to the fallback folder.

## Troubleshooting

- Nothing happens on a press, and the log has no `scan requested` line. Run `brother-scan-button status`. It checks the service, the number of listeners, `brscan-skey.config` and the profiles. `brscan-skey -l` must list the scanner. After an update of Brother's `brscan-skey` package, run `setup` again.
- The service stopped after repeated crashes. Start it again with `systemctl --user reset-failed brother-scan-button` and `systemctl --user start brother-scan-button`.
- "no paper in the scanner". Some scanners report an empty feeder as a jam.
- The scanner turns itself off when idle. Bus-powered models come back as a new USB device, which the listener picks up. The first press wakes the scanner.
- Scanning by hand, including `scan --dry-run`. The listener keeps the scanner open, so stop it first with `systemctl --user stop brother-scan-button`. Then run `brother-scan-button scan`, and start the listener again with `systemctl --user start brother-scan-button`. Stopping the listener interrupts a scan in progress.
- Network scanners. Register the scanner with Brother's tool (`brsaneconfig4 -a` or `brsaneconfig5 -a`), and allow UDP port 54925 in the firewall so button presses reach the computer. Only USB has been tested.
- Folders in the fallback folder. `pages_<date>` holds the raw pages of a scan that failed or was stopped before its file was saved. `interrupted_<date>` holds pages of a scan whose process was killed, recovered on the next press. When the fallback folder can't be written, the pages go to `~/brother-scan-button-rescue`. The notification and the log say where.

## Limitations

- One user per computer. `brscan-skey.config` is shared by the whole system and points at one user's `~/.local/bin/brother-scan-button`. Anyone else who runs `brscan-skey`, root included, runs that file with their own privileges. `setup --force` moves the button to another user.
- The button works while you're logged in, because the service runs in your session. For a headless machine, `loginctl enable-linger` keeps it running. Without a local login, USB access usually needs membership of the `scanner` group, and there are no notifications or gvfs folders.
- A missing OCR language makes NAPS2 save the PDF without text. The notification warns about it.
- A network folder that stops answering can hold a scan until the timeouts pass, and in rare cases longer. The button waits meanwhile. Folders on mounts outside GNOME, such as NFS, CIFS or rclone, have no timeout.
- On a gvfs folder, the free name is checked right before each copy, and `gio copy` then writes it. Another program writing the same name in that instant would be overwritten.
- When local delivery fails, the raw PNG pages are kept. When an upload fails, the finished files are kept.
- An upload attempt that breaks off can leave a partial file in the gvfs folder. The complete file is then in the fallback folder.
- Stopping the service during a very large scan can cut the rescue short after 60 seconds. The next press then recovers all the pages into an `interrupted_<date>` folder, so some of them are also in the partial `pages_<date>` folder.
- The tool relies on NAPS2's profile format and `naps2 console` options as of NAPS2 8.3.2.

## Tested with

| Scanner | Software | Notes |
|---|---|---|
| Brother DS-640, USB | brscan5 1.7.0, brscan-skey 0.3.4, NAPS2 8.3.2, Ubuntu 24.04 | Local folder and Google Drive |

Other brscan4 and brscan5 scanners, including ADS, DS and MFC models, should work the same way. Reports are welcome: open an issue with the output of `brother-scan-button status` and `scanimage -d <device> -A`.

The tests use SANE's virtual `test` scanner and need no hardware:

```sh
python3 -m unittest discover -s tests -v
```

## Licence

MIT. Not affiliated with Brother Industries.
