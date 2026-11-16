"""The flight and GSX Pro together (Milestone 7, C3 and C4).

Every few seconds GSX's state is read (atc/sim/gsx.py). Its boarding finishing gives the cabin's doors-closed
announcement; its pushback starting and finishing are noted in the log. With control on, the app asks GSX for the
pushback once ATC's "push and start approved" has been read back, and for deboarding once the aircraft stands at
its stand after the flight; each once, and only when GSX offers the service (state "available"), so a service the
pilot ordered in GSX himself is left alone. The menu clicks run in a thread: they take a few seconds.
"""
import threading
import time
from typing import Callable

from atc.airport.geo import distance_nm
from atc.events import Event, Sink
from atc.sim import gsx
from atc.sim.traffic import M_PER_NM

READ_EVERY_S = 2
AT_STAND_M = 40
STOPPED_KT = 1


class GsxLink:
    def __init__(self, sim, control: bool = True, clock: Callable[[], float] = time.monotonic,
                 menu: gsx.GsxMenu | None = None, background: Callable[[Callable[[], None]], None] | None = None):
        self.sim, self.control, self.clock = sim, control, clock
        self.menu = menu or gsx.GsxMenu(sim.set_lvar)
        self.background = background or (lambda job: threading.Thread(target=job, daemon=True).start())
        self.state: gsx.GsxState | None = None
        self.next_read = 0.0
        self.requested: set[str] = set()

    def step(self, controller, aircraft, sink: Sink) -> gsx.GsxState | None:
        """GSX's state now (None while GSX isn't running), after acting on it."""
        if self.clock() < self.next_read:
            return self.state
        self.next_read = self.clock() + READ_EVERY_S
        before, self.state = self.state, gsx.state_from_lvars(self.sim.gsx_values())
        now = self.state
        if now is None:
            return None
        if before is not None:
            if now.boarding_done and not before.boarding_done:
                sink.emit(Event("notice", "GSX: boarding completed"))
            if now.pushing and not before.pushing:
                sink.emit(Event("notice", "GSX: pushback started"))
            if now.departure == gsx.COMPLETED and before.departure != gsx.COMPLETED:
                sink.emit(Event("notice", "GSX: pushback finished"))
        if self.control:
            if (controller.phase == "pushback" and not controller.pending and now.departure == gsx.AVAILABLE):
                self._request("pushback", sink)
            if (controller.phase == "taxi_in" and aircraft is not None and self._at_stand(controller, aircraft)
                    and now.deboarding == gsx.AVAILABLE):
                self._request("deboarding", sink)
        return now

    def _request(self, service: str, sink: Sink) -> None:
        if service in self.requested:
            return
        self.requested.add(service)
        self.background(lambda: sink.emit(Event("notice", self.menu.request(service))))

    @staticmethod
    def _at_stand(controller, aircraft) -> bool:
        stand = controller.stand_in
        return (stand is not None and aircraft.ground_speed_kt < STOPPED_KT
                and distance_nm(stand.lat, stand.lon, aircraft.lat, aircraft.lon) * M_PER_NM <= AT_STAND_M)
