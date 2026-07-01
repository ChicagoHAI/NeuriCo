# NeuriCo — Battery Lab (BL) Mode

BL mode is a battery-lab specialization of NeuriCo. It turns the autonomous
research framework into a closed loop with a **physical** coin-cell lab: NeuriCo
designs electrolyte recipes, a human builds and measures them on the
[BatteryLab](https://github.com/…/BatteryLab) robot, the results come back, and
NeuriCo decides what to try next. Unlike a normal one-shot NeuriCo run, a BL
campaign is **long and repeated** — many design → build → measure → interpret
cycles over a single research idea.

---

## Why BL mode is different

The standard NeuriCo interactive pipeline is *resource finder → experiment runner
→ paper writer*, all inside Docker. BL mode keeps resource finding and
computational reasoning, but the **decisive experiment is run by a human on real
hardware**, not by an in-container agent:

```
   idea (YAML)
      │
      ▼
   resource finder  ── literature on water activity, Zn electrolytes, co-solvents
      │
      ▼
   experiment runner ── computational design / screening (no wet experiment)
      │
      ▼
   DELIVER RECIPES  ── BatteryLab JSON written to BL-recipes/   ◄── the handoff
      │
      ▼
   (human builds & measures cells on BatteryLab; drops raw data in BL-results/)
      │
      ▼
   INGEST RESULTS   ── read BL-results/, update the world model
      │
      └──────────────► design the next batch (repeat, indefinitely)
```

The physical experiment runner is a **person**. BL mode never asks an in-Docker
agent to "run" a cell build or an electrochemical measurement — it emits a recipe
and waits.

---

## The recipe format (BatteryLab solvency JSON)

A recipe file is a JSON **array**; each element is one coin cell. This is the
exact format BatteryLab's `app.py` **[B]atch** loader accepts:

```json
[
  {
    "recipe_name": "wa_ladder_cell_01",
    "target_electrolyte": {
      "name": "wa_ladder_target_01",
      "volume": 0.05,
      "v": {"water": 0.8, "propylene glycol": 0.2},
      "s": {"ZnOTf2": 1.0},
      "a": {"MnSO4": 0.1}
    }
  }
]
```

| Field | Meaning | Units / rules |
|---|---|---|
| `recipe_name` | Unique, human-readable cell id | string |
| `target_electrolyte.name` | Name of the formulation | string |
| `volume` | Total electrolyte volume | **millilitres** (`0.05` = 50 µL), > 0 |
| `v` | **Solvent** volume fractions | required, non-negative, **must sum to 1.0** |
| `s` | **Salt** molarities | optional, mol/L |
| `a` | **Additive** molarities | optional, mol/L |

Mnemonic: **v** = sol**v**ent blend, **s** = **s**alt, **a** = **a**dditive.
`v` and `s` are independent axes — `v` sets the solvent *proportions*, `s` sets
the salt *concentration*, and `volume` scales both. There is no manual "v-to-s
ratio": molarity already fixes the salt amount per unit volume, and the solvent
fills the rest. The BatteryLab electrolyte planner converts these targets into
actual pipetting volumes from its stock solutions.

---

## The research target this mode was built for

The driving question is the relationship between **water activity (a_w)** and
performance — **ionic conductivity** and **Coulombic efficiency (CE)** — in Zn
batteries, which is still unsettled in the field. We want to identify *when water
activity is a transferable descriptor and when it fails*, and thereby reveal
molecular design rules for suppressing parasitic water reactions without
sacrificing Zn²⁺ transport.

The core trade-off BL campaigns explore (from literature anchors):

| Regime | a_w | Stability window | Conductivity | CE |
|---|---|---|---|---|
| Water-rich (dilute ZnSO₄) | ~0.9 | narrow | high | lower |
| Hydrated eutectics (HDES) | ~0.35–0.65 | medium | medium | high |
| Deep eutectic / water-in-salt | ~0.02–0.15 | wide | low | highest |

Lowering a_w widens the stability window and raises CE but reduces conductivity —
so the science lives in finding where the descriptor predicts the sweet spot, and
where it breaks.

---

## Using BL mode today (normal mode — recipe generation)

The minimum viable loop uses **normal (non-interactive) mode** to generate a batch
of recipes and stop. No wet-lab automation is required — you relay the recipe to
the lab yourself.

1. Write an idea (`domain: battery`) whose **deliverable is a recipe file** in the
   format above (see `ideas/examples/bl_water_activity_ladder.yaml` for a worked example).
   The idea's `expected_outputs` and `evaluation_criteria` are what steer the agent
   to emit recipes rather than a computational report.
2. Submit and run, stopping after the experiment runner:

   ```bash
   ./neurico submit ideas/<your_idea>.yaml
   ./neurico run <idea_id> --no-write-paper --no-github --provider claude
   ```

   - `--no-write-paper` → pipeline stops after the experiment runner.
   - `--no-github` → stays local.
   - `--provider claude` → uses the Claude CLI credentials (no API key needed).
3. The recipe JSON lands in the run's workspace. Copy it out and send it to the
   lab; results come back into `BL-results/`.

### Grounding recipes in data

Recipe design is far stronger when the idea points the agent at real inputs — a
trained water-activity dataset, a ranked candidate list, and literature a_w↔
performance anchors — so the agent *translates* model-ranked candidates into
BatteryLab recipes (handling mole-fraction → volume-fraction conversion, salt
identity, and ionic-strength → molarity) rather than inventing compositions from
scratch.

---

## Closed-loop mode (in progress)

For the full autonomous campaign, BL mode extends **interactive mode** (the manager
+ world-model variant) with a `deliver_recipe` manager tool: it validates a recipe
batch, writes it to `BL-recipes/round-N/`, shows it to the human, and **pauses** —
the wet-lab analogue of launching an agent. When results return, an ingest step
folds them back into the world model and the manager designs the next round. This
is what makes a BL run "very long and repeated."

Status:
- [x] Recipe schema + validation (mL units, `v` sums to 1, numeric `s`/`a`).
- [x] `deliver_recipe` tool (write + pause), battery manager prompt, domain routing.
- [x] Normal-mode recipe generation via idea `expected_outputs`.
- [ ] `ingest_results` — read arbitrary files from `BL-results/` (EIS/Nyquist
      screenshots, CSVs, `.mpr`, photos) and update the world model.
- [ ] Auto-sync delivered recipes to a shared `BL-recipes/` folder.
- [ ] Direct link to the BatteryLab robot (today the human relays recipes/results).

---

## Folder conventions

| Path | Contents |
|---|---|
| `BL-recipes/` | Recipe batches NeuriCo produces (`idx-N.json` / `round-N/`) |
| `BL-results/` | Raw wet-lab results the lab returns, one folder per experiment (e.g. `idx-0/`); any file type |
| `ideas/*.yaml` | Battery-domain ideas whose deliverable is a recipe batch |
| `templates/domains/battery/` | Battery domain guidance for the agents |
