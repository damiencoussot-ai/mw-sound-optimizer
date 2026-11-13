import importlib.util
import math
import os
import types
import unittest

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "mw_sound_optimizer.py")
spec = importlib.util.spec_from_file_location("mwso", SRC)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def stub(**kw):
    """Objet minimal qui emprunte les methodes de App, sans ouvrir de fenetre."""
    s = types.SimpleNamespace(
        enabled=True, bypass=False, hp=0, gains=[float(x) for x in m.PRESETS["Pas / competitif"]],
        fcs=[float(b[1]) for b in m.BANDS], qs=[float(b[3]) for b in m.BANDS], intensity=1.0,
        width=0.0, level=0.0, balance=0.0, swap=False, target="all", auto_guid="")
    s.__dict__.update(kw)
    for name in ("eff", "coefs", "resolved", "apo_text"):
        setattr(s, name, getattr(m.App, name).__get__(s))
    return s


class Dsp(unittest.TestCase):
    def test_peaking_gain_at_center(self):
        c = m.biquad("PK", 2500, 4.0, 1.4)
        self.assertAlmostEqual(m.resp_db(c, 2500), 4.0, delta=0.05)

    def test_low_shelf_gain_far_below(self):
        c = m.biquad("LSC", 100, -5.0, 0.7)
        self.assertAlmostEqual(m.resp_db(c, 20), -5.0, delta=0.3)

    def test_highpass_cuts_low_end(self):
        c = m.biquad("HP", 90, 0, 0.7071)
        self.assertLess(m.resp_db(c, 30), -15)
        self.assertAlmostEqual(m.resp_db(c, 5000), 0.0, delta=0.1)


class GameDetection(unittest.TestCase):
    def test_matches(self):
        for n in ("cod.exe", "COD.EXE", "cod23-cod.exe", "ModernWarfare.exe", "BlackOpsColdWar.exe"):
            self.assertTrue(m.GAME_RE.match(n), n)

    def test_rejects(self):
        for n in ("code.exe", "chrome.exe", "codec.exe", "cod.exe.bak"):
            self.assertFalse(m.GAME_RE.match(n), n)


class ApoFile(unittest.TestCase):
    def test_competitive_default(self):
        txt = m.App.apo_text(stub())
        self.assertIn("Preamp: -5.2 dB", txt)
        self.assertEqual(txt.count("Filter "), 6)
        self.assertIn('regexSearch("capture", stage)', txt)
        self.assertNotIn("deviceGuid", txt)

    def test_all_tools(self):
        txt = m.App.apo_text(stub(hp=90, width=50.0, swap=True, balance=2.0, target="a9006f00-fff2"))
        self.assertIn("Preamp: -7.2 dB", txt)
        self.assertIn("Filter 1: ON HP Fc 90 Hz", txt)
        self.assertIn("Copy: L=1.250*R+-0.250*L R=1.250*L+-0.250*R", txt)
        self.assertIn("Channel: L\nPreamp: -2.0 dB\nChannel: all", txt)
        self.assertIn('regexSearch("a9006f00-fff2", tolower(deviceGuid))', txt)

    def test_disabled(self):
        self.assertEqual(m.App.apo_text(stub(enabled=False)).count("Filter"), 0)
        self.assertEqual(m.App.apo_text(stub(bypass=True)).count("Filter"), 0)

    def test_zero_bands_omitted(self):
        txt = m.App.apo_text(stub(gains=[0.0] * m.NB))
        self.assertEqual(txt.count("Filter "), 0)

    def test_gain_clamped(self):
        txt = m.App.apo_text(stub(gains=[20.0] + [0.0] * (m.NB - 1)))
        self.assertIn("Gain 12.0 dB", txt)


if __name__ == "__main__":
    unittest.main()
