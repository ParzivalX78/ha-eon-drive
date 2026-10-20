# E.ON Drive pro Home Assistant

[![Podpoř mě na Ko-fi](https://img.shields.io/badge/Ko--fi-kup%20mi%20kafe-FF5E5B?logo=kofi&logoColor=white)](https://ko-fi.com/parzival59520)

🇬🇧 **English:** [see below](#english).

Neoficiální integrace veřejné nabíjecí sítě **E.ON Drive (CZ)** do Home Assistantu.
Čte stejná data jako mobilní aplikace: stav vybraných nabíjecích stojanů, probíhající
nabíjení a historii nabíjení na tvém účtu.

> Integrace není produktem společnosti E.ON ani s ní není nijak spojená. Používá
> nedokumentované API mobilní aplikace, které se může kdykoli změnit nebo přestat
> fungovat. Používej ji jen se svým vlastním účtem a pro vlastní potřebu.

Integrace je **pouze pro čtení**. Nabíjení nespouští, nezastavuje ani nerezervuje.

## Co přidá

Pro každou sledovanou lokalitu (zařízení):

| Entita | Popis |
|---|---|
| `sensor.<lokalita>_volne_stojany` | počet volných stojanů; v atributech celkový počet, adresa a GPS |
| `sensor.<lokalita>_<konektor>_<výkon>` | stav stojanu: volný, nabíjí, mimo provoz, …; v atributech výkon, konektory a ceny (denní / noční / aktuální) |

Pro účet (zařízení „E.ON Drive“):

| Entita | Popis |
|---|---|
| `binary_sensor.e_on_drive_nabijeni` | zapnuto, když na účtu běží nabíjení |
| nabíjecí výkon, nabitá energie, cena nabíjení, baterie vozu | hodnoty probíhajícího nabíjení |
| poslední nabíjení – energie, cena, začátek | poslední dokončená relace |
| energie tento měsíc, útrata tento měsíc | součet relací zahájených v aktuálním měsíci |

Dlouhodobé statistiky (pro grafy po dnech, týdnech, měsících, letech):

| Statistika | Popis |
|---|---|
| `eon_drive:charged_energy` | nabitá energie v kWh |
| `eon_drive:charging_cost` | cena nabíjení v měně účtu (CZK) |

Plní se z **celé historie nabíjení na účtu**, takže grafy ukazují i měsíce
před instalací integrace. Nabíjení se počítá do hodiny, kdy začalo.

## Grafy

Na nástěnku přidej kartu (**Upravit → Přidat kartu → Ruční**):

```yaml
type: vertical-stack
cards:
  - type: horizontal-stack
    cards:
      - type: statistic
        name: Nabito tento měsíc
        entity: eon_drive:charged_energy
        stat_type: change
        period:
          calendar:
            period: month
      - type: statistic
        name: Útrata tento měsíc
        entity: eon_drive:charging_cost
        stat_type: change
        period:
          calendar:
            period: month
  - type: statistics-graph
    title: Nabitá energie po měsících
    entities:
      - entity: eon_drive:charged_energy
        color: "#4269d0"
    stat_types: [change]
    period: month
    chart_type: bar
    days_to_show: 365
  - type: statistics-graph
    title: Útrata za nabíjení po měsících
    entities:
      - entity: eon_drive:charging_cost
        color: "#4269d0"
    stat_types: [change]
    period: month
    chart_type: bar
    days_to_show: 365
```

Barva `#4269d0` je modrá z palety Home Assistantu; integrace PRE Point používá
žlutou `#f4bd4a`, takže ve společném grafu (stačí přidat obě statistiky do
`entities`) jsou sítě vždy odlišené stejně.

## Upozornění a odpovědnost

- Integrace je **neoficiální**. Nemá žádnou vazbu na společnost E.ON, ta ji nevytvořila,
  neschválila ani nepodporuje. Používá nedokumentovaná rozhraní, která se mohou kdykoli
  změnit nebo přestat fungovat.
- Používáš ji **výhradně na vlastní riziko a odpovědnost**. Autor neodpovídá za žádné škody
  ani důsledky jejího použití, zejména za **omezení nebo zablokování účtu**, chybné nebo
  chybějící údaje (např. o ceně nebo stavu nabíjení) ani za porušení podmínek služby.
- Totéž platí pro **jakékoli úpravy kódu nebo nastavení**, hlavně pro zkrácení intervalu
  dotazů pod výchozí hodnoty. Tím zvyšuješ zátěž serverů provozovatele i riziko zablokování
  a odpovídáš za to sám.
- Před použitím si přečti podmínky služby E.ON Drive a sám posuď, jestli je s nimi
  používání integrace v souladu.
- Software je poskytován „tak, jak je“, bez jakékoli záruky (viz licence MIT).

## Instalace

### HACS

Nejrychleji tlačítkem (otevře HACS ve tvém Home Assistantu):

[![Otevřít v HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ParzivalX78&repository=ha-eon-drive&category=integration)

Nebo ručně:

1. HACS → tři tečky → **Vlastní repozitáře**.
2. Přidej URL tohoto repozitáře, kategorie **Integrace**.
3. Nainstaluj „E.ON Drive“ a restartuj Home Assistant.

### Ručně

Zkopíruj složku `custom_components/eon_drive` do `config/custom_components/` a restartuj
Home Assistant.

## Nastavení

**Nastavení → Zařízení a služby → Přidat integraci → E.ON Drive.** Vyplníš:

- e-mail a heslo k účtu E.ON Drive,
- **client ID** a **client secret**.

Client ID a client secret jsou konstanty mobilní aplikace, kterými se aplikace
představuje serveru při přihlášení. V repozitáři záměrně nejsou. Získáš je
z vlastního záznamu provozu aplikace (např. [mitmproxy](https://mitmproxy.org)):
při přihlášení aplikace posílá `POST /api/v1/app/oauth/token` a obě hodnoty jsou
v těle požadavku jako `client_id` a `client_secret`.

V dalším kroku vyhledáš lokality (podle města nebo názvu) a vybereš, které chceš
sledovat. Krok jde přeskočit a lokality přidat později.

V **Nastavení integrace** pak můžeš lokality přidávat a odebírat a měnit interval
aktualizace (výchozí 10 minut, minimum 5 minut, maximum 1 hodina).

## Jak to funguje a jak šetrně se ptá

Integrace je navržená tak, aby dělala výrazně méně dotazů než samotná aplikace
(ta jich jen při spuštění pošle kolem třiceti).

- **Dva dotazy za cyklus:** jeden na stav všech sledovaných lokalit najednou,
  jeden na probíhající nabíjení. Při výchozích 10 minutách je to zhruba
  300 dotazů denně.
- **Historie** se stahuje jednou za hodinu a hned po skončení nabíjení, vždy jen
  za poslední dva měsíce. Celá historie účtu se stáhne **jen jednou** (po stránkách
  po 100 relacích) a uloží do `.storage`; když server tak dlouhé období odmítne,
  zkusí to integrace znovu za den.
- **Přihlášení jen když je potřeba:** token (platnost rok) se ukládá do
  `.storage` Home Assistantu, takže restart ani reload nové přihlášení nedělá.
  Znovu se přihlásí jen jednou, když server token odmítne. Když neprojde ani to,
  integrace přestane a požádá o nové heslo, nezkouší to dokola.
- **Zpomalení při potížích:** po chybě nebo odpovědi „příliš mnoho požadavků“
  (HTTP 429) se interval zdvojnásobí, respektuje `Retry-After` a roste nejvýše
  na hodinu. Po prvním úspěchu se vrátí na nastavenou hodnotu.
- Čte jen tvoje vlastní data a údaje, které aplikace ukazuje každému na mapě.
- Heslo a client secret jsou uložené v konfiguraci Home Assistantu
  (`.storage`), stejně jako u jiných integrací.

## Vývoj

```bash
python -m venv .venv && . .venv/bin/activate
pip install pytest-homeassistant-custom-component
pytest
```

Testy používají jen smyšlená data. **Záznamy z mitmproxy do repozitáře nikdy
nedávej**, obsahují heslo a tokeny (`.gitignore` je blokuje podle názvu `flows*`).

## Podpora

Integrace je zdarma a open source. Jestli ti šetří čas nebo peníze, můžeš mi
koupit kafe ☕

[![Podpoř mě na Ko-fi](https://img.shields.io/badge/Ko--fi-kup%20mi%20kafe-FF5E5B?logo=kofi&logoColor=white)](https://ko-fi.com/parzival59520)

Chyby a nápady piš do [Issues](../../issues).

## Licence

MIT, viz [LICENSE](LICENSE).

Made together with Claude (Anthropic).

---

## English

Unofficial Home Assistant integration for the **E.ON Drive (Czech Republic)** public EV
charging network. It reads the same data as the mobile app: the status of selected charging
locations, the ongoing charging session and the charging history of your account. It is
**read-only**: it never starts, stops or reserves charging.

### What you get

- **Per location:** number of free chargers and the state of each charger (free, charging,
  out of order…), with power, connectors and prices in the attributes.
- **Account:** charging now (on/off), power, charged energy, cost and car battery of the
  ongoing session; the last finished session; energy and cost this month.
- **Long-term statistics** `eon_drive:charged_energy` (kWh) and `eon_drive:charging_cost`
  (CZK), built from the **whole** charging history of the account, so charts show months
  before the integration was installed. The YAML for the charts is in the Czech part above.

### Installation

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ParzivalX78&repository=ha-eon-drive&category=integration)

Or HACS → ⋮ → **Custom repositories** → add this repository's URL, category **Integration**,
install „E.ON Drive“ and restart Home Assistant. Manual install: copy
`custom_components/eon_drive` to `config/custom_components/` and restart.

### Setup

**Settings → Devices & services → Add integration → E.ON Drive.** You need:

- the e-mail and password of your E.ON Drive account,
- the mobile app's **client ID** and **client secret**. They are deliberately not in this
  repository; capture them from your own app traffic (e.g. with
  [mitmproxy](https://mitmproxy.org)): on sign-in the app sends `POST /api/v1/app/oauth/token`
  with `client_id` and `client_secret` in the body.

Then search for and pick the locations to follow (can be skipped and changed later in the
options). Update interval: 10 minutes by default, 5–60 minutes allowed.

### Gentle on the server

Two requests per cycle, history once an hour, the sign-in token is stored and reused, and
the interval doubles (up to one hour, honouring `Retry-After`) after errors or HTTP 429.

### Disclaimer

- This integration is **unofficial**. It is not affiliated with, endorsed or supported by
  E.ON. It uses undocumented interfaces that may change or stop working at any time.
- You use it **entirely at your own risk and responsibility**. The author accepts no liability
  for any damage or consequences of its use, in particular for **restriction or blocking of
  your account**, wrong or missing data (e.g. prices or charging status), or breaches of the
  service's terms of use.
- The same applies to **any modifications of the code or settings**, especially shortening
  the update interval below the defaults. That increases the load on the operator's servers
  and the risk of being blocked, and it is your own responsibility.
- Before using it, read the E.ON Drive terms of service and decide for yourself whether
  using this integration complies with them.
- The software is provided "as is", without warranty of any kind (see the MIT license).

### Support

The integration is free and open source. If it saves you time or money, you can buy me a
coffee ☕

[![Buy me a coffee on Ko-fi](https://img.shields.io/badge/Ko--fi-buy%20me%20a%20coffee-FF5E5B?logo=kofi&logoColor=white)](https://ko-fi.com/parzival59520)

Bugs and ideas: [Issues](../../issues).

### License

MIT, see [LICENSE](LICENSE).
