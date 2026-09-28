"""Unit tests that need no scanner: python3 -m unittest discover -s tests"""

import datetime as dt
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

os.environ.setdefault("BSB_NO_NOTIFY", "1")
os.environ["BSB_LOG"] = os.path.join(tempfile.mkdtemp(prefix="bsb-unit-"), "log")  # never the user's log
ROOT = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("bsb", str(ROOT / "brother-scan-button"))
spec = importlib.util.spec_from_loader("bsb", loader)
bsb = importlib.util.module_from_spec(spec)
loader.exec_module(bsb)

# `scanimage -d 'brother5:bus2;dev1' -A` on a Brother DS-640 (brscan5 1.7.0)
DS640 = """
All options specific to device `brother5:bus2;dev1':
    --mode 24bit Color[Fast]|Black & White|True Gray|Gray[Error Diffusion] [24bit Color[Fast]]
        Select the scan mode
    --resolution 100|150|200|300|400|600|1200dpi [100]
        Sets the resolution of the scanned image.
    --source Automatic Document Feeder(left aligned) [Automatic Document Feeder(left aligned)]
        Selects the scan source (such as a document-feeder).
    --brightness -50..50% (in steps of 1) [inactive]
        Controls the brightness of the acquired image.
    --MultifeedDetection[=(yes|no)] [inactive]

    --AutoDocumentSize[=(yes|no)] [no] [advanced]

    --AutoDeskew[=(yes|no)] [no] [advanced]

    --SkipBlankPage[=(yes|no)] [no] [advanced]

    -l 0..215.9mm (in steps of 0.0999908) [0]
        Top-left x position of scan area.
    -x 0..215.9mm (in steps of 0.0999908) [215.88]
        Width of scan-area.
    -y 0..355.6mm (in steps of 0.0999908) [355.567]
        Height of scan-area.
"""

# `scanimage -d test -A` (SANE test backend, excerpt)
TEST_BACKEND = """
    --mode Gray|Color [Gray]
    --depth 1|8|16 [8]
    --resolution 1..1200dpi (in steps of 1) [0.000762939]
    --source Flatbed|Automatic Document Feeder [Flatbed]
    -x 0..200mm (in steps of 1) [80]
    -y 0..200mm (in steps of 1) [100]
"""

FLATBED_ONLY = """
    --mode Lineart|Gray|Color [Color]
    --resolution 75|150|300|600dpi [150]
    -x 0..215.9mm [215.9]
    -y 0..297mm [297]
"""


def parse(text):
    return bsb.parse_device_options(text)


def fake_run(text, returncode=0):
    return mock.patch.object(bsb, "run", return_value=mock.Mock(stdout=text, stderr="", returncode=returncode))


def profile(**kw):
    p = {"found": True, "path": "/tmp/x.pdf", "dpi": 300, "bitdepth": "C24Bit", "source": "Feeder",
         "pagesize": "A4", "custom_mm": None, "separator": "FilePerScan", "rotate": 0.0,
         "deskew": False, "options": {}}
    p.update(kw)
    return p


def config(options="", max_pages="0"):
    cfg = bsb.configparser.ConfigParser(interpolation=None)
    cfg.read_dict({"general": {"profile": "P"}, "scanner": {"options": options, "max_pages": max_pages},
                   "output": {"jpeg_quality": "90", "ocr_lang": "", "fallback_dir": "/tmp"}})
    return cfg


class DeviceOptions(unittest.TestCase):
    def test_ds640(self):
        o = parse(DS640)
        self.assertEqual(o["mode"], ["24bit Color[Fast]", "Black & White", "True Gray", "Gray[Error Diffusion]"])
        self.assertEqual(o["resolution"], ["100", "150", "200", "300", "400", "600", "1200dpi"])
        self.assertEqual(o["source"], ["Automatic Document Feeder(left aligned)"])
        self.assertEqual(o["AutoDocumentSize"], ["yes", "no"])
        self.assertEqual(o["brightness"], (-50.0, 50.0))
        self.assertEqual(o["x"], (0.0, 215.9))
        self.assertEqual(o["y"], (0.0, 355.6))

    def test_test_backend(self):
        o = parse(TEST_BACKEND)
        self.assertEqual(o["mode"], ["Gray", "Color"])
        self.assertEqual(o["resolution"], (1.0, 1200.0))
        self.assertEqual(o["source"], ["Flatbed", "Automatic Document Feeder"])


