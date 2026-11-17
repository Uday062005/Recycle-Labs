# Limitations of the ReSort v2 proposal tool

ReSort returns a PRELIMINARY plant proposal for a small plastic-scrap recycling line (crusher, two screens, sink-float tank, recycle of oversize). It is not an equipment quotation, not a guarantee, and not validated against a real plant.

## What is solid
- The mass balance. Aspen Plus solves the crush-screen-recycle-separate flowsheet; every one of the 210 sweep cases was accepted only after the run-history file showed the loop converged without errors, fresh feed = fines + dense + light within 0.1 % (worst 2.5e-7 %), and all size distributions summing to 1.
- Reproducibility: a fresh run of the whole sweep gives identical results (0 difference in all 630 rows), the refitted surrogate has identical coefficients, and the optimiser returns the same proposal.
- The surrogate reproduces held-out Aspen cases: cross-validated R² 0.98-0.999 (PET purity RMSE 0.0018, PE+PP purity 0.0075, PET recovery 1.2 points, crusher energy 2.1 kWh/t); two optimiser results were also confirmed by real Aspen runs.
- Trends are physical: finer crusher gap -> more fines, more power, less recycle; smaller screen cut -> more recycle; longer tank residence -> more PET recovery; flows and power scale linearly with feed rate (verified to 1e-9).

## What is assumed, not measured (ranked in `assumptions_ranked_v9.md`)
1. **Crusher.** The product size distribution as a function of the gap (Rosin-Rammler, characteristic size = gap) and the crusher energy (a Bond-type model whose effective work index is calibrated to one vendor claim of 20-50 kWh/t). No measured plastic work index or granulator size data were found. Aspen's own crusher power is not used (it is a fixed 1.34 times the hand calculation and cannot take a realistic work index).
2. **Sink-float tank.** Residence time, depth, turbulence spread, flake sphericity, solids loading and polymer densities are assumptions. Purity and recovery depend strongly on them (residence time 10 -> 40 s moves PET recovery 39 -> 85 % and PE+PP purity 0.69 -> 1.00). PET purity in DENSE is about 99.9 % by construction because floaters are almost never dragged down.
3. **Costs.** Equipment prices come from a handful of listings with a 2-5x spread, or have no source at all (screens, tank, auxiliary equipment, installation factor). Product prices, scrap cost, electricity, water, wages and staffing are assumptions. Capex range is only +-30 %; the real vendor spread is wider.
4. **Payback** is simple, undiscounted and dominated by the assumed price gap between products and scrap: with the defaults it ranges from about 1 year to no payback.

## What is not modelled
- PVC and PS (in water they sink with PET and cannot be separated by sink-float), metals, paper, labels, caps, other polymers, contamination, moisture and dirt.
- Washing, drying, colour or metal sorting, dust handling, product transport, selling costs, working capital, tax, financing, and depreciation.
- Tank hydraulics (pumps, dewatering, water treatment); tank energy is not in the optimiser objective.
- Feed particle size distribution as an input (fixed at 12-80 mm, top size 80 mm). Variation of crusher type.

## Where the model must not be used
- Feed rate outside 100-500 kg/h; PET share outside 30-60 %; HDPE:PP far from the simulated mixes (the three compositions lie on one line in composition space, so HDPE:PP is not an independent input).
- Settings outside the simulated ranges: crusher gap 6-14 mm, SCREEN1 cut 5-15 mm, SCREEN2 cut 1-3 mm, residence time 10-40 s, tank spread 0.25-1.0.
- The optimiser's answers often sit at the edge of the ranges (gap 14 mm, SCREEN2 1 mm): a better setting may exist outside them and the surrogate cannot say.
- Equipment is at its practical minimum size at this scale (screen 0.5 m², tank 0.5 m³), so capex hardly depends on the optimised settings.

## Known open items
- Aspen GUI: the FEED > Input > Mixed tab was red in the original case. The v2 case works around it with a 1e-6 kg/h stub in the Mixed substream (no effect on any result; produces harmless "PSD attribute not present in MIXED" warnings in the GUI). Whether the tab is now complete in the GUI was not confirmed by the user.
- Hosting: a deploy-ready bundle exists (`vercel_deploy\`); it has not been deployed or tested on Vercel.
- The surrogate is a fit to 210 simulated cases, not a validated physical plant model; always confirm a chosen design in Aspen before relying on it.
