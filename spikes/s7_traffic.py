"""Spike (step 7): yes/no check whether FSLTL aircraft appear in SimConnect's AI object list, via raw ctypes."""
import argparse
import ctypes
import struct
import time
from ctypes import wintypes
from pathlib import Path

import SimConnect as simconnect_pkg

DLL = Path(simconnect_pkg.__file__).parent / "SimConnect.dll"
DATATYPE_FLOAT64, DATATYPE_STRING64, DATATYPE_STRING256 = 4, 7, 9
SIMOBJECT_TYPE_ALL, SIMOBJECT_TYPE_AIRCRAFT = 1, 2
RECV_ID_EXCEPTION, RECV_ID_OPEN, RECV_ID_QUIT, RECV_ID_SIMOBJECT_DATA_BYTYPE = 1, 2, 3, 9
DEFINE_ID, REQUEST_ID = 1, 1
UNUSED = ctypes.c_uint32(0xFFFFFFFF)
HEADER_SIZE = 40  # SIMCONNECT_RECV (3 DWORDs) + 7 DWORDs of SIMOBJECT_DATA fields

DOUBLES = [("PLANE LATITUDE", "degrees"), ("PLANE LONGITUDE", "degrees"),
           ("PLANE ALTITUDE", "feet"), ("SIM ON GROUND", "bool"), ("GROUND VELOCITY", "knots")]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--radius-km", type=float, default=20, help="max 200")
    p.add_argument("--all-types", action="store_true", help="every sim object, not only aircraft")
    args = p.parse_args()

    dll = ctypes.WinDLL(str(DLL))
    handle = wintypes.HANDLE()
    if dll.SimConnect_Open(ctypes.byref(handle), b"atc-traffic-spike", None, 0, None, 0) != 0:
        raise SystemExit("SimConnect_Open failed. Is MSFS running?")

    for name, unit in DOUBLES:
        dll.SimConnect_AddToDataDefinition(handle, DEFINE_ID, name.encode(), unit.encode(),
                                           DATATYPE_FLOAT64, ctypes.c_float(0), UNUSED)
    dll.SimConnect_AddToDataDefinition(handle, DEFINE_ID, b"ATC ID", None,
                                       DATATYPE_STRING64, ctypes.c_float(0), UNUSED)
    dll.SimConnect_AddToDataDefinition(handle, DEFINE_ID, b"TITLE", None,
                                       DATATYPE_STRING256, ctypes.c_float(0), UNUSED)
    dll.SimConnect_RequestDataOnSimObjectType(handle, REQUEST_ID, DEFINE_ID,
                                              int(args.radius_km * 1000),
                                              SIMOBJECT_TYPE_ALL if args.all_types else SIMOBJECT_TYPE_AIRCRAFT)

    data_ptr = ctypes.POINTER(ctypes.c_byte)()
    size = wintypes.DWORD()
    deadline = time.time() + 5
    seen = 0
    while time.time() < deadline:
        if dll.SimConnect_GetNextDispatch(handle, ctypes.byref(data_ptr), ctypes.byref(size)) != 0:
            time.sleep(0.05)
            continue
        raw = ctypes.string_at(data_ptr, size.value)
        recv_id = struct.unpack_from("<I", raw, 8)[0]
        if recv_id == RECV_ID_EXCEPTION:
            print("SimConnect exception:", struct.unpack_from("<III", raw, 12))
        elif recv_id == RECV_ID_SIMOBJECT_DATA_BYTYPE:
            object_id, entry, out_of = (struct.unpack_from("<I", raw, o)[0] for o in (16, 28, 32))
            lat, lon, alt, on_ground, gs = struct.unpack_from("<5d", raw, HEADER_SIZE)
            atc_id = raw[HEADER_SIZE + 40:HEADER_SIZE + 104].split(b"\0")[0].decode(errors="replace")
            title = raw[HEADER_SIZE + 104:HEADER_SIZE + 360].split(b"\0")[0].decode(errors="replace")
            print(f"[{entry}/{out_of}] obj {object_id} {atc_id:8} {lat:.4f},{lon:.4f} "
                  f"{alt:.0f} ft ground={bool(on_ground)} {gs:.0f} kt  {title}")
            seen += 1
    dll.SimConnect_Close(handle)
    print(f"{seen} aircraft within {args.radius_km} km (includes your own). "
          "FSLTL aircraft usually have 'FSLTL' in the title.")


if __name__ == "__main__":
    main()