class Picking(unittest.TestCase):
    modes = ["24bit Color[Fast]", "Black & White", "True Gray", "Gray[Error Diffusion]"]

    def test_mode(self):
        self.assertEqual(bsb.pick_mode(self.modes, "C24Bit"), "24bit Color[Fast]")
        self.assertEqual(bsb.pick_mode(self.modes, "Grayscale"), "True Gray")
        self.assertEqual(bsb.pick_mode(self.modes, "BlackAndWhite"), "Black & White")
        self.assertEqual(bsb.pick_mode(["Lineart", "Gray", "Color"], "BlackAndWhite"), "Lineart")
        self.assertIsNone(bsb.pick_mode(["Gray", "Color"], "BlackAndWhite"))

    def test_source(self):
        s = ["Flatbed", "ADF Front", "ADF Duplex"]
        self.assertEqual(bsb.pick_source(s, "Glass"), "Flatbed")
        self.assertEqual(bsb.pick_source(s, "Feeder"), "ADF Front")
        self.assertEqual(bsb.pick_source(s, "Duplex"), "ADF Duplex")
        self.assertEqual(bsb.pick_source(["Automatic Document Feeder(left aligned)"], "Feeder"),
                         "Automatic Document Feeder(left aligned)")

    def test_choose_source_falls_back(self):
        self.assertEqual(bsb.choose_source(["Flatbed", "Automatic Document Feeder"], "Duplex"),
                         "Automatic Document Feeder")
        self.assertEqual(bsb.choose_source(["Flatbed"], "Feeder"), "Flatbed")
        self.assertIsNone(bsb.choose_source(None, "Feeder"))

    def test_resolution_list(self):
        r = ["100", "150", "200", "300", "400", "600", "1200dpi"]
        self.assertEqual(bsb.pick_resolution(r, 300), 300)
        self.assertEqual(bsb.pick_resolution(r, 250), 200)
        self.assertEqual(bsb.pick_resolution(r, 2400), 1200)

    def test_resolution_range(self):
        self.assertEqual(bsb.pick_resolution((1.0, 1200.0), 300), 300)
        self.assertEqual(bsb.pick_resolution((100.0, 1200.0), 300), 300)
        self.assertEqual(bsb.pick_resolution((75.0, 600.0), 1200), 600)
        self.assertEqual(bsb.pick_resolution((75.0, 600.0), 50), 75)
        self.assertEqual(bsb.pick_resolution(None, 300), 300)


class ScanimageArgs(unittest.TestCase):
    def args(self, device_text, prof, cfg):
        with fake_run(device_text):
            return bsb.scanimage_args("dev", prof, cfg)

    def test_ds640(self):
        args, count = self.args(DS640, profile(), config("AutoDocumentSize=yes AutoDeskew=yes"))
        self.assertIn("--AutoDocumentSize=yes", args)
        self.assertEqual(args[args.index("--resolution") + 1], "300")
        self.assertNotIn("-x", args)  # AutoDocumentSize replaces the page size
        self.assertEqual(count, bsb.SAFETY_MAX_PAGES)

    def test_max_pages(self):
        _, count = self.args(DS640, profile(), config(max_pages="3"))
        self.assertEqual(count, 3)

    def test_unmatched_source_is_bounded(self):
        args, count = self.args(TEST_BACKEND, profile(source="Duplex"), config())
        self.assertEqual(args[args.index("--source") + 1], "Automatic Document Feeder")
        self.assertEqual(count, bsb.SAFETY_MAX_PAGES)

    def test_flatbed_and_unknown_source_scan_one_page(self):
        _, count = self.args(TEST_BACKEND, profile(source="Glass"), config())
        self.assertEqual(count, 1)
        args, count = self.args(FLATBED_ONLY, profile(source="Feeder"), config())
        self.assertEqual(count, 1)
        self.assertEqual(args[args.index("-x") + 1], "210.0")

    def test_unsupported_option_ignored(self):
        args, _ = self.args(TEST_BACKEND, profile(), config("AutoDocumentSize=yes"))
        self.assertFalse(any("AutoDocumentSize" in a for a in args))

    def test_page_size_kept_when_auto_size_unsupported(self):
        args, _ = self.args(TEST_BACKEND, profile(source="Glass"), config("AutoDocumentSize=yes"))
        self.assertIn("-x", args)

    def test_no_source_option_uses_max_pages(self):
        _, count = self.args(FLATBED_ONLY.replace("Lineart|", ""), profile(), config(max_pages="5"))
        self.assertEqual(count, 5)

    def test_unreadable_scanner(self):
        with fake_run("", returncode=1), self.assertRaises(bsb.ScanError):
            bsb.device_options("dev")

    def test_reserved_options_ignored(self):
        args, count = self.args(TEST_BACKEND, profile(source="Feeder"), config("source=Flatbed mode=Gray"))
        self.assertEqual(args.count("--source"), 1)
        self.assertFalse(any(a.startswith(("--source=", "--mode=")) for a in args))
        self.assertEqual(count, bsb.SAFETY_MAX_PAGES)

    def test_bad_config(self):
        with self.assertRaises(bsb.ScanError):
            bsb.parse_option_string('AutoDeskew="yes')
        for key, value in (("max_pages", "all"), ("max_pages", "99999999999999999999"), ("max_pages", "1001"),
                           ("jpeg_quality", "high"), ("jpeg_quality", "101")):
            cfg = config()
            cfg.set("scanner" if key == "max_pages" else "output", key, value)
            with self.assertRaises(bsb.ScanError, msg=key):
                bsb.validate_config(cfg)


