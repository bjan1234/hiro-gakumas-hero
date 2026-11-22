"""考试没过线时把再挑戦交给人：HIRO_RETRY_HANDOFF=1（hiro.loop.retry_handoff）。"""

from hiro.loop import pause_flag
from hiro.loop import retry_handoff as rh


class Rig:
    def __init__(self, tmp_path, delete_at=None, timeout="120"):
        self.t, self.delete_at = 0.0, delete_at
        self.env = {"HIRO_RETRY_HANDOFF": "1", "HIRO_RETRY_HANDOFF_TIMEOUT_S": timeout, "HIRO_WAIT_FILE": str(tmp_path / "w.txt"),
                    "HIRO_NOTIFY": "0"}  # fmt: skip
        self.path = tmp_path / "w.txt"
        self.paused = []

    def sleep(self, s):
        self.t += s
        self.paused.append(pause_flag.paused())
        if self.delete_at is not None and self.t >= self.delete_at:
            self.path.unlink(missing_ok=True)

    def run(self, here):
        return rh.wait("qualify-2", still_here=lambda: here, sleep=self.sleep, clock=lambda: self.t, notifier=lambda *a: None, env=self.env)


def test_switch_default_off():
    assert not rh.enabled({}) and rh.enabled({"HIRO_RETRY_HANDOFF": "1"})


def test_user_handled_returns_user(tmp_path):
    r = Rig(tmp_path, delete_at=30)
    assert r.run(here=False) == "user" and not r.path.exists()
    assert r.paused and all(r.paused)


def test_untouched_page_goes_back_to_program(tmp_path):
    assert Rig(tmp_path, delete_at=9).run(here=True) == "auto"


def test_timeout_goes_back_to_program(tmp_path):
    r = Rig(tmp_path, timeout="60")
    assert r.run(here=False) == "auto" and r.t >= 60 and not r.path.exists()
