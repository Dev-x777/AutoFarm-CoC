# Clash of Clans Farming Strategy Knowledge Base
**For:** Computer-vision (CV) attack-planning agent  
**Research snapshot:** 2 November 2026  
**Scope:** Home Village multiplayer farming — Gold, Elixir and Dark Elixir  
**Game version caveat:** Clash of Clans changes frequently. Treat this as a strategy reference, not a permanent game-data file. Re-check official release notes and in-game troop availability after every major update.

---

## 1. Mission and operating principles

The agent's job is to choose a profitable, achievable farming attack from the currently visible base.

It must **not** blindly deploy a memorized army. It should:

1. Read the available loot and identify the resource priority.
2. Detect exposed collectors, drills, storages and reachable resource compartments.
3. Estimate the difficulty and risk of reaching each resource.
4. Choose an attack archetype compatible with the player's Town Hall, unlocked troops, troop levels, heroes and spells.
5. Plan a deployment sequence with a funnel, entry point and fallback.
6. Observe the battle after deployment and adapt to what actually happens.
7. Measure the result and store a structured outcome for later strategy selection.

**Primary objective:** maximize useful loot per unit of real time, while achieving the user's chosen risk and star target.

Do not optimize only for destruction percentage or three stars. A farming attack can be successful after taking exposed collectors and leaving the battle early, if the remaining loot is not worth the time or additional deployment.

### Important current-game context

The October 2025 multiplayer change separated ordinary **Battles** from **Ranked Battles**. Ordinary Battles are the farming mode and do not change trophies; Ranked Battles are the trophy/competition mode. League and Star bonuses are linked to the player's Ranked league and Town Hall and can apply to both modes. The Clash Anytime changes removed troop/spell/siege training costs and training time, and heroes no longer need recovery time after attacks. Therefore, old farming advice that prioritizes the cheapest army because of elixir training cost is outdated. Time, reliability, loot access and the player's objective matter more.

Source: https://clashbuilder.com/clash-of-clans/articles/clash-of-clans-farming-guide-loot-faster  
Official mode announcement: https://supercell.com/en/games/clashofclans/blog/

---

## 2. What the CV system must recognize

### 2.1 Resource indicators

| Object | Visual cues | Strategic meaning |
|---|---|---|
| Gold Mine | Mine building, visible gold/resource animation or fill state | High-value target when visibly full |
| Elixir Collector | Collector building with purple liquid | High-value target when visibly full |
| Dark Elixir Drill | Drill with dark liquid | High priority when Dark Elixir is the goal |
| Gold Storage | Large gold-storage building | Usually contains a portion of the base's stored Gold |
| Elixir Storage | Purple storage building | Usually contains a portion of stored Elixir |
| Dark Elixir Storage | Dark, compact storage building | Important high-value target for DE farming |
| Town Hall | Town Hall model/level-specific appearance | Town Hall level, weapon threat at higher levels, possible star objective |
| Clan Castle | Clan Castle building | May contain defending Clan Castle troops |
| Builder's Hut | Small hut | Can repair nearby buildings at higher levels; not a resource target |

**Do not infer collector fullness from building identity alone.** Fullness can be indicated by liquid/resource appearance, visual animation, amount of loot shown, or other game-version-specific visual cues. Train and validate the detector against screenshots from the current game version.

### 2.2 Defensive structures and threats

Detect at least:

- Cannons, Archer Towers, Mortars, Wizard Towers
- Air Defenses, Air Sweepers, Hidden Teslas when revealed
- X-Bows, Inferno Towers, Eagle Artillery where present
- Scattershots, Monolith, Spell Towers, Ricochet/other newer defenses where present
- Walls, gates/openings, compartments and narrow corridors
- Traps only when revealed or inferable from a known trigger event
- Defensive Clan Castle troops and defending heroes
- Town Hall weapon, Giga/poison effects or current equivalent, if applicable

