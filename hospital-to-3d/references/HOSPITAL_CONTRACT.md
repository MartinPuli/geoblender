# Hospital construction contract

## Detection

Accept `amenity=hospital|clinic`, `healthcare=hospital|clinic`,
`building=hospital`, normalized hospital building use, `scene_kind=hospital`, or
the explicit `hospital` specialization. Never trigger from a name alone.

## Required layers

- Mapped building wings and parts from the architectural builder.
- Public entrance canopy with supports and glazed sliding-door plane.
- Clearly separated emergency/ambulance bay and ground markings.
- Facade medical sign attached to the main semantic building.
- Coherent rooftop mechanical units.
- Helipad only when mapped, explicitly requested, or allowed by the roof-area
  auto threshold.

## Provenance

Building massing is OSM/verified data. Canopies, signs, emergency markings,
roof plant and automatic helipads are procedural inference unless independently
mapped. Never claim shallow facade interiors as medical floor plans.

## Evaluation gates

- `min_hospital_sites`
- `min_hospital_canopies`
- `min_hospital_emergency_bays`
- `min_hospital_medical_crosses`
- `min_hospital_roof_units`
- `min_hospital_helipads` only when required by the run

