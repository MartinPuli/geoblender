# Urban amenities contract

## Supported grammars

- Furniture: bench, waste basket, drinking water, bicycle parking, picnic table,
  recycling container, post box, telephone and clock.
- Street systems: lamp, bollard, gate, fire hydrant, street cabinet and utility
  pole.
- Smart utilities: parking meter, vehicle charging station/charge point,
  vending machine, parcel locker, ATM and defibrillator cabinet.
- Covers: mapped shelter roof/support structure.
- Vegetation: explicit tree trunk/crown proxy.
- Recreation: swing, slide, seesaw, climbing frame, roundabout and sandbox.
- Fitness: individual or aggregate outdoor fitness stations; preserve
  `fitness_station=*` equipment type when available.

## Fidelity and LOD

Explicit OSM features count as mapped. Semantic dimensions and all procedural
parts count as inferred detail. Do not generate whole playgrounds from the area
tag alone when no equipment is mapped. Do not infer utility connections from a
cabinet/pole/charger point. Keep tree species/crown form generic unless tags or
a run asset provide evidence. Do not infer products or brand livery for
vending/parcel machines, connector types for charging stations, or a wall host
unless one resolves within the bounded mapped-building distance.
Overhead networks are a separate streetscape specialization: build conductors
only from explicit `power=line`/`power=minor_line` axes and never connect these
amenity points merely because they are nearby.

## Acceptance evidence

Report mapped counts by family/kind, generated meshes and parts, explicit
directions, explicit dimensions, inferred infill and objects skipped by radius
or cap. Require at least one distinct grammar per supported kind present in the
input and no geometry explosion at dense-object limits.