The detector should output **object class, bounding box, confidence, estimated level if visible, and whether the object is confirmed or uncertain**. Never treat an unseen trap as confirmed.

### 2.3 Troops and battle state

Recognize:

- Player troop/spell/hero/siege bar and remaining quantities
- Troops already deployed and their approximate positions
- Hero ability availability and activation state
- Spell effects and duration where visible
- Deployment-side coordinates
- Battle timer, destruction percentage, stars and loot gained
- End-battle/return controls

Keep a distinction between **available troops**, **deployed troops**, **troops still alive**, and **troops whose status is uncertain**.

---

## 3. Farming economics and target scoring

### 3.1 Current loot rules (reference values)

The following values are from a farming guide updated 20 October 2026. They are useful as a prior, but the agent should trust the live loot panel and current game rules over hard-coded estimates.

- Gold and Elixir from collectors: approximately **50%** of the uncollected amount.
- Dark Elixir from drills: approximately **75%** of the uncollected amount.
- Storage loot is a smaller percentage, with a Town Hall-dependent cap.
- Loot is adjusted by the difference between the attacker's and defender's Town Hall levels.
- League Bonus and Star Bonus can materially affect the total reward.

Illustrative storage loot caps per attack (Gold/Elixir each; Dark Elixir):
| Attacker TH | Gold/Elixir cap | DE cap |
|---:|---:|---:|
| TH7 | 360,000 | 2,000 |
| TH8 | 480,000 | 2,400 |
| TH9 | 560,000 | 4,700 |
| TH10 | 595,000 | 5,000 |
| TH11 | 700,000 | 5,500 |
| TH12 | 980,000 | 6,000 |
| TH13 | 1,260,000 | 7,500 |
| TH14 | 1,400,000 | 8,700 |
| TH15 | 1,540,000 | 9,200 |
| TH16 | 1,610,000 | 9,500 |
| TH17 | 1,680,000 | 9,800 |
| TH18 | 1,750,000 | 10,100 |

These are caps, not guaranteed loot. Do not estimate exact loot from a storage's appearance unless the game exposes enough information to do so.

### 3.2 Target value

For each candidate target or group of targets, estimate:

`expected_value = expected_gold + wE * expected_elixir + wD * expected_dark_elixir + expected_bonus`

The weights `wE` and `wD` must reflect the player's current upgrade goals. For example, if the next upgrade needs Dark Elixir, increase `wD`; do not assume all resources are equally valuable.

Estimate attack cost in **time and risk**, not old troop training cost:

`target_score = expected_value * probability_of_success - time_penalty - troop_loss_penalty - risk_penalty`

A practical target score should include:

- Loot shown in the pre-attack panel
- Resource priority
- Collector/drill fullness and accessibility
- Distance from the outside edge
- Number and type of defenses covering the target
- Walls and compartments between troops and target
- Town Hall difference and loot penalty/bonus
- Whether a win is needed to collect the League Bonus
- Whether the army can realistically reach the loot

### 3.3 Base acceptance rules

Use configurable thresholds, not a fixed universal minimum.

**Prefer a base when:**
- Displayed loot meets the user's minimum.
- Multiple collectors/drills appear full and are exposed.
- Storages are near the perimeter or reachable with the selected army.
- The base is inactive/poorly maintained and defenses are weak, if this is supported by visible evidence.
- The army can secure the required amount of loot without spending excessive time.

**Skip a base when:**
- Loot is below the minimum.
- Most loot appears deep behind strong defenses and the selected army cannot penetrate.
- The base has a large Town Hall mismatch that sharply reduces loot.
- The visible loot distribution does not match the army's strengths.
- The agent cannot confidently interpret the screen.

Do not use a single visual clue (such as tombstones) as proof that a base is inactive.

---

## 4. Farming strategy catalogue

The compositions below are **archetypes**, not universal fixed army recipes. Exact counts depend on Town Hall, army capacity, troop unlocks, troop levels, spell capacity and current balance. The agent must build a valid composition from the player's actual army rather than inventing unavailable units.

