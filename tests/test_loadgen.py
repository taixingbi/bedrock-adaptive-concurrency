from loadgen.openloop import Phase, phase_at, pick_prompt_class


def test_phase_at():
    phases = [
        Phase(until_s=10, rps=1, prompt_class="short"),
        Phase(until_s=20, rps=2, prompt_class="long"),
    ]
    assert phase_at(phases, 0).prompt_class == "short"
    assert phase_at(phases, 10).prompt_class == "long"
    assert phase_at(phases, 99).rps == 2


def test_pick_prompt_class_mix_is_deterministic_with_seed():
    import random

    phase = Phase(until_s=1, mix={"short": 1.0, "long": 0.0})
    random.seed(0)
    assert pick_prompt_class(phase) == "short"
    phase_long = Phase(until_s=1, prompt_class="short", mix={"short": 0.0, "long": 1.0})
    assert pick_prompt_class(phase_long) == "long"
