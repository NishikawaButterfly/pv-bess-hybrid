# Historical prototype migration

The two original report and diagram scripts were removed from the current tree after an independent read-only audit found material defects in dispatch, finance, short-circuit, transformer, thermal, EMF, lifecycle, equipment-selection, and compliance calculations. Several hard-coded report statements did not match the code's own outputs, and some attributed data or vendor assumptions lacked public provenance suitable for redistribution.

The old source is not distributed in this repository. It is not part of the installed package, tests, CLI, sample workflow, or supported calculation model. It must not be executed, cited, or used for engineering or investment decisions.

The supported boundary starts at `src/pv_bess/`. Specialist engineering or compliance features will return only after each domain has a traceable methodology, authoritative and redistributable inputs, analytical fixtures, and independent review.