### A. Collector sniping / edge farming

**Best for:** exposed Gold Mines, Elixir Collectors and Dark Elixir Drills; quick resource grabs.

**Typical units:** Goblins, Sneaky Goblins, Minions, Archers or other cheap-to-deploy ranged units that the player has available.

**Plan:**
1. Detect all visible collectors/drills around the perimeter.
2. Rank them by estimated loot, exposure and nearby defensive coverage.
3. Identify safe deployment tiles within the unit's range and pathing constraints.
4. Deploy a small test group at one or two separated targets.
5. Observe whether defenses acquire the troops and whether the buildings are being damaged.
6. Continue with the remaining exposed targets only if the expected loot justifies it.
7. Avoid deploying the entire army if the farming objective has already been met.

**Failure modes:** collector is not full; a defense covers the whole edge; troops choose a different target; traps or splash damage eliminate the group.

### B. Goblin / Sneaky Goblin farming

**Best for:** resource buildings, especially when the agent can identify a route to storages.

**Why it works:** Goblins prioritize resource buildings and deal bonus damage to them. Sneaky Goblins add temporary invisibility, making them useful for reaching exposed or semi-protected resource targets.

**Plan:**
1. Separate resource buildings into exposed, wall-protected and deep targets.
2. Use small groups to remove exposed collectors first.
3. For deeper targets, identify the shortest safe path and required wall-opening/jump support.
4. Use Jump Spells or a suitable siege/entry tool only when it creates a real route to valuable targets.
5. Time invisibility-aware deployment so Sneaky Goblins are not revealed while crossing into concentrated defenses.
6. Do not assume invisibility makes them invulnerable; splash, traps, timing and target selection still matter.

**Common variants:**
- Pure collector sniping: small groups against exposed collectors/drills.
- Storage dive: Sneaky Goblins supported by Jump Spells and/or a wall-opening siege machine.
- Mixed goblin support: regular tanking/cleanup units create a safer route for Goblins.

**Failure modes:** poor timing, a resource building is not the troop's selected target, the route is blocked, or the target is protected by splash/area defenses.

### C. BARCH (Barbarians + Archers)

**Best for:** lower and mid Town Halls, exposed collectors and weak outer rings.

**Plan:**
1. Use Barbarians as a front line where single-target defenses need distraction.
2. Place Archers behind them, spread out to reduce splash damage.
3. Attack multiple exposed sides instead of stacking all units in one spot.
4. Avoid Mortars/Wizard Towers and other splash coverage.
5. Stop once the resource objective is reached.

**Strengths:** simple, flexible, easy to reason about.  
**Weaknesses:** poor against well-protected collectors and strong splash coverage.

### D. Baby Dragon farming

**Best for:** spread-out exterior collectors and bases with isolated resource buildings.

**Plan:**
1. Detect air-targeting defenses and Air Sweepers.
2. Identify isolated collectors outside strong air-defense coverage.
3. Space Baby Dragons apart to preserve their solo-unit rage bonus where applicable.
4. Deploy along a line or selected side rather than clustering them.
5. Keep spells for the highest-value threat or a route to additional loot.
6. Avoid sending the whole group into overlapping Air Defenses.

**Strengths:** forgiving, can pick off separated buildings.  
**Weaknesses:** vulnerable to concentrated air defenses and poor against deep storages without a plan.

### E. Mass Miners / Miner-based farming

**Best for:** bases where resource buildings and storages are reachable through a ground route and the player's Miner levels are strong.

**Plan:**
1. Find a broad entry edge and a path toward the resource-rich core.
2. Create a funnel so Miners do not split around the outside.
3. Deploy the main group in a controlled line or compact wave.
4. Use Heal or other available support when the group enters sustained damage.
5. Use a Wall Wrecker or other suitable siege option only if it improves access for supporting troops; Miners themselves travel underground.
6. Monitor whether the group is moving toward the intended storages rather than circling the base.

