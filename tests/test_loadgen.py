from loadgen.openloop import Phase, phase_at


def test_phase_at():
    phases = [
        Phase(until_s=10, rps=1, prompt_class="short"),
        Phase(until_s=20, rps=2, prompt_class="long"),
    ]
    assert phase_at(phases, 0).prompt_class == "short"
    assert phase_at(phases, 10).prompt_class == "long"
    assert phase_at(phases, 99).rps == 2
