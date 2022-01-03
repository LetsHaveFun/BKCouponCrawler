# Better King
Burger King Coupon Telegram Bot

<html><img src="https://www.picflash.org/viewer.php?img=Logo36AUIGS.jpg" width="220" height="216" /> </br>
<img src="https://www.picflash.org/viewer.php?img=2021_01_24_Showcase_21OL5XA.png" width="360" height="640" /> </br> </html>

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
1. ``git clone https://github.com/BetterKingBot/BKCouponCrawler.git``
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
Key | Datentyp | Optional | Beschreibung | Beispiel
--- | --- | --- | --- | ---
bot_token | String | Nein | Bot Token | `1234567890:HJDH-gh56urj6r5u6grhrkJO7Qw`
db_url | String | Nein | URL zur CouchDB DB samt Zugangsdaten | `http://username:pw@localhost:5984/` 
public_channel_name | String | Ja | Name des öffentlichen Telegram Channels, in den der Bot die aktuell gültigen Gutscheine posten soll.  | `TestChannel`
bot_name | String | Nein | Name des Bots | `BetterKingBot`
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
2. Datei `paper_coupon_helper_ids.txt` erstellen und mit allen IDs der Papiercoupons (in korrekter Reihenfolge also 1-47 bzw. 1-48) befüllen z.B.:  
```
21007
23007
22063
```
3. `PaperCouponHelper.py` einmalig ausführen **oder** Bot/Crawler neustarten.  Dies wird die `config_paper_coupons.json` aktualisieren und die neuen Papiercoupons einbinden.
Derzeit lassen sich über diesen Weg nur Coupons eines einzigen aktiven Buchstabens hinzufügen!

## config_extra_coupons.json: Optionale Config zum manuellen Hinzufügen von Coupons, die in keiner der Schnittstellen zu finden sind
Die ``config_extra_coupons.json`` ist nützlich, um manuell Coupons hinzuzufügen, die in keiner der BK Datenbanken enthalten sind z.B. [solche](https://www.mydealz.de/gutscheine/gratis-eis-und-softdrink-bei-burger-king-1804058).
Beispiel:  
Siehe `config_extra_coupons.json`

### Mögliche Start-Parameter für `BKBot.py`:  
Die meisten Parameter sind nur einzeln verwendbar.  

Parameter | Beschreibung
--- | ---
forcechannelupdatewithresend | Sofortiges Channelupdates mit löschen- und neu Einsenden aller Coupons.
resumechannelupdate | Channelupdate fortsetzen: Coupons ergänzen, die nicht rausgeschickt wurden und Couponübersicht erneuern. Nützlich um ein Channelupdate bei einem Abbruch genau an derselben Stelle fortzusetzen.
forcebatchprocess | Alle drei Aktionen ausführen, die eigentlich nur täglich 1x durchlaufen: Crawler, User Favoriten Benachrichtigungen rausschicken und Channelupdate mit Löschen- und neu Einsenden.
usernotify | User benachrichtigen über abgelaufene favorisierte Coupons, die wieder zurück sind und neue Coupons (= Coupons, die seit dem letzten DB Update neu hinzu kamen).
nukechannel | Alle Nachrichten im Channel automatisiert löschen (debug/dev Funktion für alle die zu faul sind, das von Hand zu tun ;) )
cleanupchannel | Zu löschende alte Coupon-Posts aus dem Channel löschen
migrate | DB Migrationen ausführen falls verfügbar
crawl | Crawler beim Start des Bots einmalig ausführen

### Bot mit Systemstart starten (Linux)
1. Sichergehen, dass BKBot.py ausführbar ist. Falls nötig: ``chmod a+b BKBot.py``.
2. Per ``crontab -e`` in crontab wechseln.
3. Neue Zeile erstellen mit: ``@reboot sleep 10 && cd /username/bla/BKCouponCrawler && python3 BKBot.py > /tmp/bkbot.log 2>&1``  
Die Wartezeit wird benötigt, damit CouchDB auf jeden Fall vor dem Start des Bots läuft.  
4. Beenden mit ``pkill python3`` (vereinfachte Variante).