class Names(unittest.TestCase):
    now = dt.datetime(2026, 9, 28, 19, 5, 7)

    def test_dates_everywhere(self):
        self.assertEqual(bsb.resolve_target("/s/$(YYYY)/$(MM)/scan_$(DD)_$(hh)$(mm)$(ss)_$(nn).pdf", self.now),
                         "/s/2026/09/scan_28_190507_$(nn).pdf")

    def test_relative_and_google_drive_uri(self):
        self.assertTrue(bsb.resolve_target("x.pdf", self.now).endswith("/Scans/x.pdf"))
        self.assertEqual(bsb.resolve_target("google-drive://me@gmail.com/0AB/1CD/s.pdf", self.now),
                         f"/run/user/{os.getuid()}/gvfs/google-drive:host=gmail.com,user=me/0AB/1CD/s.pdf")

    def test_counter(self):
        self.assertEqual(bsb.final_names("img_$(nnn).jpg", [""], set()), ["img_001.jpg"])
        self.assertEqual(bsb.final_names("img_$(nnn).jpg", [""], {"img_001.jpg", "img_002.1.jpg"}), ["img_003.jpg"])
        self.assertEqual(bsb.final_names("p_$(n).pdf", [".1", ".2"], {"p_1.1.pdf"}), ["p_2.1.pdf", "p_2.2.pdf"])

    def test_no_counter_never_reuses_a_name(self):
        self.assertEqual(bsb.final_names("a.pdf", [""], {"a.pdf", "a (2).pdf"}), ["a (3).pdf"])
        self.assertEqual(bsb.final_names("Scan.pdf", [""], {"scan.pdf"}), ["Scan (2).pdf"])  # case-insensitive
        self.assertEqual(bsb.final_names("a.pdf", [".1", ".2"], set()), ["a.1.pdf", "a.2.pdf"])

    def test_place_local_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "a.pdf").write_text("old")
            src = Path(d, "src")
            src.write_text("new")
            dest = bsb.place_local(src, d, "a.pdf")
            self.assertEqual(os.path.basename(dest), "a (2).pdf")
            self.assertEqual(Path(d, "a.pdf").read_text(), "old")
            self.assertFalse(src.exists())


