# Assumptions ranked by how much they change the result (V9 sensitivity run)

Base case: PET 45 % (45/30/25), 300 kg/h, crusher gap 10 mm, SCREEN1 10 mm, SCREEN2 2 mm, residence time 20 s, tank spread 0.5, 2000 h/y.
Technical rows: Aspen re-run (two passes) with one assumption changed. Economic rows: cost model with one constant changed (others at base). Data: `data/sensitivity_v9.csv`, script `sensitivity_v9.py`.
Score = largest relative change (%) of any key output versus the base case, over the low and high value. Economic scores are large because the base net cash is small (USD 10.9k/y, payback 8.6 y at these settings).

## A. Technical assumptions (base: PET purity 0.9995, PE+PP purity 0.942, PET recovery 78.6 %, crusher energy 63.4 kWh per tonne of fresh feed)

| Rank | Assumption (base) | Low -> high tested | PE+PP purity | PET recovery % | Crusher kWh/t | Score |
|---|---|---|---|---|---|---|
| 1 | Crusher product size / gap, A (1.0) | 0.8 -> 1.25 | 0.937 / 0.945 | 76.0 / 80.5 | 71.9 / 57.7 | 58 % |
| 2 | Tank residence time (20 s) | 10 -> 40 s | 0.691 / 1.000 | 38.7 / 85.1 | 63.4 / 63.4 | 51 % |
| 2 | Tank depth (1.0 m) | 0.5 -> 2.0 m | 1.000 / 0.691 | 85.1 / 38.7 | 63.4 / 63.4 | 51 % (same effect as residence time: only H/tau matters) |
| 4 | Crusher PSD spread n (1.45) | 1.2 -> 1.8 | 0.937 / 0.948 | 71.9 / 85.2 | 59.3 / 68.2 | 46 % |
| 5 | Crusher energy calibration (35 kWh/t) | 20 -> 50 kWh/t | 0.942 / 0.942 | 78.6 / 78.6 | 36.2 / 90.6 | 43 % (energy and cost only) |
| 6 | Tank turbulence spread sigma (0.5) | 0.25 -> 1.0 | 0.992 / 0.852 | 84.2 / 67.7 | 63.4 / 63.4 | 14 % |
| 7 | Flake sphericity (0.6) | 0.5 -> 0.8 | 0.890 / 0.997 | 72.2 / 84.8 | 63.4 / 63.4 | 8 % |
| 8 | Slurry solids fraction (5 %) | 2 -> 10 % | 0.960 / 0.902 | 80.7 / 73.8 | 63.4 / 63.4 | 6 % |
| 9 | Polymer densities (1380/950/905) | 1340/940/890 -> 1400/970/920 | 0.925 / 0.949 | 76.6 / 79.5 | 63.4 / 63.4 | 3 % |
| 10 | Bubble-attachment floor for HDPE/PP (0) | 0 -> 0.02 | 0.942 / 0.941 | 78.6 / 78.6 | 63.4 / 63.4 | 3 % (PET purity 0.974 at 0.02) |
| 11 | Water temperature (25 C) | 10 -> 40 C | 0.943 / 0.942 | 78.8 / 78.7 | 63.4 / 63.4 | 0 % |

Reading: the crusher product-size mapping (A, n) and the tank design values (residence time, depth) dominate the technical results; all of them are assumptions without measured data. Tank depth and residence time are equivalent (v_crit = H / tau).

## B. Economic assumptions (base: capex USD 93.6k, net cash USD 10.9k/y, payback 8.6 y)

| Rank | Assumption (low / base / high) | Net cash change (low / high) | Payback (low / high) |
|---|---|---|---|
| 1 | Scrap purchase price (150 / 250 / 350 USD/t) | +549 % / -549 % | 1.3 y / none |
| 2 | PE/PP flake price (300 / 400 / 550) | -270 % / +405 % | none / 1.7 y |
| 3 | PET-rich flake price (300 / 400 / 600) | -194 % / +389 % | none / 1.8 y |
| 4 | Operator wage (4 / 8 / 15 USD/h) | +146 % / -256 % | 3.5 y / none |
| 5 | Operators per shift (1 / 2 / 3) | +146 % / -146 % | 3.5 y / none |
| 6 | Crusher reference cost (10k / 20k / 60k USD at 30 kW) | +14 % / -55 % (capex -32 % / +128 %) | 5.1 y / 43 y |
| 7 | Auxiliary equipment factor (0.5 / 1 / 2) | +11 % / -21 % (capex -25 % / +50 %) | 5.8 y / 16.4 y |
| 8 | Screen reference cost (3k / 6k / 12k) | +5 % / -11 % | 7.1 y / 12.1 y |
| 9 | Electricity price (0.07 / 0.10 / 0.15 USD/kWh) | +15 % / -24 % | 7.5 y / 11.4 y |
| 10 | Installation factor (1.3 / 1.5 / 1.8) | +6 % / -9 % | 7.0 y / 11.3 y |
| 11 | Maintenance fraction (3 / 5 / 7 %) | +17 % / -17 % | 7.3 y / 10.3 y |
| 12-15 | Tank cost, auxiliary power, water price, product moisture | under 10 % | 7.9-9.9 y |

Reading: payback is decided by the price gap between products and scrap and by labour. With these defaults it ranges from about 1 year to "no payback". Equipment-cost assumptions matter much less than prices and wages.

## What to do with this

1. Replace the three prices (scrap, PET-rich flake, PE/PP flake), operator count and wage with real local numbers first.
2. Measure or get data for the crusher product size at a given screen/gap and for the sink-float tank (residence time, depth, turbulence): these set purity, recovery and energy.
3. Everything else changes the result by less than the uncertainty already stated.