### Interne Coupon-Typen und Beschreibung
ID | Interne Bezeichnung | Beschreibung
--- | --- | --- | 
0 | APP | App Coupons
1 | APP_VALID_AFTER_DELETION | App Coupons, die laut Ablaufdatum noch gültig sein müssten aber bereits nicht mehr per App-API zurückgegeben werden.
2 | APP_SAME_CHAR_AS_CURRENT_APP_COUPONS | Coupons mit denselben Abfangsbuchstaben wie aktuelle App Coupons, die jedoch nicht in der App API sind -> Potentielle "Special App Coupons"
3 | PAPER | Papiercoupons
4 | PAPER_UNSAFE | Coupons aus der "Coupons2" API, die keinem anderen Coupon-Typen zugewiesen werden konnten.
5 | ONLINE_ONLY | Coupons ohne short PLU Code, die wenn überhaupt nur online oder per QR Code (Terminal) bestellbar sind.
6 | ONLINE_ONLY_STORE_SPECIFIC | Coupons, die nur in bestimmten Filialen einlösbar sind -> Derzeit ist das nur ein Platzhalter
7 | SPECIAL | Spezielle Coupons, die manuell über die ``config_extra_coupons.json`` eingefügt werden können.
8 | PAYBACK | Payback Papiercoupons, die manuell über die ``config_extra_coupons.json`` eingefügt werden können.

### Codebeispiel Crawler
```
crawler = BKCrawler()
""" Nur für den Bot geeignete Coupons crawlen oder alle?
 Wenn du den Bot 'produktiv' einsetzt, solltest du alle ressourcenhungrigen Schalter deaktivieren (= default). """
crawler.setCrawlOnlyBotCompatibleCoupons(True)
# History Datenbank aufbauen z.B. zur späteren Auswertung?
crawler.setKeepHistory(True)
# CSV Export bei jedem Crawlvorgang (de-)aktivieren
crawler.setExportCSVs(False)
# Coupons crawlen
crawler.crawlAndProcessData()
# Coupons filtern und sortieren Bsp. 1: Nur aktive, die der Bot handlen kann sortiert nach Typ, Menü, Preis
activeCoupons = crawler.filterCoupons(CouponFilter(activeOnly=True, allowedCouponSources=BotAllowedCouponSources, sortMode=CouponSortMode.SOURCE_MENU_PRICE))
# Coupons filtern und sortieren Bsp. 1: Nur aktive, nur App Coupons, mit und ohne Menü, nur versteckte, sortiert nach Preis
activeCoupons = crawler.filterCoupons(CouponFilter(sortMode=CouponSortMode.PRICE, allowedCouponSources=CouponSource.APP, containsFriesAndCoke=None, isHidden=True))
```