**Strengths:** can move through walls and reach internal targets.  
**Weaknesses:** pathing can spread; traps and concentrated damage can reduce value; requires more timing than edge farming.

### F. Super Barbarian farming

**Best for:** fast pressure on exposed buildings and outer rings when Super Barbarians are unlocked.

**Plan:**
1. Identify an edge with multiple reachable resource buildings.
2. Deploy small groups across several points to avoid one splash-defense kill zone.
3. Use their ability window/boost effectively; do not waste it before they reach targets.
4. Use remaining troops to reach a second layer only if expected loot is high.
5. Track whether the outer ring is being cleared or troops are being pulled away from resource buildings.

**Strengths:** fast, straightforward pressure.  
**Weaknesses:** can be stopped by splash coverage and may not reach deep storages.

### G. Dragon / Electro Dragon farming

**Best for:** robust attacks where the player wants a higher chance of winning and the base offers a favorable air entry.

**Plan:**
1. Detect Air Defenses, Air Sweepers, Monolith/other high-threat defenses and the direction they face.
2. Select an entry that reduces exposure to the strongest air-defense cluster.
3. Use a few units to establish a funnel on both sides.
4. Deploy the main air force only after the funnel is visible.
5. Keep support spells for the central threat zone; avoid spending all spells on the outer ring.
6. Watch for Electro Dragons chaining across buildings; spacing and building proximity affect value.
7. Do not assume an air army will automatically reach storages.

**Strengths:** simple deployment compared with precision ground armies; can clear large sections.  
**Weaknesses:** air defenses and sweepers can dominate the result; slower or less loot-efficient when targets are scattered.

### H. Hybrid / Hog-and-Miner farming

**Best for:** players with the required troops and heroes who want a reliable core push through defensive compartments.

**Plan:**
1. Use a Queen Charge or other controlled entry if the player's hero and spell levels support it.
2. Remove one side of the base and create a funnel.
3. Send Miners and Hog Riders through the remaining lane.
4. Use Heal spells over predictable high-damage zones, not after the army has already died.
5. Use Warden ability or equivalent protection for the largest incoming damage window.
6. Monitor pathing and remaining defenses; deploy cleanup only where it will survive.

**Strengths:** can reach the core and deal with many defensive layouts.  
**Weaknesses:** requires hero availability, spell timing and more sophisticated path planning; not the first choice for a simple collector-only raid.

### I. Ground smash / tank-and-support farming

**Examples:** Giants, Golems, Yetis, P.E.K.K.A, Witches, Bowlers or other unlocked ground combinations.

**Best for:** bases with a clear entry lane and valuable storages behind walls.

**Plan:**
1. Choose one side with a path toward the largest resource cluster.
2. Create a funnel with a small number of support troops.
3. Deploy tanks first, then damage/support troops behind them.
4. Open walls or use a siege machine when the route requires it.
5. Use Rage/Heal/Freeze or other spells based on the actual threat and troop composition.
6. Keep the force concentrated enough to enter the core, but avoid a single narrow splash-damage kill zone.

**Strengths:** can break through compartments and reach storages.  
**Weaknesses:** expensive in time/complexity; poor funneling can cause troops to walk around the base.

### J. Dark Elixir focused farming

**Best for:** when Dark Elixir is the user's highest-priority resource.

**Plan:**
1. Give Dark Elixir Drills and the Dark Elixir Storage a higher target weight.
2. Prefer full exposed drills first because they are often easier to reach.
3. If the storage is deep, choose a Goblin/Sneaky Goblin dive, Miner route or a strong ground entry depending on the available army.
4. Avoid spending the entire army to reach a small amount of DE.
5. Record DE gained per minute and the success rate for each strategy.

**Important:** the best DE strategy depends on the drill fullness, storage position, Town Hall matchup and available troop levels. Do not always attack the central storage if the drills contain more accessible loot.

---

## 5. Strategy selection decision tree