class ProfileXml(unittest.TestCase):
    def test_read_profile_and_escaping(self):
        xml = bsb.profile_xml("A&B <Button>", "/tmp/out & more/scan.pdf", "brother5:bus2;dev1", "DS-640",
                              {"Opt&1": 'x<"y">'})
        with tempfile.TemporaryDirectory() as d:
            f = Path(d, "profiles.xml")
            f.write_text(f'<?xml version="1.0"?>\n<ArrayOfScanProfile>\n{xml}</ArrayOfScanProfile>\n')
            with mock.patch.object(bsb, "NAPS2_PROFILES", f):
                p = bsb.read_profile("A&B <Button>")
                self.assertTrue(p["found"])
                self.assertEqual(p["path"], "/tmp/out & more/scan.pdf")
                self.assertEqual(p["options"], {"Opt&1": 'x<"y">'})
                self.assertFalse(bsb.read_profile("Other")["found"])

    def test_add_to_existing_and_empty_lists(self):
        block = bsb.profile_xml("New", "/tmp/s.pdf", "d", "d", {})
        for text in ('<?xml version="1.0"?>\n<ArrayOfScanProfile>\n</ArrayOfScanProfile>\n',
                     '<?xml version="1.0"?>\n<ArrayOfScanProfile />\n',
                     '<?xml version="1.0"?>\n<ArrayOfScanProfile xmlns:xsi="http://www.w3.org/2001/'
                     'XMLSchema-instance" />\n'):
            new = bsb.add_profile_to_xml(text, block)
            names = [p.findtext("DisplayName") for p in ET.fromstring(new.split("?>", 1)[1]).findall("ScanProfile")]
            self.assertEqual(names, ["New"], text)
        self.assertIsNone(bsb.add_profile_to_xml("<Something/>", block))


class SkeyConfig(unittest.TestCase):
    def test_rewrite(self):
        original = ('password=\nIMAGE="bash  /opt/x/scantoimage.sh"\nOCR="bash  /opt/x/scantoocr.sh"\n'
                    'EMAIL="bash  /opt/x/scantoemail.sh"\nFILE="bash  /opt/x/scantofile.sh"\nSEMID=b\n')
        new = bsb.rewrite_skey_config(original, lambda act: f"/home/u/.local/bin/tool scan --action {act.lower()}")
        self.assertIn('FILE="/home/u/.local/bin/tool scan --action file"', new)
        self.assertIn("password=\n", new)
        self.assertIn("SEMID=b", new)
        self.assertEqual(new.count("IMAGE="), 1)
        self.assertEqual(bsb.rewrite_skey_config(new, lambda act: f"/home/u/.local/bin/tool scan --action {act.lower()}"), new)

    def test_backslashes_are_literal(self):
        new = bsb.rewrite_skey_config("FILE=old\n", lambda act: r"C:\1\g<0>")
        self.assertIn(r'FILE="C:\1\g<0>"', new)

    def test_empty_file(self):
        new = bsb.rewrite_skey_config("", lambda act: "t")
        self.assertEqual(new, 'IMAGE="t"\nOCR="t"\nEMAIL="t"\nFILE="t"\n')


class ScanEnd(unittest.TestCase):
    def test_reason_skips_the_batch_summary(self):
        # stderr of `scanimage --batch` on a Brother DS-640 after one page
        err = ("scanimage: rounded value of br-x from 215.9 to 215.88\n"
               "Scanning page 2\n"
               "scanimage: sane_read: Document feeder out of documents\n"
               "Scanned page 2. (scanner status = 7)\n"
               "Batch terminated, 2 pages scanned\n")
        self.assertEqual(bsb.scan_end_reason(err), "scanimage: sane_read: Document feeder out of documents")
        self.assertRegex(bsb.scan_end_reason(err), bsb.END_OF_FEED_RE)
        self.assertEqual(bsb.scan_end_reason("Batch terminated, 1 pages scanned\n"), "")
        noisy = err + "libusb: warning [libusb_exit] device still referenced\n"
        self.assertEqual(bsb.scan_end_reason(noisy), "scanimage: sane_read: Document feeder out of documents")
        jam = "scanimage: sane_read: Document feeder jammed\nScanned page 3. (scanner status = 8)\n"
        self.assertEqual(bsb.scan_end_reason(jam), "scanimage: sane_read: Document feeder jammed")


