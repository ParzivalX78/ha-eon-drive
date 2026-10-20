# E.ON Drive pro Home Assistant

[![Podpoř mě na Ko-fi](https://img.shields.io/badge/Ko--fi-kup%20mi%20kafe-FF5E5B?logo=kofi&logoColor=white)](https://ko-fi.com/parzival59520)

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
