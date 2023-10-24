# Better King
Burger King Coupon Telegram Bot

<html><img src="https://github.com/coffeerhyder/BKCouponCrawler/blob/GithubMirror/media/Logo2.jpeg?raw=true" width="220" height="216" /> </br>
<img src="https://github.com/coffeerhyder/BKCouponCrawler/blob/GithubMirror/media/2021_01_24_Showcase_2.png?raw=true" width="360" height="640" /> </br> </html>

# Features
* Alle Burger King Coupons ohne App & Accountzwang
* Crawler und Bot getrennt: Crawler kann einfach für andere Projekte verwendet werden
* Coupons sortiert, aufgeräumt und teils mit zusätzlichen Informationen

**Video:**  
https://www.bitchute.com/video/eoMYCfag5oiM/

# Live Instanz:
# [Zum TG Channel](https://t.me/BetterKingPublic) | [Ansicht ohne TG Account](https://t.me/s/BetterKingPublic)
# [Zum TG Bot](https://t.me/BetterKingBot)
# [Zur Matrix Bridge](https://app.element.io/#/room/#BetterKingDE:matrix.org)

# Installation
1. ``git clone https://github.com/coffeerhyder/BKCouponCrawler.git``
2. ``apt install python3-pip``
3. ``pip3 install -r requirements.txt``
4. [CouchDB](https://linuxize.com/post/how-to-install-couchdb-on-ubuntu-20-04/) installieren und einrichten.  
5. `config.json.default` in `config.json` umbenennen und eigene Daten eintragen (siehe unten).
6. Eine wichtige couchDB Einstellung festlegen:
``` max_document_id_number ``` --> Auf 1000 setzen siehe: https://docs.couchdb.org/en/latest/config/misc.html#purge
7. `BKBot.py` einmalig mit dem Parameter `crawl` aufrufen.

# CouchDB (user-DB) Backup & Wiederherstellen
Backup:
```
git clone https://github.com/danielebailo/couchdb-dump
-->
bash couchdb-dump.sh -b -H 127.0.0.1 -d telegram_users -f telegram_users.json -u username -p password
```
Wiederherstellen:
```
Alte DB löschen, da bestehende Einträge nicht überschrieben werden:
curl -X DELETE http://username:password@127.0.0.1:5984/telegram_users
Wiederherstellen des Backups:
bash couchdb-dump.sh -r -c -H 127.0.0.1 -d telegram_users -f telegram_users.json -u username -p password
```


# config.json (siehe config.json.default)
| Key                 | Datentyp    | Optional | Beschreibung                                                                                         | Beispiel                                 |
|---------------------|-------------|----------|------------------------------------------------------------------------------------------------------|------------------------------------------|
| bot_token           | String      | Nein     | Bot Token                                                                                            | `1234567890:HJDH-gh56urj6r5u6grhrkJO7Qw` |
| db_url              | String      | Nein     | URL zur CouchDB DB samt Zugangsdaten                                                                 | `http://username:pw@localhost:5984/`     |
| public_channel_name | String      | Ja       | Name des öffentlichen Telegram Channels, in den der Bot die aktuell gültigen Gutscheine posten soll. | `TestChannel`                            |
| bot_name            | String      | Nein     | Name des Bots                                                                                        | `BetterKingBot`                          |
| admin_ids           | StringArray | Nein     | Telegram UserIDs der gewünschten Bot Admins                                                          | ["57659679843", "534494657832"]          |

**Falls nur der Crawler benötigt wird, reicht die CouchDB URL (mit Zugangsdaten)!**

## Optional: Papiercoupons hinzufügen  
1. Die `config_paper_coupons.json` wie folgt befüllen:  
Gäbe es derzeit z.B. Papiercoupons mit dem Buchstaben ``B`` und Ablaufdatum  ``05.03.2021`` **und** ``C`` mit dem Ablaufdatum ``23.04.2021``, müsste die json Datei wie folgt angepasst werden:
   
```
{
{
  "B": {
    "expire_date": "2021-03-05"
  },
  "C": {
    "expire_date": "2021-04-23"
  }
}
}   
```  
2. Datei `paper_coupon_data/paper_coupon_helper_ids_NOCHAR.txt` erstellen und mit allen IDs der Papiercoupons befüllen z.B.:  
```
31734:906
23236:909
11394:910
```
3. Bot einmalig mit dem `crawl` Parameter starten.

## config_extra_coupons.json: Optionale Config zum manuellen Hinzufügen von Coupons, die in keiner der Schnittstellen zu finden sind
Die `config_extra_coupons.json` ist nützlich, um manuell Coupons hinzuzufügen, die in keiner der BK Datenbanken enthalten sind z.B. [solche](https://www.mydealz.de/gutscheine/gratis-eis-und-softdrink-bei-burger-king-1804058).
Beispiel:  
Siehe `config_extra_coupons.json`

### Bot mit Logging in File starten
```
python3 BKBot.py 2>&1 | tee /tmp/bkbot.log
```

### Mögliche Start-Parameter für `BKBot.py`:  
Die meisten Parameter sind nur einzeln verwendbar.  

```
usage: BKBot.py [-h] [-fc FORCECHANNELUPDATEWITHRESEND]
                [-rc RESUMECHANNELUPDATE] [-fb FORCEBATCHPROCESS]
                [-un USERNOTIFY] [-n NUKECHANNEL] [-cc CLEANUPCHANNEL]
                [-m MIGRATE] [-c CRAWL] [-mm MAINTENANCEMODE]

optional arguments:
  -h, --help            show this help message and exit
  -fc FORCECHANNELUPDATEWITHRESEND, --forcechannelupdatewithresend FORCECHANNELUPDATEWITHRESEND
                        Sofortiges Channelupdates mit löschen- und neu
                        Einsenden aller Coupons.
  -rc RESUMECHANNELUPDATE, --resumechannelupdate RESUMECHANNELUPDATE
                        Channelupdate fortsetzen: Coupons ergänzen, die nicht
                        rausgeschickt wurden und Couponübersicht erneuern.
                        Nützlich um ein Channelupdate bei einem Abbruch genau
                        an derselben Stelle fortzusetzen.
  -fb FORCEBATCHPROCESS, --forcebatchprocess FORCEBATCHPROCESS
                        Alle Aktionen ausführen, die eigentlich nur täglich 1x
                        durchlaufen: Crawler, User Benachrichtigungen
                        rausschicken und Channelupdate mit Löschen- und neu
                        Einsenden.
  -un USERNOTIFY, --usernotify USERNOTIFY
                        User benachrichtigen über abgelaufene favorisierte
                        Coupons, die wieder zurück sind und neue Coupons (=
                        Coupons, die seit dem letzten DB Update neu hinzu
                        kamen).
  -n NUKECHANNEL, --nukechannel NUKECHANNEL
                        Alle Nachrichten im Channel automatisiert löschen
                        (debug/dev Funktion)
  -cc CLEANUPCHANNEL, --cleanupchannel CLEANUPCHANNEL
                        Zu löschende alte Coupon-Posts aus dem Channel
                        löschen.
  -m MIGRATE, --migrate MIGRATE
                        DB Migrationen ausführen falls verfügbar
  -c CRAWL, --crawl CRAWL
                        Crawler beim Start des Bots einmalig ausführen.
  -mm MAINTENANCEMODE, --maintenancemode MAINTENANCEMODE
                        Wartungsmodus - zeigt im Bot und Channel eine
                        entsprechende Meldung. Deaktiviert alle Bot
                        Funktionen.
```

### Bot mit Systemstart starten (Linux)
1. Sichergehen, dass BKBot.py ausführbar ist. Falls nötig: ``chmod a+b BKBot.py``.
2. Per ``crontab -e`` in crontab wechseln.
3. Folgendes hinzufügen:  
```
# Bot Start Script alle X Minuten ausführen um sicherzugehen, dass der Bot immer läuft
*/1 * * * * sh /root/betterking/BKCouponCrawler/bkstart.sh

# Optionale Commands: Updates nachts automatisch ausführen
00 03 * * * root /usr/bin/apt update -q -y >> /var/log/apt/automaticupdates.log
30 03 * * * root /usr/bin/apt upgrade -q -y >> /var/log/apt/automaticupdates.log
# Jede Nacht um 4 Uhr neustarten
00 04 * * * reboot
```
4. Falls gewollt, Bot beenden mit ``pkill python3`` (vereinfachte Variante).

### Interne Coupon-Typen und Beschreibung
|ID | Interne Bezeichnung | Beschreibung|
--- | --- | --- | 
|0 | APP | App Coupons|
|3 | PAPER | Papiercoupons|
|4 | PAPER_UNSAFE | Coupons aus der "Coupons2" API, die keinem anderen Coupon-Typen zugewiesen werden konnten.|
|5 | ONLINE_ONLY | Coupons ohne short PLU Code, die wenn überhaupt nur online oder per QR Code (Terminal) bestellbar sind.|
|6 | ONLINE_ONLY_STORE_SPECIFIC | Coupons, die nur in bestimmten Filialen einlösbar sind -> Derzeit ist das nur ein Platzhalter|
|7 | SPECIAL | Spezielle Coupons, die manuell über die ``config_extra_coupons.json`` eingefügt werden können.|
|8 | PAYBACK | Payback Papiercoupons, die manuell über die ``config_extra_coupons.json`` eingefügt werden können.|

### Codebeispiel Crawler
Siehe BKBot.py -> ``__init__``

# TODOs
* Dafür sorgen, dass der Bot auch dann am Laufen bleibt, wenn beim Start kein Internet verfügbar ist und er somit in ein Timeout läuft (Abbruch in application.run_polling)
* Zeitberechnungen refactoring: timedelta überall verwenden wo möglich
* MessageHandler für nicht unterstützte Kommandos/Text einbauen
* Die Transparenz bei (mybk) Couponbildern durch gelb ersetzen
* Handling mit Datumsangaben prüfen/verbessern
* couchdb-dump updaten, sodass es per Parameter beim restore die DB wahlweise vorher löschen- und neu erstellen oder Items überschreiben kann
* Infos aus BK Couponbögen mit [opencv](https://opencv.org/) oder einer anderen OCR Lösung extrahieren und damit das Hinzufügen der aktuellen Papiercoupons erleichtern
* resumechannelupdate verbessern
* Channelupdate "fortsetzen" nach Abbruch ermöglichen --> Autom. Neuversuch bei Netzwerkfehlern o.ä.

# Daten für den BotFather (Telegram Bot Konfiguration)

### Bot Commands Liste
```
start - Hauptmenü
coupons - Alle Coupons
coupons2 - Coupons ohne Menü
favoriten - ⭐Favoriten⭐
angebote - Angebote
payback - 🅿️ayback Karte
einstellungen - 🔧Einstellungen
stats - Statistiken für Nerds
tschau - 🚫 Meinen Account löschen
 ```

### Bot About
```
Burger King Coupons auf Telegram
Made with ❤ and 🍻 during 😷
Channel: @BetterKingPublic
Kontakt: bkfeedback@pm.me
```

### Bot Description
```
Burger King Coupons auf Telegram
- Channel: @BetterKingPublic
- Kontakt: bkfeedback@pm.me
Features:
- Alle BK Coupons immer aktuell (auch Papiercoupons)
- MyBK Coupons ohne Account und unendlich oft einlösbar
- Datensparsam & superschnell
- Favoriten speichern & optionale Benachrichtigung bei Wiederverfügbarkeit
- Kein Tracking
- Offline verwendbar (sofern Bilder vorher geladen wurden)
- Open source: github.com/coffeerhyder/BKCouponCrawler
Made with ❤ and 🍻 during 😷
```

### Channel Description
```
Burger King Coupons auf Telegram
Made with ❤ and 🍻 during 😷
Zum Bot: @BetterKingBot
Kontakt: bkfeedback@pm.me
Source: github.com/coffeerhyder/BKCouponCrawler
```

### Channel angepinnter Post mit Papiercoupons Datei & Verlinkung
```
Aktuelle Papiercoupons (gültig bis 24.09.2021):
Externer Downloadlink: mega.nz/folder/zWQkRIoD#-XRxtHFcyJZcgvOKx4gpZg
Quelle(n):
mydealz.de/gutscheine/burger-king-coupons-bundesweit-gultig-bis-23042021-1762251
mydealz.de/gutscheine/burger-king-coupons-bundesweit-gultig-bis-05032021-1731958
```

### Channel angepinnter Post mit Papiercoupons nur Verlinkung (neue Variante ohne extra Upload der Datei)
```
Aktuelle Papiercoupons (gültig bis 24.09.2021):
mydealz.de/gutscheine/burger-king-papier-coupons-bis-2409-1840299
```

### Channel FAQ
```
FAQ BetterKing Bot und Channel

Wo finde ich die aktuellen Papiercoupons als Scan?
Sofern es welche gibt, hier:
mega.nz/folder/zWQkRIoD#-XRxtHFcyJZcgvOKx4gpZg
Dieser Ordner dient außerdem als Archiv.

Warum fehlen Papiercoupons im Bot/Channel?
Seit dem 30.07.2022 gibt es keine Papiercoupons mehr direkt im Bot/Channel, da man diese manuell eintragen müsste und ich _noch_ keine Zeit hatte, ein System dafür zu bauen.
Die aktuellen Papiercoupons finden sich immer auf MyDealz und in der oben verlinkten MEGA Cloud.

Warum sind Payback Coupons nur manchmal direkt im Bot/Channel verfügbar?
Weil sie derzeit von Hand eingetragen werden müssen und ich faul bin.

Welche Daten speichert der Bot?
Deine Benutzer-ID, deine Einstellungen und alle 48 Stunden einen Zeitstempel der letzten Bot verwendung.
Diese Daten werden nicht ausgewertet und du kannst sie jederzeit mit dem Befehl '/tschau' endgültig aus der Datenbank löschen.
Der Zeitstempel dient nur dazu, inaktive Accounts nach 6 Monaten automatisch löschen zu können.

Kann der Bot meine Telefonnummer sehen?
Nein das können Bots standardmäßig nur, wenn du es erlaubst.
Selbst wenn du dies tust: Der Bot speichert ausschließlich die oben genannten Daten.

Meine BK Filiale verlangt original Papier-/App Coupons, wie kann ich die aus dem Channel dennoch verwenden?
Es gibt mehrere Möglichkeiten:
- Versuche, die Kurz-Codes einfach anzusagen
- Fahre durch den Drive hier werden idR. alle genommen
- Falls deine BK Filiale die Vorbestellen Funktion bietet, scanne die Coupons im Bestellvorgang mit deinem Handy (Zweitgerät/Laptop benötigt)
- Nimm statt BetterKing das unten verlinkte Würger King Projekt; es zeigt die Coupons so an wie die BK App

Wo finde ich den Quellcode?
Hier: github.com/coffeerhyder/BKCouponCrawler

Wie kann ich Fehler melden oder Feedback einreichen?
Per Mail: bkfeedback@pm.me

Gibt es ähnliche open source Projekte für BK?
Nein

Gibt es sowas auch für McDonalds/KFC/...?
McDonald's
01. mccoupon.deals | Mcdonald's Coupons
02. mcbroken.com | Wo funktioniert die Eismaschine?
Sonstige
01. billigepizza.netlify.app | Pizzapreise bei Domino's optimieren
—> Video
 (https://www.youtube.com/watch?v=rChjUHveYxI)  
02. mistersnax.com | Lieferando in geiler z.B. Gruppenbestellungen, Preisvergleich

Linksammlung BK:
01. burgerking.de/sparkings | Spar Kings
02. burgerking.de/kingdeals | KING Deals
03. burgerking.de/rewards/offers | Coupons Webansicht
04. burgerking.de/store-locator | KING Finder
05. ngb.to/threads/betterking-burger-king-coupons-telegram-bot.110780/
06. pr0gramm.com/user/FishEater23/uploads/4730464
07. tvnow.de/shows/team-wallraff-reporter-undercover-2384/2022-09/episode-2-team-wallraff-undercover-2022-5209024
```

### Test Cases
* Alle Coupon Kategorien
* User Favoriten
* User mit Favoriten + abgelaufenen Favoriten
* Einstellungen
* Channel Renew
* Test mit neuem User

### BK Feedback Codes Recherche
Feedback Codes sind ...
* Hier generierbar: https://www.bk-feedback-de.com/
* 8-stellig: Zwei großgeschriebene Anfangsbuchstaben (variieren je nach Monat) und 6 Zahlen z.B. `BB123456`
* Offiziell gültig bei Abgabe eines maximal 30 Tage alten Kassenbons

Tabelle: Buchstabencodes für alle Monate:
  
| Monat     | Code |
|-----------|------|
| Januar    | BB   |
| Februar   | LS   |
| März      | JH   |
| April     | PL   |
| Mail      | BK   |
| Juni      | WH   |
| Juli      | FF   |
| August    | BF   |
| September | CF   |
| Oktober   | CK   |
| November  | CB   |
| Dezember  | VM   |

### Online Vorbestellung Recherche
Über die BK App kann man in einigen Filialen [online vorbestellen](https://www.bundesverband-systemgastronomie.de/de/bdsnachricht/schnell-einfach-flexibel-bestellen-abholen-bei-burger-king-r.html).  
Hier lassen sich in der App die App Gutscheine auswählen, aber auch QR Codes scannen.
* Es sind alle PLUs bestellbar, auch laut Datum abgelaufene --> Vermutlich alles, was zu einem Produkt führt, das aktuell einen `availability_type` von `available` hat.
* Es befinden sich fast alle App- UND Papiercoupons im "Filial-spezifischen" Endpoint: `mo.burgerking-app.eu/api/v2/stores/486/menu`
* Unterschiedliche Filialen können einen unterschiedlichen Pool von Coupons akzeptieren, aber die meisten Coupons funktionieren in allen Filialen
* Die online aufgelisteten Gutscheine sind nicht alle, die akzeptiert werden: beispielsweise können aktuell gültige Papiercoupons teilweise fehlen, obwohl Restaurants Papiercoupons generell akzeptieren -> Bedeutet im Klartext: Manche Papiercoupons lassen sich bei manchen Restaurants nicht in der online Vorbestellung nutzen, obwohl sie offline in der Filiale funktionieren müssten -> Fehler in der BK DB?! -> Ergibt einfach keinen Sinn
* Seit ca. September 2021 scheint die Vorbestellen Funktion bei allen BK Filialen entfernt worden zu sein. Kennt man die FilialIDs, die Vorbestellungen akzeptierten, kann man noch immer Coupons über den Endpoint abfragen.

### Danke an
* https://github.com/3dik/bkoder
* https://edik.ch/posts/hack-the-burger-king.html
* https://www.mydealz.de/gutscheine/burger-king-bk-plu-code-sammlung-uber-270-bkplucs-822614
* https://limits.tginfo.me/de-DE

### Kleine Linksammlung
* https://www.mydealz.de/diskussion/burger-king-gutschein-api-1741838
* https://www.burgerking.de/rewards/offers (Coupons direkt über die BK Webseite)
* https://pr0gramm.com/user/FishEater23/uploads/4730464
* https://ngb.to/threads/betterking-burger-king-coupons-telegram-bot.110780/

### Ähnliche Projekte | funktionierend
Name | Beschreibung | Live-Instanz
--- | --- | ---
- | https://github.com/reteps/burger-king-api-wrapper | -
- | https://github.com/robsonkades/clone-burger-king-app-with-expo | -
mccoupon.deals | McDonalds Coupons ohne App, [Autor](https://www.mydealz.de/profile/Jicu) | https://www.mccoupon.deals/
billigepizza.netlify.app | Pizzapreise von Domino's optimieren | https://billigepizza.netlify.app/
MisterSnax (ehemals Spätzlehunter) | Lieferando in geiler z.B. Gruppenbestellungen, Preisvergleich | https://mistersnax.com/
NordseeCoupons | Nordsee Coupons Bot | https://t.me/nordseecoupons , [Bot](https://t.me/NordseeCouponsBot)

* https://github.com/reteps/burger-king-api-wrapper
* https://github.com/robsonkades/clone-burger-king-app-with-expo
* https://www.mccoupon.deals/ | [Autor](https://www.mydealz.de/profile/Jicu) | [Quelle](https://www.mydealz.de/gutscheine/burger-king-gutscheine-mit-plant-based-angeboten-1979906?page=3#comment-36031037)
* [pbcp.de/partner/burger-king](https://pbcp.de/partner/burger-king)
* https://mcbroken.com/

### Ähnliche Projekte | down/defekt
Name | Beschreibung | Live-Instanz | Down seit
--- | --- | --- | ---
freecokebot aka gimmecockbot | McDonalds gratis Getränke | https://t.me/gimmecockbot (Alternativ https://t.me/freecokebot) | 10.11.2022
bk.eris.cc | BK Coupons ohne App, [Autor](https://gist.github.com/printfuck) | https://bk.eris.cc/ | 10.11.2022
mcdonalds4free_bot | McDonalds Getränke kostenlos, [MyDealz Thread](https://www.mydealz.de/diskussion/mcdonalds-hasst-diesen-trick-freigetranke-free-softdrink-coffee-small-1550092) | https://t.me/mcdonalds4free_bot | 15.01.2023
Würger King | Burger King Coupons | https://wurgerking.wfr.moe/  ([Quellcode](https://github.com/WebFreak001/WurgerKing)) | 31.12.2022

#### Ideen für ähnliche Projekte
* Couponplatz Crawler/Bot
* KFC Bot
* Aral Bot/Channel ([MeinAral App](https://mein.aral.de/service-tools/meinaral-app/))