"""End-to-end tests against SANE's virtual "test" scanner and the real NAPS2.

Needs `scanimage` (sane-utils), the SANE test backend (libsane1) and `naps2`.
Skipped automatically if any of them is missing.

    python3 -m unittest tests.test_integration -v
"""

import datetime as dt
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "brother-scan-button"
sys.path.insert(0, str(Path(__file__).parent))
from test_unit import bsb  # noqa: E402

# Stands in for `gio` on a gvfs destination. `copy` replaces existing files like the
# real one, and fails for names containing $FAKE_GIO_FAIL; `list` fails when
# $FAKE_GIO_LIST_FAIL is set.
FAKE_GIO = """#!/bin/sh
case "$1" in
  copy) if [ -n "$FAKE_GIO_FAIL" ]; then case "$(basename "$3")" in *"$FAKE_GIO_FAIL"*)
          echo "Operation not supported" >&2; exit 1;; esac; fi
        cp -f "$2" "$3" ;;
  list) [ -n "$FAKE_GIO_LIST_FAIL" ] && { echo "Timeout was reached" >&2; exit 1; }
        for f in "$4"/*; do [ -e "$f" ] && printf '%s\\t0\\t(regular)\\tstandard::display-name=%s\\n' \\
          "$(basename "$f")" "$(basename "$f")"; done; exit 0 ;;
  mkdir) shift; [ "$1" = -p ] && shift; mkdir -p "$@" ;;
  info) printf 'standard::display-name: %s\\n' "$(basename "$4")" ;;
  mount) ;;
esac
"""


def have_test_backend():
    if not (shutil.which("scanimage") and shutil.which("naps2")):
        return False
    with tempfile.TemporaryDirectory() as d:
        Path(d, "dll.conf").write_text("test\n")
        out = subprocess.run(["scanimage", "-L"], env={**os.environ, "SANE_CONFIG_DIR": d},
                             capture_output=True, text=True).stdout
    return "test:" in out


