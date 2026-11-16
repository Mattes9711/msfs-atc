"""R5: push-to-talk bindings: any key, a side mouse button or a joystick button, plus a spare."""
import pytest

from atc.audio import ptt
from atc.audio.voice import MicRecorder
from atc.config import Config
from atc import settings_file


@pytest.mark.parametrize("text, binding, name", [
    ("right ctrl", ptt.Binding("key", 0xA3), "Right Ctrl"),  # the old names still work
    ("key:0x20", ptt.Binding("key", 0x20), "Space"),
    ("KEY:0X70", ptt.Binding("key", 0x70), "F1"),
    ("key:6", ptt.Binding("key", 0x06), "Mouse button 5"),
    ("joy:0:5", ptt.Binding("joy", 0, 5), "Joystick 1 button 5"),
])
def test_bindings_read_and_named(text, binding, name):
    assert ptt.parse(text) == binding and binding.name == name and ptt.parse(binding.text) == binding


@pytest.mark.parametrize("text", ["space", "key:0x01", "key:0x10", "key:999", "joy:0:33", "joy:16:1", ""])
def test_unusable_bindings(text):
    with pytest.raises(ValueError, match="push-to-talk binding"):
        ptt.parse(text)


def test_held_by_key_or_joystick_button():
    keys = lambda vk: vk == 0x20
    joys = lambda device: 0b10000 if device == 1 else 0  # joystick 2, button 5
    assert ptt.is_held(ptt.parse("key:0x20"), keys, joys)
    assert ptt.is_held(ptt.parse("joy:1:5"), keys, joys) and not ptt.is_held(ptt.parse("joy:1:4"), keys, joys)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_capture_waits_for_release_then_takes_the_first_press():
    clock, down = Clock(), {0x0D}  # Enter still down from clicking "Set" with the keyboard

    def keys(vk):
        if clock.t > 0.1:
            down.discard(0x0D)
        if clock.t > 0.5:
            down.add(0x47)  # then the pilot presses G
        return vk in down

    found = ptt.capture(keys=keys, joysticks=lambda d: 0, clock=clock, sleep=clock.sleep)
    assert found == ptt.Binding("key", 0x47)


def test_capture_finds_a_joystick_button_and_gives_up_after_the_timeout():
    clock = Clock()
    joys = lambda device: (1 << 11) if device == 2 and clock.t > 1 else 0
    assert ptt.capture(keys=lambda vk: False, joysticks=joys, clock=clock, sleep=clock.sleep) == ptt.Binding("joy", 2, 12)
    clock = Clock()
    assert ptt.capture(timeout=2, keys=lambda vk: False, joysticks=lambda d: 0, clock=clock, sleep=clock.sleep) is None


def test_the_recorder_listens_to_the_spare_too():
    rec = MicRecorder("right ctrl", spare="joy:0:3", is_down=lambda vk: False, joysticks=lambda d: 0b100)
    assert rec.held()
    assert not MicRecorder("right ctrl", is_down=lambda vk: False, joysticks=lambda d: 0b100).held()


def test_the_settings_page_stores_bindings():
    config = settings_file.apply(Config(), {"whisper.ptt_key": "key:0x47", "whisper.ptt_key2": "joy:0:5"})
    assert (config.whisper.ptt_key, config.whisper.ptt_key2) == ("key:0x47", "joy:0:5")
    assert settings_file.apply(config, {"whisper.ptt_key2": ""}).whisper.ptt_key2 is None  # spare cleared


def test_a_switch_that_is_always_on_is_ignored():
    # Found on the user's PC: joystick 2 reported button 3 as held all the time (a switch on a yoke or throttle)
    clock = Clock()
    joys = lambda device: (0b100 | ((1 << 6) if clock.t > 2 else 0)) if device == 1 else 0
    found = ptt.capture(keys=lambda vk: False, joysticks=joys, clock=clock, sleep=clock.sleep)
    assert found == ptt.Binding("joy", 1, 7)  # the button really pressed, not the switch
