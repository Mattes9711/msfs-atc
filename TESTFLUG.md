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

**Erster Check ohne App** (im Projektordner, MSFS läuft, du stehst am Gate):

```
.venv\Scripts\python -m atc.sim.check --gsx-menu --tune 121.705
```

- [ ] Die Ausgabe zeigt eine Zeile `GSX: COUATL_STARTED=1, BOARDING_STATE=…` (und nicht „no answer for its L-vars“)
- [ ] Danach erscheint `GSX menu:` mit den Menüzeilen, und in MSFS geht das GSX-Menü auf
- [ ] Die letzte Zeile meldet `COM1 set to 121.705: now 121.705`, und im Cockpit steht COM1 auf 121.705

➡ **Die komplette Ausgabe kopierst du mir.** Das GSX-Menü in MSFS danach einfach schließen.

---

## 1. App starten

- [ ] `start.bat` starten (Doppelklick)
- [ ] LiveTraffic startet von selbst (falls es nicht schon lief)
- [ ] Startbildschirm: „Load flight“ zeigt den SimBrief-Plan (Callsign, Route, Bahn, Wetter)
- [ ] Flug starten: Der Karten-Tab lädt vollständig, ohne Hängen (das war der Avast-Fehler)
- [ ] Nach ein paar Minuten: Auf der Karte sind LiveTraffic-Flugzeuge zu sehen

## 2. Am Gate

- [ ] **Kabine, Boarding:** Gong, dann die Durchsage erst auf Deutsch, dann auf Englisch
- [ ] Wie klingen Lautstärke und Stimme der Kabine neben ATC? (zu laut, zu leise, passt)
- [ ] Freigabe: COM1 auf Hamburg Ground **121.705**, dann „Hamburg Ground, *Callsign*, request IFR clearance to
      Munich, information …“, Readback
- [ ] GSX-Boarding starten (in GSX selbst). Wenn es fertig ist: Im Log steht „GSX: boarding completed“, und die
      Durchsage „Türen geschlossen“ kommt

## 3. Pushback (GSX)

- [ ] „request push and start“, dann den Readback „push and start approved, facing …“
- [ ] **Den GSX-Pushback nicht selbst bestellen:** Die App soll ihn nach deinem Readback von selbst anfordern
      (im Log: „GSX: pushback requested“)
- [ ] Fragt GSX etwas (z. B. die Richtung), beantwortest du das im GSX-Menü. Im Log steht dann „GSX asks …“
- [ ] Im Log steht „GSX: pushback started“ und später „finished“
- [ ] Falls ein Flugzeug hinter dir rollt: kam „hold position, traffic passing behind“?

## 4. Rollen (Taxi-Überwachung)

- [ ] „request **progressive** taxi“: Ground gibt die Route und sagt dann Abzweigungen an („turn left onto …“).
      In Hamburg sind viele Rollwege unbenannt, dann kommen nur wenige Ansagen.
- [ ] **Einmal absichtlich falsch abbiegen:** Ground meldet „you appear to be on …, new route, …“. Die neue Route
      zurücklesen.
- [ ] **Einmal kurz über 30 kt rollen:** Ground sagt „reduce taxi speed“
- [ ] Gibt es beim normalen Rollen **falsche** „new route“-Meldungen, z. B. beim Abkürzen von Kurven oder auf dem
      Vorfeld? (wichtig: Die Grenze liegt bei 50 m neben der Route)
- [ ] LiveTraffic auf deinem Weg: „give way to …“ / „follow …“ / „hold position“, und danach „continue taxi“
- [ ] Vor einer Bahnkreuzung anhalten und „holding short runway …“ melden. Kommt „cross runway …“?

## 5. Start

- [ ] Am Holding Point: Ground übergibt an den Tower, du meldest „ready for departure“
- [ ] Ist kurz vorher ein Heavy gestartet oder gelandet? Dann: „expect departure in two minutes, wake turbulence“
      bzw. „caution wake turbulence from the …“
- [ ] **Kabine:** Die Ansage vor dem Start kommt

## 6. Steigflug: Co-Pilot am Funk

- [ ] „copilot, you have the radio“ (oder den Button „Co-pilot radio“)
- [ ] Bei der Übergabe an Departure: Der Co-Pilot liest zurück, **rastet COM1 im Cockpit um** und meldet sich
- [ ] „I have the radio“: Du hast den Funk wieder
- [ ] **Kabine:** Durch 10.000 ft kommt die Steigflug-Durchsage

## 7. Reiseflug und Sinkflug

- [ ] Center-Übergaben kommen mit plausiblen Frequenzen
- [ ] Die Sinkflugfreigabe kommt rechtzeitig, die Kabine sagt den Sinkflug an

## 8. Anflug München

- [ ] Approach: Vectors oder STAR, dann die ILS-Freigabe
- [ ] Mit Verkehr vor dir: „number two, traffic to follow …“, eventuell eine Geschwindigkeitsanweisung
- [ ] Die Landefreigabe kommt erst, wenn die Bahn frei ist
- [ ] **Kabine:** Die Landedurchsage kommt

## 9. Nach der Landung

- [ ] „runway vacated“, Ground, „taxi to stand …“ (auch hier geht progressive taxi)
- [ ] In München: Übergabe an Apron
- [ ] Am Stand stehen bleiben: Die App fordert das GSX-Deboarding von selbst an (im Log: „GSX: deboarding requested“)
- [ ] **Kabine:** Die Ankunftsdurchsage kommt

---

## Was ich danach von dir brauche

1. **Die Ausgabe des Check-Befehls** aus Schritt 0
2. **Das Flight Log:** Ordner `%LOCALAPPDATA%\MSFS ATC\logs`, die neueste `.txt`-Datei
3. **Diese Checkliste** mit deinen Haken und einem Satz zu allem, was nicht stimmte. Am besten mit der ungefähren
   Uhrzeit, dann finde ich es im Log.

Wenn die App abstürzt oder eine Fehlermeldung zeigt, kopiere den Text oder mache einen Screenshot.
