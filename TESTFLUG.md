# Testflug-Checkliste (Milestones 6 und 7)

Ein Flug **Hamburg (EDDH) → München (EDDM)** prüft alles, was seit Milestone 6 nur gegen Attrappen getestet ist:
LiveTraffic, Ausweichen am Boden, Wirbelschleppen, Taxi-Überwachung, Kabine, Co-Pilot und GSX.

Du musst nicht alles in einem Flug schaffen. Was nicht klappt oder fehlt, kreuzt du einfach als „nein“ an und schreibst
einen Satz dazu.

---

## 0. Vorbereitung (vor dem Flug)

- [ ] SimBrief-Plan EDDH → EDDM, mit einem Lufthansa- oder Eurowings-Callsign (dann kommt die Kabine auf Deutsch)
- [ ] MSFS gestartet, Flugzeug **an einem Gate in EDDH**, Motoren aus
- [ ] GSX Pro läuft (Couatl-Symbol in der Toolbar)
- [ ] LiveTraffic **nicht** von Hand starten: das soll die App selbst tun

**Erster Check ohne App** (im Projektordner, MSFS läuft, du stehst am Gate): 0 funktioniert alles

```
.venv\Scripts\python -m atc.sim.check --gsx-menu --tune 121.705
```

- [ ] Die Ausgabe zeigt eine Zeile `GSX: COUATL_STARTED=1, BOARDING_STATE=…` (und nicht „no answer for its L-vars“)
- [ ] Danach erscheint `GSX menu:` mit den Menüzeilen, und in MSFS geht das GSX-Menü auf
- [ ] Die letzte Zeile meldet `COM1 set to 121.705: now 121.705`, und im Cockpit steht COM1 auf 121.705

➡ **Die komplette Ausgabe kopierst du mir.** Das GSX-Menü in MSFS danach einfach schließen.

---

## 1. App starten

- [ja ] `start.bat` starten (Doppelklick)
- [ja ] LiveTraffic startet von selbst (falls es nicht schon lief)
- [ja ] Startbildschirm: „Load flight“ zeigt den SimBrief-Plan (Callsign, Route, Bahn, Wetter)
- [ ja] Flug starten: Der Karten-Tab lädt vollständig, ohne Hängen (das war der Avast-Fehler)
- [ja ] Nach ein paar Minuten: Auf der Karte sind LiveTraffic-Flugzeuge zu sehen

## 2. Am Gate

- [ja ] **Kabine, Boarding:** Gong, dann die Durchsage erst auf Deutsch, dann auf Englisch
- [zu laut aber mn kann sie ja selber leiser stellen ] Wie klingen Lautstärke und Stimme der Kabine neben ATC? (zu laut, zu leise, passt)
- [jo ] Freigabe: COM1 auf Hamburg Ground **121.705**, dann „Hamburg Ground, *Callsign*, request IFR clearance to
      Munich, information …“, Readback
- [ jo] GSX-Boarding starten (in GSX selbst). Wenn es fertig ist: Im Log steht „GSX: boarding completed“, und die
      Durchsage „Türen geschlossen“ kommt

## 3. Pushback (GSX)

- [ja ] „request push and start“, dann den Readback „push and start approved, facing …“
- [nein ] **Den GSX-Pushback nicht selbst bestellen:** Die App soll ihn nach deinem Readback von selbst anfordern
      (im Log: „GSX: pushback requested“)
- [nein ] Fragt GSX etwas (z. B. die Richtung), beantwortest du das im GSX-Menü. Im Log steht dann „GSX asks …“
- [ja ] Im Log steht „GSX: pushback started“ und später „finished“
- [ ja] Falls ein Flugzeug hinter dir rollt: kam „hold position, traffic passing behind“?

## 4. Rollen (Taxi-Überwachung)

- [ja ] „request **progressive** taxi“: Ground gibt die Route und sagt dann Abzweigungen an („turn left onto …“).
      In Hamburg sind viele Rollwege unbenannt, dann kommen nur wenige Ansagen.
- [ne ] **Einmal absichtlich falsch abbiegen:** Ground meldet „you appear to be on …, new route, …“. Die neue Route
      zurücklesen.
- [ja ] **Einmal kurz über 30 kt rollen:** Ground sagt „reduce taxi speed“
- [ ja] Gibt es beim normalen Rollen **falsche** „new route“-Meldungen, z. B. beim Abkürzen von Kurven oder auf dem
      Vorfeld? (wichtig: Die Grenze liegt bei 50 m neben der Route)
- [ja ] LiveTraffic auf deinem Weg: „give way to …“ / „follow …“ / „hold position“, und danach „continue taxi“
- [ ja] Vor einer Bahnkreuzung anhalten und „holding short runway …“ melden. Kommt „cross runway …“?

## 5. Start

- [ja ] Am Holding Point: Ground übergibt an den Tower, du meldest „ready for departure“
- [ noch nicht passiert] Ist kurz vorher ein Heavy gestartet oder gelandet? Dann: „expect departure in two minutes, wake turbulence“
      bzw. „caution wake turbulence from the …“
- [ ja ] **Kabine:** Die Ansage vor dem Start kommt

## 6. Steigflug: Co-Pilot am Funk

- [ ja ] „copilot, you have the radio“ (oder den Button „Co-pilot radio“)
- [ Co-Pilot macht garnuchts ] Bei der Übergabe an Departure: Der Co-Pilot liest zurück, **rastet COM1 im Cockpit um** und meldet sich
- [ja ] „I have the radio“: Du hast den Funk wieder
- [ja] **Kabine:** Durch 10.000 ft kommt die Steigflug-Durchsage

## 7. Reiseflug und Sinkflug

- [ ja ] Center-Übergaben kommen mit plausiblen Frequenzen
- [ kein bisschen ] Die Sinkflugfreigabe kommt rechtzeitig, die Kabine sagt den Sinkflug an

## 8. Anflug München

- [ ja ] Approach: Vectors oder STAR, dann die ILS-Freigabe
- [ ja ] Mit Verkehr vor dir: „number two, traffic to follow …“, eventuell eine Geschwindigkeitsanweisung
- [ ja  ] Die Landefreigabe kommt erst, wenn die Bahn frei ist
- [ja  ] **Kabine:** Die Landedurchsage kommt

## 9. Nach der Landung

- [ ich sollte direkt stoppen ich weiß nicht was los war ] „runway vacated“, Ground, „taxi to stand …“ (auch hier geht progressive taxi)
- [ jo aber nach dem arriven an einem gate kam nichts mehr. ] In München: Übergabe an Apron
- [ jo aber das debarding viel zu früh, die Motoren leifen noch ] Am Stand stehen bleiben: Die App fordert das GSX-Deboarding von selbst an (im Log: „GSX: deboarding requested“)
- [ ka. ] **Kabine:** Die Ankunftsdurchsage kommt

---

## Was ich danach von dir brauche

1. **Die Ausgabe des Check-Befehls** aus Schritt 0
2. **Das Flight Log:** Ordner `%LOCALAPPDATA%\MSFS ATC\logs`, die neueste `.txt`-Datei
3. **Diese Checkliste** mit deinen Haken und einem Satz zu allem, was nicht stimmte. Am besten mit der ungefähren
   Uhrzeit, dann finde ich es im Log.

Wenn die App abstürzt oder eine Fehlermeldung zeigt, kopiere den Text oder mache einen Screenshot.


Es kracht maximal mit dem descenden.
Dazu gibt es viel zu viele directs.