class SetupHelpers(unittest.TestCase):
    def test_other_users_in_skey_config(self):
        text = 'FILE="/home/bob/.local/bin/brother-scan-button scan --action file"\n'
        self.assertEqual(bsb.skey_other_users(text), ["/home/bob/.local/bin/brother-scan-button"])
        mine = bsb.rewrite_skey_config("", bsb.skey_command)
        self.assertEqual(bsb.skey_other_users(mine), [])
        self.assertTrue(bsb.skey_points_here(mine))
        self.assertFalse(bsb.skey_points_here(mine.replace("OCR=", "#OCR=")))

    def test_set_config_profile(self):
        self.assertIn("profile = B", bsb.set_config_profile("[general]\nprofile = A\n", "B"))
        self.assertEqual(bsb.set_config_profile("[general]\n[scanner]\n", "B"), "[general]\nprofile = B\n[scanner]\n")
        self.assertTrue(bsb.set_config_profile("[scanner]\n", "B").startswith("[general]\nprofile = B\n"))
        self.assertEqual(bsb.set_config_profile("[general]\nProfile: A\n", "B"), "[general]\nprofile = B\n")
        self.assertEqual(bsb.set_config_profile("[general]\n  profile = A\n", "B"), "[general]\nprofile = B\n")

    def test_paper_size(self):
        self.assertEqual(bsb.local_paper_size("height=279\nwidth=216\n"), "Letter")
        self.assertEqual(bsb.local_paper_size("height=297\nwidth=210\n"), "A4")
        self.assertEqual(bsb.local_paper_size(""), "A4")

    def test_autostart(self):
        with tempfile.TemporaryDirectory() as system, tempfile.TemporaryDirectory() as user:
            entry = "[Desktop Entry]\nType=Application\nExec=brscan-skey\n"
            Path(system, "brscan.desktop").write_text(entry)
            Path(system, "other.desktop").write_text("[Desktop Entry]\nExec=foo --brscan-skey-like\n")
            Path(system, "stop.desktop").write_text("[Desktop Entry]\nExec=brscan-skey -t\n")
            found = bsb.autostart_entries([Path(system), Path(user)])
            self.assertEqual([f.name for f in found], ["brscan.desktop"])
            Path(user, "brscan.desktop").write_text(entry + "X-GNOME-Autostart-enabled=false\n")
            self.assertEqual(bsb.autostart_entries([Path(system), Path(user)]), [])
            Path(user, "brscan.desktop").write_text(entry + "Hidden=true\n")
            self.assertEqual(bsb.autostart_entries([Path(system), Path(user)]), [])

    def test_listener_hints(self):
        self.assertIn("startup settings", bsb.listener_hint(os.getuid(), "app-brscan\\x2dskey@autostart.service"))
        self.assertIn("brscan-skey -t", bsb.listener_hint(os.getuid(), "vte-spawn-1.scope"))
        self.assertIn("'x y.service'", bsb.listener_hint(os.getuid(), "x y.service"))
        self.assertIn("sudo systemctl disable", bsb.listener_hint(0, "brscan.service", system=True))
        self.assertIn("sudo kill 42", bsb.listener_hint(os.getuid() + 1, "user@1001.service", pid=42))

    def test_paths_with_spaces(self):
        with mock.patch.object(bsb, "INSTALL_PATH", Path("/home/a b/.local/bin/brother-scan-button")):
            mine = bsb.rewrite_skey_config("", bsb.skey_command)
            self.assertTrue(bsb.skey_points_here(mine))
            self.assertEqual(bsb.skey_other_users(mine), [])
        self.assertEqual(bsb.skey_other_users(mine), ["/home/a b/.local/bin/brother-scan-button"])

    def test_tilde(self):
        home = str(bsb.HOME)
        self.assertEqual(bsb.tilde(home + "/Documents/x"), "~/Documents/x")
        self.assertEqual(bsb.tilde(home + "x/y"), home + "x/y")
        self.assertEqual(bsb.tilde("/srv" + home), "/srv" + home)

    def test_rescue_folders_never_merge(self):
        with tempfile.TemporaryDirectory() as d:
            pages = []
            for i, content in enumerate(("FIRST", "SECOND")):
                src = Path(d, f"src{i}")
                src.mkdir()
                (src / "page-0001.png").write_text(content)
                pages.append([src / "page-0001.png"])
            cfg = config()
            cfg.set("output", "fallback_dir", str(Path(d, "fb")))
            a, b = (bsb.rescue_pages(p, cfg, "interrupted") for p in pages)
            self.assertNotEqual(a, b)
            self.assertEqual({Path(a, "page-0001.png").read_text(), Path(b, "page-0001.png").read_text()},
                             {"FIRST", "SECOND"})


if __name__ == "__main__":
    unittest.main()