# TODOs
* Infos aus BK Couponbögen mit [opencv](https://opencv.org/) oder einer anderen OCR Lösung extrahieren und damit das Hinzufügen der aktuellen Papiercoupons erleichtern
* Payback Coupons in "Alle Coupons" Ansicht ganz oben anzeigen (normale Coupons ohne Preis stehen derzeit ganz oben - aktuell nur einer)(?) -> Low Prio
* Neue API einbauen: https://czqk28jt.apicdn.sanity.io/v1/graphql/prod_bk_de/default (Insomnia Client oder Postman verwenden)
* resumechannelupdate verbessern
* Channelupdate "fortsetzen" nach Abbruch ermöglichen --> Autom. Neuversuch bei "NetworkError"
* User, die den Bot geblockt haben keine Benachrichtigungen mehr versuchen zu schicken (könnte passieren, wenn ein User Favoriten speichert. Benachrichtigungen aktiviert und dannach den Bot blockiert, TG Exception Unauthorized)
* Herausfinden, ob "Store-spezifische Coupons" offline vor Ort doch in allen Stores gehen oder die Akzeptanz gleich der der App ist
* App DB per Proxy in der originalen BK App modifizieren?
* App Coupons testen, die gerade nicht in der App sind aber noch gültig sein müssten

# Feature Ideen
* Einstellung, um abgelaufene Favoriten automatisch löschen zu lassen sonst werden es über die Zeit immer mehr

# Daten für den BotFather (Telegram Bot Konfiguration)

### Bot Commands Liste
```
start - Hauptmenü
tschau - 🚫 Meine Daten löschen
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
- Open source: github.com/BetterKingBot/BKCouponCrawler
Made with ❤ and 🍻 during 😷
```

### Channel Description
```
Burger King Coupons auf Telegram
Made with ❤ and 🍻 during 😷
Zum Bot: @BetterKingBot
Kontakt: bkfeedback@pm.me
Source: github.com/BetterKingBot/BKCouponCrawler
```

### Channel angepinnter Post mit Papiercoupons Datei & Verlinkung
```
Aktuelle Papiercoupons (gültig bis 24.09.2021):
Externer Downloadlink: mega.nz/folder/HLJFGAyL#Da7bq1Sues_mrC-uvVLTGQ
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
mydealz.de/gutscheine/neue-burger-king-gutscheine-gultig-bis-12112021-1861962
Gültig bis: 12.11.2021

Welche Daten speichert der Bot?
Deine Benutzer-ID und deine Einstellungen.
Diese Daten werden nicht ausgewertet und du kannst sie jederzeit mit dem Befehl '/tschau' endgültig aus der Datenbank löschen.

Meine BK Filiale verlangt original Papier-/App Coupons, wie kann ich die aus dem Channel dennoch verwenden?
Es gibt mehrere Möglichkeiten:
- Versuche, die Kurz-Codes einfach anzusagen
- Fahre durch den Drive hier werden idR. alle genommen
- Falls deine BK Filiale die Vorbestellen Funktion bietet, scanne die Coupons im Bestellvorgang mit deinem Handy (Zweitgerät/Laptop benötigt)
- Nimm statt BetterKing das unten verlinkte Würger King Projekt; es zeigt die Coupons so an wie die BK App

Wo finde ich den Quellcode?
Hier: github.com/BetterKingBot/BKCouponCrawler

Wie kann ich Fehler melden oder Feedback einreichen?
Per Mail: bkfeedback@pm.me

Gibt es ähnliche open source Projekte für BK?
Ja: Würger King: wurgerking.wfr.moe
Quellcode: github.com/WebFreak001/WurgerKing

Gibt es sowas auch für McDonalds/KFC/...?
Mir ist kein solches Projekt bekannt.
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
  
Monat | Code
--- | ---
Januar | BB
Februar | LS
März | JH
April | PL
Mail | BK
Juni | WH
Juli | FF
August | BF
September | CF
Oktober | CK
November | CB
Dezember | VM

### Online Vorbestellung Recherche
Über die BK App kann man in einigen Filialen [online vorbestellen](https://www.bundesverband-systemgastronomie.de/de/bdsnachricht/schnell-einfach-flexibel-bestellen-abholen-bei-burger-king-r.html).  
Hier lassen sich in der App die App Gutscheine auswählen, aber auch QR Codes scannen.
* Es sind alle PLUs bestellbar, auch laut Datum abgelaufene --> Vermutlich alles, was zu einem Produkt führt, das aktuell einen `availability_type` von `available` hat.
* Es befinden sich fast alle App- UND Papiercoupons im "Filial-spezifischen" Endpoint: `mo.burgerking-app.eu/api/v2/stores/123456/menu`
* Unterschiedliche Filialen können einen unterschiedlichen Pool von Coupons akzeptieren, aber die meisten Coupons funktionieren in allen Filialen
* Die online aufgelisteten Gutscheine sind nicht alle, die akzeptiert werden: beispielsweise können aktuell gültige Papiercoupons teilweise fehlen, obwohl Restaurants Papiercoupons generell akzeptieren -> Bedeutet im Klartext: Manche Papiercoupons lassen sich bei manchen Restaurants nicht in der online Vorbestellung nutzen, obwohl sie offline in der Filiale funktionieren müssten -> Fehler in der BK DB?! -> Ergibt einfach keinen Sinn
* Seit ca. September 2021 scheint die Vorbestellen Funktion bei allen BK Filialen entfernt worden zu sein. Kennt man die FilialIDs, die Vorbestellungen akzeptierten, kann man noch immer Coupons über den Endpoint abfragen.

### Danke an
* [bkoder Projekt](https://github.com/3dik/bkoder)
* [Blog Artikel 'Hack the Burger King'](https://edik.ch/posts/hack-the-burger-king.html)
* [MyDealz BK PLU Sammlung](https://www.mydealz.de/gutscheine/burger-king-bk-plu-code-sammlung-uber-270-bkplucs-822614)
* https://limits.tginfo.me/de-DE

### Kleine Linksammlung
* https://www.mydealz.de/diskussion/burger-king-gutschein-api-1741838
* http://www.fastfood-forum.net/wbb3/upload/index.php/Board/9-Burger-King/

### Ähnliche BK Projekte auf GitHub (teilweise veraltet)
* https://github.com/WebFreak001/WurgerKing | [Live Instanz](https://wurgerking.wfr.moe/)
* https://github.com/reteps/burger-king-api-wrapper
* https://github.com/robsonkades/clone-burger-king-app-with-expo
* https://bk.eris.cc/ --> https://gist.github.com/printfuck

#### Ideen für ähnliche Projekte
* Couponplatz Crawler/Bot
* KFC Bot
* Aral Bot/Channel ([MeinAral App](https://mein.aral.de/service-tools/meinaral-app/))