Use this order:

1. **Read the live loot panel.** If below the configured minimum, skip.
2. **Determine resource priority.** Gold, Elixir, Dark Elixir or balanced.
3. **Find exposed full collectors/drills.**
   - Many exposed targets: collector sniping, Goblins/Sneaky Goblins, BARCH or Baby Dragons.
   - Few exposed targets: inspect storages and core access.
4. **Check storage accessibility.**
   - Near edge/open compartments: Goblin/Sneaky Goblin or a direct ground push.
   - Deep behind walls: Miner, Hybrid or ground smash if available.
   - Deep and heavily defended: skip unless loot is exceptional and the army is strong enough.
5. **Check defense profile.**
   - Strong Air Defenses/Sweepers: avoid blind air spam.
   - Heavy splash on edge: avoid tightly grouped small troops.
   - Strong core single-target damage: use tanks, freezes or a different route.
6. **Check player capability.** Only choose troops, spells, heroes and siege machines that are actually available and sufficiently upgraded.
7. **Estimate success probability and time.** Choose the highest expected-value option, not the most fashionable strategy.
8. **Deploy incrementally and observe.** Re-plan when actual troop movement differs from predicted pathing.

Pseudo-code:

```python
def choose_farming_plan(base, player, objective):
    if base.visible_loot < objective.minimum_loot:
        return Skip("loot_below_threshold")

    targets = detect_and_rank_resources(base, objective.weights)
    exposed = [t for t in targets if t.is_exposed and t.estimated_value > 0]
    core_targets = [t for t in targets if not t.is_exposed]

    if enough_value(exposed, objective):
        candidates = [
            collector_sniping(player, exposed),
            goblin_or_sneaky_goblin(player, exposed),
            barch_if_available(player, exposed),
            baby_dragon_if_safe(player, exposed, base.defenses),
        ]
    else:
        candidates = [
            goblin_storage_dive(player, core_targets, base),
            miner_route(player, core_targets, base),
            hybrid_route(player, core_targets, base),
            ground_smash_route(player, core_targets, base),
            dragon_route_if_air_safe(player, core_targets, base),
        ]

    valid = [p for p in candidates if p.is_unlocked and p.is_valid_for_army]
    if not valid:
        return Skip("no_valid_strategy")

    return max(
        valid,
        key=lambda p: (
            p.expected_loot * p.success_probability
            - p.expected_time_penalty
            - p.risk_penalty
        )
    )
```

This is conceptual pseudocode. The actual agent must use measured estimates and handle uncertainty.

---

## 6. Computer-vision attack planner

### 6.1 Suggested perception output

Represent every detected object in normalized screen coordinates (0.0 to 1.0):

```json
{
  "screen_state": "enemy_base_scout",
  "town_hall_level_estimate": 15,
  "loot_panel": {
    "gold": 850000,
    "elixir": 620000,
    "dark_elixir": 7200
  },
  "objects": [
    {
      "class": "gold_mine",
      "bbox": [0.08, 0.32, 0.14, 0.40],
      "confidence": 0.94,
      "fullness": "high",
      "access": "outside_wall",
      "threats": ["archer_tower"]
    }
  ],
  "defenses": [],
  "walls_and_gaps": [],
  "army": {
    "available_troops": [],
    "available_spells": [],
    "heroes_available": [],
    "siege_available": []
  }
}
```

This is an example schema only. Do not copy the sample Town Hall or loot values into runtime assumptions.

### 6.2 Map screen positions to the village grid

- Estimate the playable village boundary and perspective.
- Convert screen coordinates to a stable normalized grid.
- Detect building footprints, not just center pixels.
- Maintain a map of occupied tiles, wall segments and open paths.
- Use a calibration step after screen resize, zoom or UI layout changes.
- Re-detect after major animation, camera movement or interface transition.

Do not assume the base is perfectly aligned to the screenshot. Use perspective-aware geometry or a learned grid transform.

### 6.3 Threat and reachability map

