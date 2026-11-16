"""Spike (step 2): read the sim variables the ATC needs via Python-SimConnect. MSFS must be running."""
import math
import time

from SimConnect import AircraftRequests, SimConnect

VARS = [
    "PLANE_LATITUDE",
    "PLANE_LONGITUDE",
    "PLANE_ALT_ABOVE_GROUND",
    "SIM_ON_GROUND",
    "PLANE_HEADING_DEGREES_MAGNETIC",
    "GROUND_VELOCITY",
    "COM_ACTIVE_FREQUENCY:1",
    "AMBIENT_WIND_DIRECTION",
    "AMBIENT_WIND_VELOCITY",
]


def main():
    sm = SimConnect()
    aq = AircraftRequests(sm, _time=200)
    print("Connected. Ctrl+C to stop. Report the raw values back, especially COM1 and heading units.")
    try:
        while True:
            values = {name: aq.get(name) for name in VARS}
            heading = values["PLANE_HEADING_DEGREES_MAGNETIC"]
            if heading is not None:
                values["heading_deg (if radians)"] = round(math.degrees(heading), 1)
            print(" | ".join(f"{k}={v}" for k, v in values.items()))
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        sm.exit()


if __name__ == "__main__":
    main()
