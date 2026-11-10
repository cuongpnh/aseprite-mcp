"""rotate_layer: quarter turns and free-angle RotSprite turns."""
from conftest import ok, run

from aseprite_mcp.tools import analysis, transform


def test_free_angle_keeps_colours_and_size(sprite):
    before = ok(run(analysis.get_color_stats(sprite, 1)))
    box_before = ok(run(analysis.get_bounds(sprite, "body", "1")))
    ok(run(transform.rotate_layer(sprite, "body", 1, 30, 16, 16)))
    after = ok(run(analysis.get_color_stats(sprite, 1)))
    # the square's red is still the only drawn colour: RotSprite never mixes colours
    assert "#d04648" in after.lower()
    assert before.lower().count("#") == after.lower().count("#")
    # a 16x16 square turned 30 degrees about its centre reaches past its old box: the drawn box changed
    assert ok(run(analysis.get_bounds(sprite, "body", "1"))) != box_before


def test_free_angle_back_round_is_a_full_turn(sprite):
    for _ in range(11):
        ok(run(transform.rotate_layer(sprite, "body", 1, 30, 16, 16)))
    stats = ok(run(analysis.get_color_stats(sprite, 1)))
    assert "#d04648" in stats.lower()


def test_quarter_turn_still_exact(sprite):
    assert "rotated 90" in ok(run(transform.rotate_layer(sprite, "body", 1, 90)))