For each candidate deployment tile, estimate:

- Distance to target
- Whether a wall blocks the path
- Likely troop target preference
- Defenses whose range overlaps the route
- Splash damage overlap
- Air vs ground compatibility
- Nearby resource targets that may pull troops away
- Unknown/trap risk

The threat map should be probabilistic. Hidden traps and unrevealed defenses are unknown, not absent.

### 6.4 Deployment controller

Use a finite-state controller:

`SCOUT -> CLASSIFY -> PLAN -> DEPLOY_TEST -> OBSERVE -> CONTINUE_OR_ADAPT -> FINISH -> EVALUATE`

- **SCOUT:** wait for the base screen and stable visual state.
- **CLASSIFY:** detect loot, resources, defenses, walls and army.
- **PLAN:** rank targets and choose the strategy.
- **DEPLOY_TEST:** deploy a small initial group when appropriate.
- **OBSERVE:** verify target selection, movement and survival.
- **CONTINUE_OR_ADAPT:** deploy the next group, change entry or stop.
- **FINISH:** end only when the configured loot/star objective is met or further action has negative expected value.
- **EVALUATE:** read final loot and destruction, then save the outcome.

Use confidence thresholds and an explicit `UNKNOWN` state. If the screen is ambiguous, pause and request human review rather than issuing a risky sequence of taps.

---

## 7. Learning from attacks

A strategy cannot improve if the agent stores only "win" or "loss". Log each attack:

```json
{
  "timestamp": "ISO-8601",
  "game_version": "unknown_or_detected",
  "player_town_hall": 0,
  "defender_town_hall_estimate": 0,
  "strategy": "sneaky_goblin_storage_dive",
  "objective": "dark_elixir",
  "loot_before": {"gold": 0, "elixir": 0, "dark_elixir": 0},
  "loot_after": {"gold": 0, "elixir": 0, "dark_elixir": 0},
  "stars": 0,
  "destruction_percent": 0,
  "duration_seconds": 0,
  "deployment_plan_id": "id",
  "observed_failures": [],
  "perception_confidence": 0.0
}
```

All zeroes are placeholders, not real game values.

Track these metrics per strategy and Town Hall matchup:

- Gold, Elixir and Dark Elixir gained per attack
- Weighted loot gained per minute
- Win rate and star distribution
- Percentage of target loot captured
- Troop survival / unused troop rate where measurable
- Failed pathing rate
- Perception error rate
- Strategy selection confidence
- Number of skipped bases before a successful target

### Learning loop

1. Save the initial screenshot and perception output.
2. Save the selected strategy and intended deployment points.
3. Save short observation snapshots during the battle.
4. Compare actual troop movement with predicted movement.
5. Save final loot and battle result.
6. Label failure causes: wrong detection, wrong fullness estimate, bad target choice, bad path, poor funnel, spell timing, defense misclassification or UI action error.
7. Update strategy scores only after enough comparable examples.
8. Keep separate performance statistics by Town Hall, troop level, army composition and base archetype.

Do not let one unusually good or bad attack rewrite the strategy policy. Use rolling averages or a contextual bandit with minimum sample counts.

---

## 8. Common agent mistakes to prevent

- Treating every resource building as full.
- Confusing a storage with a collector or drill.
- Attacking the Town Hall when the objective is loot and the Town Hall is not valuable or reachable.
- Deploying every troop at one coordinate.
- Failing to create a funnel before a core push.
- Sending ground troops toward an inaccessible compartment.
- Using air troops without checking Air Defenses and Air Sweepers.
- Using spells before the main army reaches the relevant threat.
- Assuming a troop will target the building the agent wants it to target.
- Ignoring the actual troop bar and selecting locked/unavailable units.
- Applying old training-cost logic after the Clash Anytime changes.
- Optimizing for three stars when the user only needs a resource target.
- Continuing an attack after the expected remaining loot is lower than the time/risk cost.
- Treating low-confidence detections as facts.

