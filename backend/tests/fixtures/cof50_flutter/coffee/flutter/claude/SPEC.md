# Kaffee-Begleiter (Flutter) – Spezifikation CAF-44

## 8 Entscheidungen

1. Team-Code-Style gilt wie in Abschnitt 7 (PO-Antwort 1).
2. Lokale Speicherung mit drift/SQLite, offline first, JSON-Export/-Import; stabile IDs und `updatedAt`; Cloud-Sync später (Abschnitt 3, 6).
3. Ein Nutzer, kein Login (Abschnitt 1).
4. Deutsch und Englisch nach Systemsprache (Abschnitt 6).
5. Schweizer Einheiten: Härte-Eingabe °fH (Standard), °dH, ppm, Speicherung ppm; g, ml, s, °C (R1).
6. Websuche beim Spec-Schreiben, Quellen zitiert; Regelwerte als Daten mit Quelle und Datum (Abschnitt 5, 6).
7. Mühlen: eigene Skala (Min, Max, Schritt) und Totraum pro Mühle (Abschnitt 3, R7, R9).
8. Maschinen: Brühtemperatur, Preinfusion, Druckprofil, Standard-Wasserprofil (Abschnitt 3).
9. Bestand: Mindestbestand 2 Tage Verbrauch, ohne Historie 100 g; Bestellhinweis nach R5; Lückenwarnung nach R6.
10. Alle weiteren Vorschläge übernommen (Defaults aus Abschnitt 5, 4).
11. Empfehlungen: eine Variable, in Rasterstufen der Mühle (1–2), Wasser zuerst, mit Grund und Quelle (R9, R11).
12. Filter: Methoden V60/Chemex/Kalita/AeroPress/Batch, Verhältnis Standard 1:16 (1:14–1:18), Bloom und Aufgüsse mit Zwischensummen und Timer, nur ruhezeit-fertige Packungen, Espresso-Blends nicht zuerst (R3, R10); README.md und CHANGELOG.md in jeder Story (Abschnitt 7).
13. Wasserbereich: Gesamthärte 50–175 ppm und Alkalinität 40–75 ppm (SCA-Handbuch „Core Zone“); Quellen nennen daneben Calcium-Härte 17–85 mg/L – nur Daten-Asset, änderbar (R2).
14. Ruhetage = untere Grenze der Bereichs-Tabelle (R3).
15. Annahmen aus der Review-Revision (einfachste passende Option): Zeit vor Geschmack bei Espresso und Filter (R9, R11); ein Band 25–30 s (R9); Filter-Empfehlung nur Mahlgrad (R11); Lieferzeit auf Bohnenebene (Abschnitt 3); `restMethod` espresso für `espressoBlend`/`allround` (Abschnitt 3); Soft-Delete statt hartem Löschen (Abschnitt 3); fehlende Referenzen beim Import werden übersprungen (Abschnitt 6); alle deutschen Locales im Format de-CH (Abschnitt 6); zu alte Packungen zählen nicht als trinkbereit (R3); Shot-Zeiten-Summe entfällt (R8); Warnfarbe #8A5A00 wegen Kontrast (Tokens).

## 9 Offene Fragen