@unittest.skipUnless(have_test_backend(), "needs scanimage, the SANE test backend and naps2")
class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bsb-test-"))
        (self.tmp / "sane").mkdir()
        (self.tmp / "sane" / "dll.conf").write_text("test\n")
        self.out = self.tmp / "out"
        self.fallback = self.tmp / "unsent"
        home = self.tmp / "home"
        (home / ".config").mkdir(parents=True)
        # NAPS2 keeps logs and recovery data in $HOME/.config/naps2 (in the current
        # directory when $HOME/.config doesn't exist)
        self.env = {**os.environ,
                    "HOME": str(home),
                    "XDG_CONFIG_HOME": str(home / ".config"),
                    "XDG_CACHE_HOME": str(home / ".cache"),
                    "BSB_WORK": str(self.tmp / "work"),
                    "SANE_CONFIG_DIR": str(self.tmp / "sane"),
                    "BSB_CONFIG": str(self.tmp / "config.ini"),
                    "BSB_NAPS2_PROFILES": str(self.tmp / "profiles.xml"),
                    "BSB_LOG": str(self.tmp / "log"),
                    "BSB_LOCK": str(self.tmp / "lock"),
                    "BSB_NO_NOTIFY": "1"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def configure(self, path, source="Glass", bitdepth="C24Bit", separator="FilePerScan",
                  max_pages=0, extra_config=""):
        xml = bsb.profile_xml("Button", str(path), "test:0", "test", {}, source)
        xml = (xml.replace("<BitDepth>C24Bit<", f"<BitDepth>{bitdepth}<")
                  .replace("<Resolution>Dpi300<", "<Resolution>Dpi75<")
                  .replace("<Separator>FilePerScan<", f"<Separator>{separator}<"))
        Path(self.env["BSB_NAPS2_PROFILES"]).write_text(
            f'<?xml version="1.0" encoding="utf-8"?>\n<ArrayOfScanProfile>\n{xml}</ArrayOfScanProfile>\n')
        Path(self.env["BSB_CONFIG"]).write_text(
            f"[general]\nprofile = Button\n[scanner]\nmax_pages = {max_pages}\n"
            f"[output]\nfallback_dir = {self.fallback}\n{extra_config}")

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *args], env=self.env,
                              capture_output=True, text=True, timeout=300)

    def scan(self, expect_ok=True):
        r = self.run_tool("scan", "test:0")
        log = Path(self.env["BSB_LOG"]).read_text() if Path(self.env["BSB_LOG"]).exists() else ""
        self.assertEqual(r.returncode == 0, expect_ok, r.stderr + log)
        return [Path(p) for p in r.stdout.split("\n") if p], log

    def pdf_pages(self, f):
        out = subprocess.run(["pdfinfo", str(f)], capture_output=True, text=True).stdout
        return int(next(l.split()[-1] for l in out.splitlines() if l.startswith("Pages:")))

    def test_flatbed_pdf_at_profile_resolution(self):
        self.configure(self.out / "scan_$(YYYY)-$(MM)-$(DD).pdf")
        self.assertIn("--resolution 75", self.run_tool("scan", "--dry-run", "test:0").stdout)
        files, _ = self.scan()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].parent, self.out)
        self.assertRegex(files[0].name, r"^scan_\d{4}-\d{2}-\d{2}\.pdf$")
        if shutil.which("pdfinfo"):
            self.assertEqual(self.pdf_pages(files[0]), 1)

    def test_placeholders_in_folders(self):
        self.configure(self.out / "$(YYYY)" / "$(MM)" / "s.pdf")
        files, _ = self.scan()
        now = dt.datetime.now()
        self.assertEqual(files[0], self.out / now.strftime("%Y") / now.strftime("%m") / "s.pdf")

    def test_feeder_one_file(self):
        self.configure(self.out / "batch.pdf", source="Feeder", max_pages=3)
        files, _ = self.scan()
        self.assertEqual(len(files), 1)
        if shutil.which("pdfinfo"):
            self.assertEqual(self.pdf_pages(files[0]), 3)

    def test_feeder_file_per_page(self):
        self.configure(self.out / "page.pdf", source="Feeder", separator="FilePerPage", max_pages=3)
        self.assertEqual(len(self.scan()[0]), 3)

    def test_jpeg_gray_counter(self):
        self.configure(self.out / "img_$(nnn).jpg", bitdepth="Grayscale")
        files, _ = self.scan()
        self.assertEqual(files[0].name, "img_001.jpg")
        self.assertEqual(files[0].read_bytes()[:2], b"\xff\xd8")
        self.assertEqual(self.scan()[0][0].name, "img_002.jpg")

    def test_existing_file_not_overwritten(self):
        self.configure(self.out / "same.pdf")
        a, b = self.scan()[0][0], self.scan()[0][0]
        self.assertEqual((a.name, b.name), ("same.pdf", "same (2).pdf"))

    def test_unreachable_destination_keeps_pages(self):
        self.configure(Path("/proc/nope/scan.pdf"))
        _, log = self.scan(expect_ok=False)
        self.assertIn("FAILED", log)
        kept = list(self.fallback.glob("pages_*/page-0001.png"))
        self.assertEqual(len(kept), 1, log)

    def test_naps2_failure_keeps_pages(self):
        self.configure(self.out / "scan.docx")
        _, log = self.scan(expect_ok=False)
        self.assertIn("NAPS2 could not save", log)
        self.assertTrue(list(self.fallback.glob("pages_*/page-0001.png")))

    def test_invalid_config_fails_before_scanning(self):
        self.configure(self.out / "scan.pdf")
        with open(self.env["BSB_CONFIG"], "a") as f:
            f.write("[scanner]\n")  # duplicate section
        _, log = self.scan(expect_ok=False)
        self.assertIn("FAILED", log)
        self.assertNotIn("scanned", log)

    def fake_remote(self, **env):
        remote = self.tmp / "gvfs" / "drive"
        remote.mkdir(parents=True)
        bindir = self.tmp / "bin"
        bindir.mkdir()
        (bindir / "gio").write_text(FAKE_GIO)
        (bindir / "gio").chmod(0o755)
        self.env.update(BSB_REMOTE_PREFIX=str(self.tmp / "gvfs"), PATH=f"{bindir}:{os.environ['PATH']}", **env)
        return remote

    def test_remote_upload_failure_keeps_every_page(self):
        remote = self.fake_remote(FAKE_GIO_FAIL=".2.")
        self.configure(remote / "page.pdf", source="Feeder", separator="FilePerPage", max_pages=3)
        files, log = self.scan()
        self.assertEqual(sorted(p.name for p in remote.iterdir()), ["page.1.pdf", "page.3.pdf"])
        self.assertEqual([p.name for p in self.fallback.iterdir()], ["page.2.pdf"])
        self.assertIn("WARNING", log)
        self.assertEqual(len(files), 3)

    def test_remote_listing_failure_never_overwrites(self):
        remote = self.fake_remote(FAKE_GIO_LIST_FAIL="1")
        (remote / "scan_001.pdf").write_text("precious")
        self.configure(remote / "scan_$(nnn).pdf")
        files, log = self.scan()
        self.assertEqual((remote / "scan_001.pdf").read_text(), "precious")
        self.assertEqual(files, [self.fallback / "scan_001.pdf"])
        self.assertIn("could not be delivered", log)

    def test_remote_placeholder_folders_are_created(self):
        remote = self.fake_remote()
        self.configure(remote / "$(YYYY)" / "s.pdf")
        files, _ = self.scan()
        self.assertEqual(files, [remote / dt.datetime.now().strftime("%Y") / "s.pdf"])
        self.assertTrue(files[0].exists())

    def test_stopping_during_a_scan_keeps_the_pages(self):
        self.configure(self.out / "long.pdf", source="Feeder", max_pages=400)
        p = subprocess.Popen([sys.executable, str(TOOL), "scan", "test:0"], env=self.env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        work = self.tmp / "work"
        for _ in range(300):
            if list(work.glob("scan-*/page-0002.png")):
                break
            time.sleep(0.1)
        p.send_signal(signal.SIGTERM)
        p.communicate(timeout=60)
        self.assertEqual(p.returncode, 1)
        log = Path(self.env["BSB_LOG"]).read_text()
        self.assertIn("interrupted", log)
        self.assertTrue(list(self.fallback.glob("pages_*/page-0001.png")), log)
        self.assertEqual(list(work.glob("scan-*")), [])

    def test_pages_of_a_killed_scan_are_recovered(self):
        old = time.time() - 600
        for name in ("scan-a", "scan-b"):
            orphan = self.tmp / "work" / name
            orphan.mkdir(parents=True)
            (orphan / "page-0001.png").write_bytes(name.encode())
            os.utime(orphan / "page-0001.png", (old, old))
        busy = self.tmp / "work" / "scan-busy"  # still being written: left alone
        busy.mkdir()
        (busy / "page-0001.png").write_bytes(b"busy")
        self.configure(self.out / "s.pdf")
        _, log = self.scan()
        self.assertEqual(log.count("RECOVERED"), 2)
        kept = sorted(p.read_bytes() for p in self.fallback.glob("interrupted_*/page-0001.png"))
        self.assertEqual(kept, [b"scan-a", b"scan-b"])
        self.assertEqual([p.name for p in (self.tmp / "work").iterdir()], ["scan-busy"])


if __name__ == "__main__":
    unittest.main()