---

## 9. Practical evaluation scenarios

Build a test set with screenshots and known labels for at least these base archetypes:

1. Full collectors outside the walls, weak defenses.
2. Full collectors outside the walls, heavy splash coverage.
3. Exposed Dark Elixir Drills, central DE Storage.
4. Storages near the outer ring.
5. Storages deep in a compact core.
6. Spread-out base with many isolated buildings.
7. Ring base with buildings around the perimeter.
8. Compartment base with narrow entry lanes.
9. Strong air defense coverage.
10. Weak air defense coverage but strong ground defenses.
11. Low displayed loot despite visually full-looking buildings.
12. Higher Town Hall defender with a loot bonus/penalty matchup.

For every test, score:
- Resource detection precision/recall
- Fullness classification accuracy
- Defense detection accuracy
- Strategy selection accuracy
- Target loot captured
- Loot per minute
- Unnecessary troop deployment
- Safe handling of uncertain screens

Use a held-out test set. Do not evaluate only on the same screenshots used to tune the policy.

---

## 10. Version and balance maintenance

The game changes over time. In the 2026 update cycle, Town Hall 18 and newer content, troop/hero/pet levels, Supercharges and balance changes affect what is viable. For example, official 2026 release notes announced additional TH18 pet and Supercharge levels, while October 2026 balance tracking reports changes affecting units including Hog Rider, Super Hog Rider, Miner, Super Miner, P.E.K.K.A and Meteor Golem. These details can alter the relative value of attack archetypes.

At startup or after a detected update:
1. Read the current game version if available.
2. Check official release notes.
3. Revalidate troop names, unlocks, levels and spell behavior.
4. Re-run the screenshot test suite.
5. Mark unverified compositions as `needs_validation`.
6. Never silently assume a balance change did not affect a strategy.

Useful sources:
- Supercell official Clash of Clans news and release notes: https://supercell.com/en/games/clashofclans/blog/
- Supercell support: https://support.supercell.com/clash-of-clans/en/
- Farming mechanics and loot guide (updated 20 Oct 2026): https://clashbuilder.com/clash-of-clans/articles/clash-of-clans-farming-guide-loot-faster
- 2026 strategy overview (secondary source; not an official balance authority): https://www.ezarena.com/blog/best-attack-strategies-for-every-town-hall-2026
- Balance-change history (community-maintained; verify against official notes): https://coc.tools/changes

**Source hierarchy:** in-game behavior and official Supercell notes first; current, tested community guides second; old videos and static army lists last.

---

## 11. Recommended first implementation

Do not attempt to master every army archetype in the first version.

**Phase 1 — Reliable perception**
- Detect loot panel, Town Hall, collectors, drills, storages, walls and major defenses.
- Output confidence scores and unknown labels.
- Save annotated screenshots for review.

**Phase 2 — Simple farming**
- Implement collector sniping and Goblin/Sneaky Goblin target ranking.
- Start with exposed resource buildings.
- Measure loot gained per minute and target detection accuracy.

**Phase 3 — Layout-aware attacks**
- Add pathfinding, threat maps, splash coverage and wall/compartment reasoning.
- Add Baby Dragon and BARCH as alternative archetypes where unlocked.

**Phase 4 — Core access**
- Add Miner, Hybrid and ground-smash planning only after the agent can reliably infer paths and troop movement.

**Phase 5 — Learning**
- Store attack episodes, classify failures and update strategy scores using comparable examples.
- Add automatic regression tests after every model or policy change.

The first milestone is not "three-star every base." It is: **correctly identify profitable bases, take accessible loot consistently, and explain why the selected strategy is appropriate.**

---

## 12. Important operational note

This document describes game strategy and a CV research workflow. Automated gameplay may be restricted by Supercell's Terms of Service or fair-play rules, and can risk account sanctions. Review the current rules and use a permitted test environment or human-supervised setup. Do not build features intended to evade anti-cheat or platform protections.
