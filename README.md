# E.ON Drive pro Home Assistant

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

## Instalace

### HACS

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
aktualizace (výchozí 5 minut, minimum 1 minuta). Dotazuj se střídmě.

## Jak to funguje

- Přihlášení: OAuth2 password grant, token se drží jen v paměti. Když ho server
  odmítne, integrace se přihlásí znovu; při změně hesla nabídne nové přihlášení.
- Každý cyklus: jeden dotaz na stav všech sledovaných lokalit a jeden na
  probíhající nabíjení.
- Historie se stahuje jednou za 30 minut a hned po skončení nabíjení.
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

## Licence

MIT, viz [LICENSE](LICENSE).

Made together with Claude (Anthropic).
