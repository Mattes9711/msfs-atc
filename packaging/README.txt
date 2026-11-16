MSFS ATC
========

Voice ATC for Microsoft Flight Simulator 2020: Clearance, Ground, Tower, Departure, Center, Approach, with ICAO
phraseology, push-to-talk and speech recognition, a co-pilot, cabin announcements, LiveTraffic and GSX Pro.
Everything runs on your own PC; no account, no subscription.

Start: "MSFS ATC.exe". Without MSFS, tick "Without MSFS (practice mode)" on the New flight screen.


What you need
-------------
- Windows 10 or 11, 64-bit, with the Microsoft Edge WebView2 Runtime (part of Windows 11; for Windows 10 free
  from Microsoft). Without it the app opens in your normal browser instead.
- Microsoft Flight Simulator 2020.
- Little Navmap with its MSFS database built (Little Navmap: Scenery Library > Load Scenery Library). MSFS ATC reads
  the airports, taxiways and frequencies of your own scenery from it.
- SimConnect.dll (Microsoft's, not included): MSFS ATC finds it by itself in the MSFS SDK or with an add-on that
  brings one along (GSX, or a program MSFS starts with itself). If it says it can't find one, install the MSFS SDK
  (free: MSFS Developer Mode > Help > SDK Installer), or set its path in Settings > Simulator.
- A microphone, and a key or joystick button for push-to-talk (Settings > Controls).


The first start
---------------
MSFS ATC downloads what it needs once, with progress in the radio log:
- the speech recognition model (whisper small.en, about 0.5 GB),
- the ATC voice (Piper, about 79 MB) and the German cabin voice (about 63 MB).
Until then you can type your transmissions.


Where your files are
--------------------
- Settings:  %APPDATA%\MSFS ATC\settings.toml  (or in the app: Settings)
- Models, cache, flight logs:  %LOCALAPPDATA%\MSFS ATC
MSFS ATC never writes into its own folder. To remove it, delete this folder and those two.


Licence
-------
MSFS ATC is free software under the GNU General Public License, version 3 or later (LICENSE.txt). It uses Piper
and espeak-ng, which are GPL-3.0. The source code: SOURCE_URL
The licences of the libraries it uses are in THIRD_PARTY_LICENSES.txt.

Voices: Piper with the LibriTTS-R voice (CC BY 4.0); German cabin voice by Thorsten Mueller (CC0).
Speech recognition: Whisper by OpenAI, faster-whisper by SYSTRAN (MIT).
Fonts: B612 and B612 Mono by Airbus and Intactile (SIL Open Font License 1.1).
Design values after unslop by Damir Sokolovsky (CC BY 4.0).
MSFS ATC is not made by or connected with Microsoft, Asobo, FSDreamTeam (GSX) or LiveTraffic.
