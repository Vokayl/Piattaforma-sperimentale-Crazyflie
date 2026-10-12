# Crazyflie Platform

Piattaforma per progettare, simulare e analizzare missioni con più droni
Crazyflie. L'editor 3D permette di configurare lo scenario e i waypoint;
il backend esegue le missioni con Crazyswarm2 e conserva i dati per la
valutazione e il replay.

Il progetto nasce come lavoro di tesi ed è dedicato alla **simulazione**:
non controlla droni fisici. Utilizza il modello Crazyflie 2.1, il backend
dinamico NumPy (`np`) e il controllore Mellinger.

## Setup

Sono necessari:

- **[Godot 4.6 Standard](https://godotengine.org/)**, per l'interfaccia grafica;
- **Docker con Compose**, avviato e configurato per container Linux.

ROS 2 Jazzy, Crazyswarm2 e le dipendenze Python vengono installati nell'immagine
Docker: non occorre configurarli sul computer che esegue Godot.

1. Clonare o scaricare questa repository e aprire un terminale nella cartella
   che contiene `compose.yaml`.
2. Avviare il backend:

   ```bash
   docker compose up --build
   ```

   La prima build richiede una connessione Internet e compila le dipendenze.
   Attendere il messaggio `Crazyflie Platform HTTP` nel terminale.
3. Importare `frontend/project.godot` in Godot e avviare il progetto con **F5**.
4. Nell'interfaccia, lasciare host `127.0.0.1` e porta `8870`, quindi premere
   **Connetti**.

Agli avvii successivi basta `docker compose up`. Ripetere `--build` dopo
modifiche al backend o alle dipendenze. Il simulatore parte quando viene
richiesta una missione, mentre il backend rimane disponibile tra un run e l'altro.

Per arrestare il servizio usare `Ctrl+C`, oppure da un altro terminale:

```bash
docker compose down
```

Su Linux, se il proprio utente non ha UID/GID 1000, avviare Compose con gli
identificativi corretti per poter scrivere nella cartella dei dati:

```bash
CFP_UID=$(id -u) CFP_GID=$(id -g) docker compose up --build
```

## Prima simulazione

Premere **Apri JSON** e caricare `examples/single_drone.json`. Il documento
contiene già un drone e una missione completa di decollo, waypoint e atterraggio.
Premere **Esegui simulazione** per avviarla.

Durante il volo, le linee dei waypoint mostrano il percorso programmato e una
traccia distinta mostra quello osservato. **STOP simulazione** interrompe la
prova conservando i dati acquisiti. Al termine, l'archivio permette di selezionare
il run e usare **Apri replay** per rivederlo.

Gli altri esempi sono:

| File | Contenuto |
| --- | --- |
| `three_drones.json` | Tre missioni contemporanee con svolte e cambi di yaw. |
| `single_drone_fast.json` | Una missione con durate più brevi, utile per confrontare gli errori ai target. |
| `negative_obstacle.json` | Un ostacolo interseca il percorso: la verifica geometrica deve segnalarlo. |

## Funzionalità

- **Editor 3D:** configurazione di droni, waypoint, ostacoli, limiti dello
  scenario e criteri di valutazione. Gli oggetti si trascinano sul piano XY;
  tenendo premuto `Ctrl` si attiva lo snap a 10 cm.
- **Importazione ed esportazione JSON:** lo stesso documento descrive lo
  scenario e le missioni e può essere riutilizzato per nuove prove.
- **Verifica ostacoli:** il pulsante dedicato controlla i segmenti del percorso
  programmato considerando il raggio dei droni. È indipendente dalla simulazione;
  gli ostacoli sono aree geometriche, non corpi con collisioni fisiche.
- **Esecuzione multi-drone:** ogni drone segue la propria sequenza di comandi
  `takeoff`, `go_to` e `land`. Il backend gestisce un esperimento alla volta.
- **Monitoraggio:** verifica posizione ai checkpoint, yaw dei waypoint,
  separazione tra droni, limiti dello scenario e continuità dei campioni.
  Il completamento del volo è distinto dal superamento dei criteri; dati
  insufficienti possono rendere la valutazione inconcludente.
- **Archivio e replay:** risultati, eventi, pose e log rimangono consultabili.
  Il replay riproduce i dati registrati senza rilanciare il simulatore.

## Componenti e dati

Godot comunica via HTTP/JSON con il backend, leggendo lo stato a 20 Hz.
Backend e simulatore sono nello stesso container: il runner lavora in un
thread, Crazyswarm2 in un processo separato e i due comunicano tramite ROS 2.

```text
backend/swarm_platform/
  core/          Modello dell'esperimento, piano e verifica geometrica
  runtime/       Runner, monitor, telemetria e registrazione
  ros/           Configurazione e collegamento a Crazyswarm2
  transport/     API HTTP
  service.py     Coordinamento e stato dell'esperimento
  main.py        Avvio del backend
frontend/        Progetto Godot
examples/        Esperimenti pronti da caricare
tests/           Verifiche essenziali senza ROS
docker/          Entrypoint e patch delle dipendenze
data/            Archivio locale, escluso da Git
```

Ogni esecuzione crea `data/runs/<run_id>/` sul computer. La cartella conserva
`experiment.json`, i parametri ROS in `sim.params.yaml`, i campioni in
`frames.jsonl`, gli eventi in `events.jsonl`, il risultato in `result.json`
e i log disponibili. I dati sopravvivono alla rimozione del container.
Lo stato live resta in memoria; registrazione e monitoraggio lavorano sui
campioni completi, indipendentemente dal polling dell'interfaccia.

Compose pubblica la porta HTTP soltanto su localhost. L'API non implementa
autenticazione o cifratura e non è pensata per essere esposta su Internet.

Le dipendenze e la provenienza del modello 3D sono descritte in
[THIRD_PARTY.md](THIRD_PARTY.md).
