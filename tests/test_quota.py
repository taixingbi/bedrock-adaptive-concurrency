from analysis.quota import envelope, published_envelopes, tpm_at_rps, warn_rps


def test_short_rpm_binds():
    env = published_envelopes()["short"]
    assert env["tokens_per_request"] == 640
    assert abs(env["rps_rpm"] - 800 / 60) < 1e-9
    assert abs(env["rps_tpm"] - 600000 / (640 * 60)) < 1e-9
    assert env["binding"] == "rpm"
    assert abs(env["rps_cap"] - 800 / 60) < 1e-9


def test_long_tpm_binds():
    env = published_envelopes()["long"]
    assert env["tokens_per_request"] == 4608
    assert env["binding"] == "tpm"
    assert abs(env["rps_cap"] - 600000 / (4608 * 60)) < 1e-6
    assert env["rps_cap"] < 3.0


def test_same_rps_blows_long_tpm():
    rps = 0.9 * (800 / 60)
    assert tpm_at_rps(rps, 512, 128) < 600000
    assert tpm_at_rps(rps, 4096, 512) > 600000
    assert warn_rps(rps, "long") is not None


def test_envelope_custom():
    env = envelope(512, 128, rpm=800, tpm=600000)
    assert env["binding"] == "rpm"
