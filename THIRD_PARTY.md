# Dipendenze e risorse di terze parti

## Software

Il `Dockerfile` installa ROS 2 Jazzy e compila le seguenti revisioni:

| Progetto | Revisione |
| --- | --- |
| Crazyswarm2 (`IMRCLab/crazyswarm2`) | `f1e09954f56cd08e7d9aff5e13dc9a68795914a3` |
| Crazyflie firmware (`bitcraze/crazyflie-firmware`) | `16c5630707e92830dcd16455a57b5560e5838735` |

La patch in `docker/crazyswarm2.patch` viene applicata durante la build.
Le licenze dei progetti restano nei rispettivi sorgenti scaricati nell'immagine.
Il frontend richiede Godot 4.6, installato separatamente.

## Modello Crazyflie

`frontend/assets/Crazyflie_2_1.glb` è un modello visuale fornito per il progetto conservato senza modifiche.
La licenza è inclusa in `frontend/assets/LICENSE_BITCRAZE.txt`.
La licenza del modello riguarda questa risorsa e non assegna una licenza al resto della piattaforma.
